"""Provider-neutral chat-LLM adapter — the ONE path every chat call takes.

Both hub repos carry a byte-identical copy of this file (scal-ai-pipeline/
llm_adapter.py and pvt-ai-pipeline/src/utils/llm_adapter.py); a test in each
repo fails if the copies drift.

Contract
--------
* Provider and model come from the environment, never from code:
    LLM_PROVIDER    mock | ollama | nvidia | gemini | openai   (default: mock)
    LLM_MODEL       model id sent on the wire               (default: per provider)
    LLM_BASE_URL    OpenAI-compatible chat/completions URL  (default: per provider)
    LLM_API_KEYS    comma-separated key pool (LLM_API_KEY for one key)
    LLM_HTTP_TIMEOUT seconds                                (default: 300)
  A real provider is an explicit, deliberate opt-in: only LLM_PROVIDER selects
  one. A URL, a model name or a key on its own never does (D0). Legacy names
  (SCAL_LLM_BASE_URL / SCAL_LLM_MODEL / NVIDIA_API_KEY*, NVIDIA_HTTP_TIMEOUT)
  still supply the URL / model / keys once a provider is selected.
* `mock` never opens a connection. Null mode (the default): deterministic text
  derived from the messages, no tool calls, no keys. Scripted mode (D2, opt-in
  per test via `adapter.load_script(MockScript)`): a named scenario — a JSON
  fixture in the repo — plays an ordered sequence of assistant turns, tool
  calls, errors, timeouts and slow responses, and records a transcript of what
  the model was sent. Fully deterministic; delays go through `adapter.sleeper`
  so tests need no clock. Fixture shape:
      {"name": "...", "description": "...", "on_exhausted": "error" | "null",
       "steps": [{"assistant": {"text": "...", "tool_calls": [{"name": "...", "args": {...}}]}},
                 {"assistant": "plain text"},
                 {"error": "HTTP 503 upstream"},
                 {"timeout": {"after": 300}},
                 {"slow": {"delay": 5, "text": "...", "tool_calls": [...]}}]}
* `is_cloud(provider)` — nvidia | gemini | openai — is what the startup
  air-gap invariant in each app reads (cloud provider + reachable private
  database = refuse to start).
* The wire format is OpenAI chat/completions, which every supported provider
  speaks (NVIDIA NIM, Gemini's OpenAI-compatible endpoint, Ollama /v1, OpenAI).
  Messages are passed through untouched, so multimodal content parts work.
* `ChatResult.model` is the model that was actually sent — nothing upstream
  may report a different name.
* Keys rotate on failure with a cooldown; a key never appears in a log line or
  an error message (only its first 6 characters, for operators).
* `on_success` / `on_failure` fire once per call and feed the provider-neutral
  liveness signal that /health reads (alerting.record_llm_success/failure).
  on_success is derived from the outcome: it fires only once the provider has
  delivered a message (`choices` in the body / in at least one stream chunk).
  A body that is not JSON or carries no choices, an in-stream `error` event, a
  malformed chunk, or a mid-stream transport error fires on_failure and raises.
  A garbled tool call (unparseable arguments) raises rather than running the
  tool with `{}`; `ChatResult.finish_reason` says whether a reply was cut short.

Embeddings are NOT routed here — that migration is a data migration (C3).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

logger = logging.getLogger("LLMAdapter")

PROVIDERS: Dict[str, Dict[str, str]] = {
    "nvidia": {"base_url": "https://integrate.api.nvidia.com/v1/chat/completions",
               "model": "openai/gpt-oss-120b"},
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
               "model": "gemini-2.5-flash"},
    "ollama": {"base_url": "http://localhost:11434/v1/chat/completions",
               "model": "gemma3n:e2b"},
    "openai": {"base_url": "https://api.openai.com/v1/chat/completions",
               "model": "gpt-4o-mini"},
    "mock": {"base_url": "mock://", "model": "mock"},
}
CLOUD_PROVIDERS = frozenset({"nvidia", "gemini", "openai"})

_KEY_COOLDOWN_S = 60.0
_DEFAULT_TIMEOUT_S = 300.0


def is_cloud(provider: str) -> bool:
    """True for a provider that ships prompts off the machine."""
    return provider in CLOUD_PROVIDERS


class ChatAdapterError(RuntimeError):
    """Raised when a call cannot be completed on any key (never carries a key)."""


@dataclass(frozen=True)
class ChatConfig:
    provider: str
    model: str
    base_url: str
    api_keys: Tuple[str, ...]
    timeout: float = _DEFAULT_TIMEOUT_S


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: Dict[str, object]


@dataclass(frozen=True)
class ChatResult:
    text: str
    tool_calls: List[ToolCall]
    usage: Tuple[int, int]          # (prompt_tokens, completion_tokens)
    model: str                      # the model actually sent on the wire
    raw: Dict[str, object]
    finish_reason: str = ""         # choices[0].finish_reason as sent ("length" = cut at max_tokens)


# -- scripted mock scenarios (D2) ----------------------------------------------------

_STEP_KINDS = ("assistant", "error", "timeout", "slow")


@dataclass(frozen=True)
class MockStep:
    kind: str                       # assistant | error | timeout | slow
    text: str = ""
    tool_calls: Tuple[ToolCall, ...] = ()
    delay: float = 0.0              # seconds slept before acting (slow / timeout)
    detail: str = ""                # error detail


def _parse_step(index: int, raw) -> MockStep:
    if not isinstance(raw, Mapping) or len(raw) != 1 or next(iter(raw)) not in _STEP_KINDS:
        got = sorted(raw) if isinstance(raw, Mapping) else type(raw).__name__
        raise ChatAdapterError(
            f"mock scenario step {index}: expected exactly one of {_STEP_KINDS}, got {got}")
    kind, body = next(iter(raw.items()))
    if kind == "error":
        return MockStep("error", detail=str(body))
    if kind == "timeout":
        after = body.get("after", 0.0) if isinstance(body, Mapping) else body
        return MockStep("timeout", delay=float(after or 0.0))
    body = {"text": body} if isinstance(body, str) else dict(body or {})
    calls = tuple(ToolCall(str(c.get("name", "")), dict(c.get("args") or {}))
                  for c in body.get("tool_calls") or [])
    return MockStep(kind, text=str(body.get("text", "")), tool_calls=calls,
                    delay=float(body.get("delay", 0.0) or 0.0))


class MockScript:
    """A named, ordered scenario for the mock provider (see module docstring)."""

    def __init__(self, name: str, steps: Sequence[MockStep], *, description: str = "",
                 on_exhausted: str = "error") -> None:
        if on_exhausted not in ("error", "null"):
            raise ChatAdapterError(f"mock scenario {name!r}: on_exhausted must be 'error' or 'null'")
        self.name = name
        self.description = description
        self.steps = list(steps)
        self.on_exhausted = on_exhausted
        self.cursor = 0
        self.transcript: List[Dict[str, object]] = []

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "MockScript":
        steps = [_parse_step(i, s) for i, s in enumerate(data.get("steps") or [])]
        return cls(str(data.get("name", "")), steps,
                   description=str(data.get("description", "")),
                   on_exhausted=str(data.get("on_exhausted", "error")))

    @classmethod
    def from_file(cls, path) -> "MockScript":
        with open(path, encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))

    def reset(self) -> None:
        self.cursor = 0
        self.transcript = []

    def take(self, messages: Sequence[Mapping[str, object]], tools) -> Optional[MockStep]:
        """Record what the model was sent; return the next step (None when exhausted)."""
        self.transcript.append({
            "step": self.cursor,
            "messages": [dict(m) for m in messages],
            "tools": [str((t.get("function") or {}).get("name", "")) for t in (tools or [])],
        })
        if self.cursor >= len(self.steps):
            return None
        step = self.steps[self.cursor]
        self.cursor += 1
        return step


def _split_keys(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    return [k.strip(' \n\r\t"\'') for k in raw.split(",") if k.strip(' \n\r\t"\'')]


def load_config(env: Optional[Mapping[str, str]] = None, *, prefix: str = "LLM",
                default_base_url: Optional[str] = None,
                default_model: Optional[str] = None) -> ChatConfig:
    """Build a ChatConfig from environment variables (see module docstring).

    `prefix` lets a second, independently-configured backend coexist (the hub
    agents use AGENT_LLM_* for their local model); `default_*` are the
    caller's URL / model fallbacks once a provider has been selected. The
    provider itself is `{prefix}_PROVIDER` or `mock` — nothing else selects one.
    """
    e = os.environ if env is None else env
    provider = (e.get(f"{prefix}_PROVIDER") or "").strip().lower() or "mock"
    if provider not in PROVIDERS:
        raise ChatAdapterError(
            f"{prefix}_PROVIDER={provider!r} is not one of {sorted(PROVIDERS)}")

    legacy_url = (e.get("SCAL_LLM_BASE_URL") or "").strip() if prefix == "LLM" else ""
    base_url = ((e.get(f"{prefix}_BASE_URL") or "").strip() or legacy_url
                or default_base_url or PROVIDERS[provider]["base_url"])
    legacy_model = (e.get("SCAL_LLM_MODEL") or "").strip() if prefix == "LLM" else ""
    model = ((e.get(f"{prefix}_MODEL") or "").strip() or legacy_model
             or default_model or PROVIDERS[provider]["model"])

    keys: List[str] = _split_keys(e.get(f"{prefix}_API_KEYS")) + _split_keys(e.get(f"{prefix}_API_KEY"))
    if prefix == "LLM" and not keys:
        keys = _split_keys(e.get("NVIDIA_API_KEY"))
        for k in sorted(e):
            if k.startswith("NVIDIA_API_KEY") and k != "NVIDIA_API_KEY":
                keys += _split_keys(e[k])
    keys = list(dict.fromkeys(keys))
    if provider == "ollama" and not keys:
        keys = ["ollama"]          # Ollama ignores auth; one placeholder so the loop runs
    if provider == "mock":
        keys = []                  # never a credential, never a "cloud agent"

    raw_timeout = (e.get(f"{prefix}_HTTP_TIMEOUT") or "").strip() or \
        ((e.get("NVIDIA_HTTP_TIMEOUT") or "").strip() if prefix == "LLM" else "")
    try:
        timeout = float(raw_timeout) if raw_timeout else _DEFAULT_TIMEOUT_S
    except ValueError:
        var = f"{prefix}_HTTP_TIMEOUT" if e.get(f"{prefix}_HTTP_TIMEOUT") else "NVIDIA_HTTP_TIMEOUT"
        raise ChatAdapterError(f"{var}={raw_timeout!r} is not a number of seconds")
    return ChatConfig(provider=provider, model=model, base_url=base_url,
                      api_keys=tuple(keys), timeout=timeout)


def _default_opener(url: str, headers: Dict[str, str], body: bytes, timeout: float):
    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    return urllib.request.urlopen(req, timeout=timeout)


class ChatAdapter:
    def __init__(self, config: ChatConfig,
                 on_success: Optional[Callable[[], None]] = None,
                 on_failure: Optional[Callable[[str], None]] = None,
                 opener: Optional[Callable] = None) -> None:
        self.config = config
        self._on_success = on_success
        self._on_failure = on_failure
        self._open = opener or _default_opener
        self._cooldown: Dict[str, float] = {}
        self._idx = 0
        self._lock = threading.Lock()
        self.script: Optional[MockScript] = None    # mock provider: scripted scenario (opt-in)
        self.sleeper: Callable[[float], None] = time.sleep

    def load_script(self, script: Optional[MockScript]) -> None:
        """Install a scenario on the mock provider (None restores null mode)."""
        if script is not None:
            script.reset()
        self.script = script

    # -- key pool --------------------------------------------------------------

    @staticmethod
    def _mask(key: str) -> str:
        return key[:6] + "…" if len(key) > 6 else "…"

    def keys_in_cooldown(self) -> int:
        now = time.time()
        with self._lock:
            return sum(1 for k in self.config.api_keys if self._cooldown.get(k, 0.0) > now)

    def keys_degraded(self) -> bool:
        if self.config.provider == "mock":
            return False
        return not self.config.api_keys or self.keys_in_cooldown() >= len(self.config.api_keys)

    def state(self) -> Dict[str, object]:
        return {"provider": self.config.provider, "model": self.config.model,
                "base_url": self.config.base_url, "keys": len(self.config.api_keys),
                "keys_in_cooldown": self.keys_in_cooldown()}

    def _ordered_keys(self) -> List[str]:
        keys = list(self.config.api_keys)
        if not keys:
            return []
        now = time.time()
        with self._lock:
            start = self._idx % len(keys)
        rotated = keys[start:] + keys[:start]
        healthy = [k for k in rotated if self._cooldown.get(k, 0.0) <= now]
        return healthy or rotated          # all cooling: try anyway, in order

    def _fail_key(self, key: str) -> None:
        with self._lock:
            self._cooldown[key] = time.time() + _KEY_COOLDOWN_S
            self._idx = (self._idx + 1) % max(1, len(self.config.api_keys))

    # -- payload ---------------------------------------------------------------

    def _payload(self, messages: Sequence[Mapping[str, object]], *, temperature: float,
                 max_tokens: int, tools, response_format, stream: bool,
                 extra: Optional[Mapping[str, object]]) -> Dict[str, object]:
        body: Dict[str, object] = {
            "model": self.config.model,
            "temperature": float(temperature),
            "top_p": 0.95,
            "max_tokens": int(max_tokens),
            "stream": stream,
            "messages": list(messages),
        }
        if self.config.provider == "nvidia":
            # gpt-oss on NIM is a reasoning model; low effort keeps latency inside
            # the chat timeout. Other providers reject or ignore the field.
            body["reasoning_effort"] = "low"
        if tools:
            body["tools"] = list(tools)
            body["tool_choice"] = "auto"
        if response_format:
            body["response_format"] = dict(response_format)
        if extra:
            body.update(extra)
        return body

    def _request(self, body: Dict[str, object], timeout: Optional[float] = None):
        """Try the key pool in order; return the open response of the first success.
        `timeout` (seconds) overrides the configured one — the caller's retry budget
        caps an attempt to the wall clock it has left (D3.3)."""
        per_attempt = float(timeout) if timeout else self.config.timeout
        if not self.config.api_keys:
            raise ChatAdapterError(
                f"no API key configured for provider '{self.config.provider}' "
                f"(set LLM_API_KEYS / LLM_API_KEY)")
        data = json.dumps(body).encode("utf-8")
        errors: List[str] = []
        for key in self._ordered_keys():
            headers = {"accept": "application/json", "content-type": "application/json",
                       "authorization": f"Bearer {key}"}
            try:
                return self._open(self.config.base_url, headers, data, per_attempt)
            except Exception as exc:                        # noqa: BLE001
                detail = str(exc)
                if isinstance(exc, urllib.error.HTTPError) or hasattr(exc, "read"):
                    try:
                        detail = f"{exc}: {exc.read().decode('utf-8', 'replace')[:300]}"
                    except Exception:                       # noqa: BLE001
                        pass
                detail = detail.replace(key, self._mask(key))
                errors.append(detail)
                logger.warning("[LLM %s] call failed on key %s: %s",
                               self.config.provider, self._mask(key), detail[:200])
                self._fail_key(key)
        msg = (f"all {len(self.config.api_keys)} key(s) failed for provider "
               f"'{self.config.provider}' model '{self.config.model}': {errors}")
        if self._on_failure:
            self._on_failure(msg)
        raise ChatAdapterError(msg)

    # -- mock provider (no transport) -----------------------------------------------

    @staticmethod
    def _mock_text(messages: Sequence[Mapping[str, object]]) -> str:
        digest = hashlib.sha256(json.dumps(list(messages), sort_keys=True,
                                           default=str).encode("utf-8")).hexdigest()[:12]
        return f"[mock:{digest}] no model connected"

    def _mock_result(self, messages: Sequence[Mapping[str, object]], tools) -> ChatResult:
        def null() -> ChatResult:
            if self._on_success:
                self._on_success()
            return ChatResult(text=self._mock_text(messages), tool_calls=[], usage=(0, 0),
                              model=self.config.model, raw={})
        script = self.script
        if script is None:
            return null()
        step = script.take(messages, tools)
        if step is None:
            if script.on_exhausted == "null":
                return null()
            raise ChatAdapterError(
                f"mock scenario '{script.name}' exhausted: {len(script.steps)} step(s) "
                f"scripted, {len(script.transcript)} call(s) made")
        index = script.cursor - 1
        if step.delay:
            self.sleeper(step.delay)
        if step.kind in ("error", "timeout"):
            msg = (f"mock scenario '{script.name}' step {index}: timed out after {step.delay}s"
                   if step.kind == "timeout"
                   else f"mock scenario '{script.name}' step {index}: {step.detail}")
            if self._on_failure:
                self._on_failure(msg)
            raise ChatAdapterError(msg)
        if self._on_success:
            self._on_success()
        return ChatResult(text=step.text, tool_calls=list(step.tool_calls), usage=(0, 0),
                          model=self.config.model, raw={"mock_step": index})

    # -- public API --------------------------------------------------------------

    def complete(self, messages: Sequence[Mapping[str, object]], *, tools=None,
                 temperature: float = 0.2, max_tokens: int = 4096,
                 response_format: Optional[Mapping[str, object]] = None,
                 extra: Optional[Mapping[str, object]] = None,
                 timeout: Optional[float] = None) -> ChatResult:
        if self.config.provider == "mock":
            return self._mock_result(messages, tools)
        body = self._payload(messages, temperature=temperature, max_tokens=max_tokens,
                             tools=tools, response_format=response_format,
                             stream=False, extra=extra)
        logger.info("[LLM %s] generate -> model=%s tools=%s msgs=%d",
                    self.config.provider, self.config.model, bool(tools), len(body["messages"]))
        with self._request(body, timeout) as r:
            raw = r.read()
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            self._fail(f"response is not JSON ({exc}): {raw[:300]!r}")
        # An HTTP-200 body without a message (provider error JSON, quota or
        # moderation reply, wrong endpoint) is a failed call, not an empty answer.
        choices = data.get("choices") if isinstance(data, dict) else None
        if not choices:
            self._fail(f"no choices in response: {json.dumps(data)[:300]}")
        choice = choices[0] or {}
        msg = choice.get("message") or {}
        finish_reason = str(choice.get("finish_reason") or "")
        if self._on_success:            # a message envelope arrived: the provider is alive
            self._on_success()
        if finish_reason == "content_filter":
            raise ChatAdapterError("reply blocked by the provider (finish_reason=content_filter)")
        calls: List[ToolCall] = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            name = str(fn.get("name", ""))
            arguments = fn.get("arguments") or "{}"
            try:
                args = json.loads(arguments)
            except (TypeError, ValueError) as exc:
                raise ChatAdapterError(
                    f"tool call '{name}' carried unparseable arguments ({exc}): {str(arguments)[:200]!r}")
            if not isinstance(args, dict):
                raise ChatAdapterError(
                    f"tool call '{name}' arguments are not a JSON object: {str(arguments)[:200]!r}")
            calls.append(ToolCall(name, args))
        # Never surface `reasoning_content`: raw chain-of-thought must not reach a
        # user. An empty reply is an empty reply; callers decide what that means
        # (finish_reason tells them whether it was cut short).
        text = msg.get("content") or ""
        usage = data.get("usage") or {}
        return ChatResult(text=text, tool_calls=calls,
                          usage=(int(usage.get("prompt_tokens", 0) or 0),
                                 int(usage.get("completion_tokens", 0) or 0)),
                          model=self.config.model, raw=data, finish_reason=finish_reason)

    def stream(self, messages: Sequence[Mapping[str, object]], *, temperature: float = 0.2,
               max_tokens: int = 4096,
               extra: Optional[Mapping[str, object]] = None,
               timeout: Optional[float] = None) -> Iterator[str]:
        """Yield text deltas from an SSE chat/completions stream."""
        if self.config.provider == "mock":
            res = self._mock_result(messages, None)
            if res.tool_calls:
                # A tool-bearing turn cannot travel a text-only stream; dropping
                # the calls would present a tool request as a plain answer.
                names = ", ".join(c.name for c in res.tool_calls)
                raise ChatAdapterError(
                    f"stream() carries text only, but the model requested tool call(s): {names} "
                    f"- tool-bearing turns go through complete()")
            if res.text:
                yield res.text
            return
        body = self._payload(messages, temperature=temperature, max_tokens=max_tokens,
                             tools=None, response_format=None, stream=True, extra=extra)
        r = self._request(body, timeout)            # fires on_failure itself when every key fails
        delivered = False                           # at least one chunk carried choices
        try:
            with r:
                for raw in r:
                    line = raw.decode("utf-8", "replace").strip() if isinstance(raw, bytes) else str(raw).strip()
                    if not line.startswith("data:"):
                        continue
                    chunk = line[5:].strip()
                    if chunk == "[DONE]":
                        break
                    try:
                        obj = json.loads(chunk)
                    except ValueError as exc:
                        raise ChatAdapterError(f"malformed SSE chunk ({exc}): {chunk[:200]!r}")
                    if not isinstance(obj, dict):
                        raise ChatAdapterError(f"malformed SSE chunk (not an object): {chunk[:200]!r}")
                    if obj.get("error"):
                        raise ChatAdapterError(
                            f"provider error in stream: {json.dumps(obj['error'])[:300]}")
                    choices = obj.get("choices") or []
                    if choices:
                        delivered = True
                    delta = ((choices or [{}])[0].get("delta") or {}).get("content")
                    if delta:
                        yield delta
        except Exception as exc:                    # noqa: BLE001 — the hook, then the caller
            if self._on_failure:
                self._on_failure(f"stream failed: {exc}"[:500])
            raise
        if not delivered:
            self._fail("stream ended without any message (no choices delivered)")
        if self._on_success:
            self._on_success()

    def _fail(self, msg: str) -> None:
        """Record a failed call on the liveness signal, then raise it to the caller."""
        if self._on_failure:
            self._on_failure(msg)
        raise ChatAdapterError(msg)
