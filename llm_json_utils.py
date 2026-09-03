"""Robust JSON handling for LLM outputs — shared by the report/extraction pipeline.

The report pipeline now runs on NVIDIA NIM (openai/gpt-oss-120b), which
occasionally wraps JSON in ```json fences or surrounds it with prose /
reasoning text. These helpers are stdlib-only (safe for offline CI) and are
used by app.py, hviel_doc_engine.py and llm_insight_generator.py.

Layers of defense:
  1. strip_code_fences()  — prefer the contents of a fenced ```json block.
  2. parse_llm_json()     — direct json.loads, then a balanced-scan fallback
                            that tolerates leading/trailing prose.
  3. llm_json_with_retry()— one corrective re-prompt on parse failure.
"""

import json
import re

__all__ = [
    "LLMJsonParseError",
    "CORRECTIVE_JSON_PROMPT",
    "strip_code_fences",
    "parse_llm_json",
    "llm_json_with_retry",
]


class LLMJsonParseError(ValueError):
    """Raised when no JSON object/array can be recovered from an LLM reply."""


CORRECTIVE_JSON_PROMPT = (
    "Your previous reply could not be parsed as JSON. Respond again with ONLY "
    "the valid JSON object or array — no markdown code fences, no explanation, "
    "no text before or after the JSON. Preserve exactly the same data and "
    "schema you intended in your previous reply."
)

_FENCE_BLOCK_RE = re.compile(r"```[a-zA-Z0-9_-]*[ \t]*\r?\n?(.*?)```", re.DOTALL)


def strip_code_fences(text: str) -> str:
    """Strip markdown code fences from an LLM reply.

    If the reply contains a fenced block whose body looks like JSON, return
    that body (this tolerates prose around the fence). Otherwise drop any
    stray fence marker lines and return the rest.
    """
    if text is None:
        return ""
    t = str(text).strip()
    if "```" not in t:
        return t
    for block in _FENCE_BLOCK_RE.findall(t):
        body = block.strip()
        if body.startswith("{") or body.startswith("["):
            return body
    # Fence markers present but no JSON-looking block: drop the marker lines.
    lines = [ln for ln in t.splitlines() if not ln.strip().startswith("```")]
    return "\n".join(lines).strip()


def parse_llm_json(text: str):
    """Parse a JSON object/array out of an LLM reply.

    Tolerates markdown code fences and leading/trailing prose. Returns the
    parsed dict/list. Raises LLMJsonParseError when nothing parseable is found.
    """
    if text is None:
        raise LLMJsonParseError("empty LLM response")
    t = strip_code_fences(text)
    if not t:
        raise LLMJsonParseError("empty LLM response after fence cleanup")
    try:
        parsed = json.loads(t)
        if isinstance(parsed, (dict, list)):
            return parsed
    except ValueError:
        pass
    # Balanced-scan fallback: try every '{' / '[' start position and let the
    # decoder find the matching end, ignoring whatever prose surrounds it.
    decoder = json.JSONDecoder()
    for m in re.finditer(r"[\[{]", t):
        try:
            candidate, _end = decoder.raw_decode(t, m.start())
        except ValueError:
            continue
        if isinstance(candidate, (dict, list)):
            return candidate
    raise LLMJsonParseError("no valid JSON object/array found in LLM response")


def llm_json_with_retry(generate_fn, corrective_prompt: str = CORRECTIVE_JSON_PROMPT,
                        logger=None):
    """Call generate_fn(None) -> raw text and parse it as JSON.

    On parse failure, calls generate_fn(corrective_prompt) exactly once (the
    callable decides how to weave the corrective instruction into its prompt)
    and parses that. Raises LLMJsonParseError if the retry also fails.
    """
    raw = generate_fn(None)
    try:
        return parse_llm_json(raw)
    except LLMJsonParseError as first_err:
        if logger is not None:
            try:
                logger.warning(
                    "[LLM-JSON] parse failed (%s); one corrective retry...", first_err
                )
            except Exception:
                pass
        raw_retry = generate_fn(corrective_prompt)
        try:
            return parse_llm_json(raw_retry)
        except LLMJsonParseError as second_err:
            raise LLMJsonParseError(
                "LLM JSON parse failed after corrective retry: "
                f"first={first_err}; retry={second_err}"
            ) from second_err
