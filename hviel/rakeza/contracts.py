"""Rakeza Supervisor Agent — inter-agent delegation contracts.

Rakeza supervises two worker agents:
- Hviel (scal-ai-pipeline, port 8000) — SCAL / special core analysis.
- Aviel (pvt-ai-pipeline, port 8001)  — PVT / fluid properties.

These Pydantic schemas are the wire contract for delegation and synthesis.
Two hard rules learned from the Hviel tool-laundering incident are enforced at
the contract level:

1. Routing validation — a DelegationRequest whose agent/domain pairing is
   wrong fails validation; it cannot be constructed, so a misrouted task can
   never reach a worker silently.
2. No failure laundering — a WorkerResponse with ok=True must carry a
   non-empty answer, and ok=False must carry an explicit error. "Empty
   success" is unrepresentable.

Synthesis follows the harness's reason-first CoT format: reasoning is the
FIRST field and the prompt demands it before any conclusion.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class WorkerAgent(str, Enum):
    HVIEL = "hviel"   # SCAL pipeline
    AVIEL = "aviel"   # PVT pipeline


AGENT_DOMAIN = {WorkerAgent.HVIEL: "SCAL", WorkerAgent.AVIEL: "PVT"}


# Metadata filters Aviel's PVT retrieval accepts. fluid_type / well_name /
# pvt_report_id are the PVT-document taxonomy; doc_type / shelf map onto the
# columns Aviel's KB stores today (kb_chunks.doc_type, kb_chunks.shelf).
PVT_METADATA_FILTERS = ("fluid_type", "well_name", "pvt_report_id", "doc_type", "shelf")


class RagOptions(BaseModel):
    """Worker-side retrieval options riding on a delegation.

    For aviel these serialize into the PVT RAG payload (today the filters ride
    along with POST /api/chat, which runs KB retrieval internally; a dedicated
    POST /api/pvt/rag/search consumes the same payload once Aviel exposes it).
    """
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    top_k: int = Field(default=5, ge=1, le=25)
    fluid_type: Optional[Literal[
        "black_oil", "volatile_oil", "gas_condensate", "wet_gas", "dry_gas"
    ]] = None
    well_name: Optional[str] = None
    pvt_report_id: Optional[str] = None
    doc_type: Optional[Literal["reference", "session"]] = None
    shelf: Optional[str] = None


class DelegationRequest(BaseModel):
    """Rakeza → worker task hand-off."""
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1)
    agent: WorkerAgent
    domain: Literal["SCAL", "PVT"]
    query: str = Field(min_length=1)
    session_id: Optional[str] = None
    rag_route: Optional[Literal["VECTOR_SEARCH", "GRAPH_SEARCH", "HYBRID"]] = None
    rag: Optional[RagOptions] = None

    @model_validator(mode="after")
    def _validate_routing(self) -> "DelegationRequest":
        expected = AGENT_DOMAIN[self.agent]
        if self.domain != expected:
            raise ValueError(
                f"routing violation: agent '{self.agent.value}' owns domain "
                f"'{expected}', got '{self.domain}'"
            )
        return self


class WorkerResponse(BaseModel):
    """Worker → Rakeza result envelope."""
    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(min_length=1)
    agent: WorkerAgent
    ok: bool
    answer: str = ""
    error: Optional[str] = None
    citations: List[str] = Field(default_factory=list)
    latency_s: Optional[float] = None
    # Fallbacks the worker took while answering (its own "degradations" list:
    # KB search failed, chat provider fell back, ...). ok=True with a
    # non-empty list is a degraded answer and is surfaced as such.
    degradations: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _no_failure_laundering(self) -> "WorkerResponse":
        if self.ok:
            if not self.answer.strip():
                raise ValueError("ok=True requires a non-empty answer (empty success is laundering)")
            if self.error:
                raise ValueError("ok=True must not carry an error")
        else:
            if not (self.error or "").strip():
                raise ValueError("ok=False requires an explicit error detail")
        return self


class SupervisorSynthesis(BaseModel):
    """Rakeza's final synthesized reply. reasoning is deliberately the first
    field — the reason-first CoT contract."""
    model_config = ConfigDict(extra="forbid")

    reasoning: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    sources: List[WorkerAgent] = Field(min_length=1)


# ── deterministic worker routing ─────────────────────────────────────────────

# Public: src.rag.router imports these as the single source of domain vocabulary.
PVT_KEYWORDS = (
    "pvt", "bubble point", " pb", "solution gor", " rs", " bo", "fvf",
    "formation volume factor", "oil viscosity", "gas gravity", "api gravity",
    "undersaturated", "flash", "eclipse pvto",
)
SCAL_KEYWORDS = (
    "scal", "relative permeability", "kr ", "krw", "kro", "capillary",
    "micp", "mercury injection", "archie", "formation factor",
    "resistivity index", "brooks-corey", "brooks corey", "swi", "sor",
    "displacement efficiency", "centrifuge", "overburden porosity",
)


def route_worker(query: str) -> WorkerAgent:
    """Pick the worker whose domain vocabulary dominates the query.
    Ties and no-signal queries go to Hviel (SCAL is the hub's primary domain).
    """
    low = f" {(query or '').lower()} "
    pvt_hits = sum(1 for k in PVT_KEYWORDS if k in low)
    scal_hits = sum(1 for k in SCAL_KEYWORDS if k in low)
    return WorkerAgent.AVIEL if pvt_hits > scal_hits else WorkerAgent.HVIEL


def make_delegation(task_id: str, query: str, session_id: Optional[str] = None,
                    rag_route: Optional[str] = None,
                    rag: Optional[RagOptions] = None) -> DelegationRequest:
    """Construct a routing-valid DelegationRequest: agent chosen by
    route_worker, domain derived from the agent — an invalid pairing is
    unconstructable through this factory."""
    agent = route_worker(query)
    return DelegationRequest(
        task_id=task_id, agent=agent, domain=AGENT_DOMAIN[agent],
        query=query, session_id=session_id, rag_route=rag_route, rag=rag,
    )


def build_aviel_rag_payload(request: DelegationRequest) -> dict:
    """Wire payload for Aviel's PVT retrieval.

    Clean-format guarantees: only non-null filters serialize (no null keys on
    the wire), filter keys are restricted to PVT_METADATA_FILTERS, and the
    payload carries no SCAL-side structure — it is rejected outright for a
    non-aviel delegation instead of leaking cross-domain content.
    """
    if request.agent is not WorkerAgent.AVIEL:
        raise ValueError(
            f"PVT RAG payload requested for agent '{request.agent.value}' — "
            "only aviel delegations carry PVT retrieval options"
        )
    rag = request.rag or RagOptions()
    payload: dict = {"query": request.query, "top_k": rag.top_k}
    filters = {
        key: getattr(rag, key)
        for key in PVT_METADATA_FILTERS
        if getattr(rag, key) is not None
    }
    if filters:
        payload["filters"] = filters
    if request.session_id:
        payload["session_id"] = request.session_id
    return payload


def build_synthesis_prompt(query: str, responses: List[WorkerResponse]) -> str:
    """Reason-first CoT synthesis prompt. Failed workers are surfaced
    explicitly so the supervisor acknowledges them instead of papering over
    the gap with invented content."""
    blocks = []
    for r in responses:
        if r.ok and r.degradations:
            blocks.append(
                f"[{r.agent.value.upper()} — OK but DEGRADED: {'; '.join(r.degradations)}]\n"
                f"{r.answer}\n"
                "This worker fell back on the items above; treat the affected parts as unverified."
            )
        elif r.ok:
            blocks.append(f"[{r.agent.value.upper()} — OK]\n{r.answer}")
        else:
            blocks.append(
                f"[{r.agent.value.upper()} — FAILED: {r.error}]\n"
                "This worker produced NO result. Acknowledge the gap; do not invent its data."
            )
    worker_section = "\n\n".join(blocks) if blocks else "[no worker responses]"
    return (
        "You are Rakeza, the PRC AI Hub supervisor. Synthesize the worker "
        "agent results below into one reply.\n"
        "Reason FIRST, then answer: (a) restate what each worker contributed, "
        "(b) note any failed workers and what is therefore unknown, (c) check "
        "the contributions against the user's question. Only then write the "
        "final answer. Never fabricate data a worker did not return.\n\n"
        f"### USER QUESTION\n{query}\n\n"
        f"### WORKER RESULTS\n{worker_section}\n\n"
        "Respond as JSON with the reasoning field FIRST:\n"
        '{"reasoning": "<your step-by-step analysis>", '
        '"answer": "<final synthesized reply>", '
        '"sources": ["hviel" and/or "aviel"]}'
    )
