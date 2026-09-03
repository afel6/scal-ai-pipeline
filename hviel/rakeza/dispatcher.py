"""Rakeza Supervisor — live worker-agent dispatcher.

Executes DelegationRequests (built by contracts.make_delegation) against the
running worker services over HTTP:

- hviel → Hviel SCAL pipeline: POST {HVIEL_BASE_URL}/api/chat
          (multipart/form contract; reply JSON carries "reply").
- aviel → Aviel PVT pipeline:  POST {AVIEL_BASE_URL}/api/chat
          (JSON contract {message, session_id, stream}; reply carries "text").
Either reply may carry "status": "error" (in-band failure -> ok=False) and a
"degradations" list (fallbacks the worker took -> copied onto the envelope).

Every execution — success, HTTP error, timeout, connection refusal, or an
empty reply — is wrapped in a WorkerResponse envelope. The envelope's own
validators make failure laundering unrepresentable (ok=True requires a
non-empty answer; ok=False requires an explicit error), so a dead worker is
always visible to the supervisor's synthesis step.

Auth note: Hviel's /api/chat enforces token auth outside pytest — pass
`hviel_token` (a bearer token from Hviel's login flow) for production
dispatch. Aviel's chat endpoint is unauthenticated. stdlib-only by design.
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from typing import List, Optional

from hviel.rakeza.contracts import DelegationRequest, WorkerAgent, WorkerResponse

HVIEL_DEFAULT_BASE = "http://localhost:8000"
AVIEL_DEFAULT_BASE = "http://localhost:8001"

# Eval identity: Hviel treats this sender as a semantic-cache bypass, so
# dispatched evals always grade a fresh generation.
_DISPATCH_EMAIL = "test@prc.local"


def _post_json(url: str, data: bytes, headers: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def dispatch(request: DelegationRequest, *,
             hviel_base_url: Optional[str] = None,
             aviel_base_url: Optional[str] = None,
             hviel_token: Optional[str] = None,
             aviel_token: Optional[str] = None,
             timeout: float = 300.0) -> WorkerResponse:
    """Execute one delegation against its live worker and envelope the result."""
    t0 = time.monotonic()
    try:
        if request.agent is WorkerAgent.HVIEL:
            base = (hviel_base_url or os.environ.get("HVIEL_BASE_URL", "")
                    or HVIEL_DEFAULT_BASE).rstrip("/")
            form = {"message": request.query, "user_email": _DISPATCH_EMAIL}
            if request.session_id:
                form["session_id"] = request.session_id
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            if hviel_token:
                headers["Authorization"] = f"Bearer {hviel_token}"
            payload = _post_json(f"{base}/api/chat",
                                 urllib.parse.urlencode(form).encode("utf-8"),
                                 headers, timeout)
            answer = str(payload.get("reply") or "").strip()
        else:
            base = (aviel_base_url or os.environ.get("AVIEL_BASE_URL", "")
                    or AVIEL_DEFAULT_BASE).rstrip("/")
            body = json.dumps({
                "message": request.query,
                "session_id": request.session_id or "rakeza-dispatch",
                "stream": False,
            }).encode("utf-8")
            headers = {"Content-Type": "application/json"}
            # Aviel /api/chat now requires its Bearer token (KB_INGEST_PASSWORD).
            a_token = aviel_token or os.environ.get("AVIEL_API_TOKEN", "")
            if a_token:
                headers["Authorization"] = f"Bearer {a_token}"
            payload = _post_json(f"{base}/api/chat", body, headers, timeout)
            answer = str(payload.get("text") or "").strip()

        latency = round(time.monotonic() - t0, 3)
        # Both workers answer HTTP 200 with {"status": "error", ...} for an
        # in-band failure (Hviel: "Processing error: ..."); the reply text is
        # then the error, never an answer.
        if str(payload.get("status") or "").lower() == "error":
            return WorkerResponse(
                task_id=request.task_id, agent=request.agent, ok=False,
                error=answer or "worker reported status=error", latency_s=latency,
            )
        if not answer:
            return WorkerResponse(
                task_id=request.task_id, agent=request.agent, ok=False,
                error="worker returned an empty answer", latency_s=latency,
            )
        degradations = [str(d) for d in (payload.get("degradations") or [])]
        return WorkerResponse(
            task_id=request.task_id, agent=request.agent, ok=True,
            answer=answer, latency_s=latency, degradations=degradations,
        )
    except Exception as exc:
        return WorkerResponse(
            task_id=request.task_id, agent=request.agent, ok=False,
            error=f"{type(exc).__name__}: {exc}",
            latency_s=round(time.monotonic() - t0, 3),
        )


def dispatch_all(requests: List[DelegationRequest], **kwargs) -> List[WorkerResponse]:
    """Execute delegations sequentially (Hviel's chat is rate-limited 10/min;
    Aviel likewise — sequential keeps a joint case well under both)."""
    return [dispatch(r, **kwargs) for r in requests]
