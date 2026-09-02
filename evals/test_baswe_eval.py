"""BASWE evaluation gate for the Hviel SCAL AI Pipeline.

Layer 0 — offline, deterministic, zero API keys: dataset schema, PhysicsGuard
monotonicity rules, sandbox fit health-vs-R² independence, prompt-injection
sanitizer, tool-failure marker propagation, and the grader's hallucinated-well
blocklist.

Layer 1 — live E2E over POST /api/chat via TestClient, active only when
RUN_LIVE_EVALS=1 and an NVIDIA NIM key is configured. All requests use sender
email test@prc.local, which app.py treats as a semantic-cache bypass
(response_cache replay is skipped), so every run exercises the real
gpt-oss-120b pipeline.
"""
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from grader import run_checks, value_in_text, grade_ai_response
from physics_validator import PhysicsGuard


def load_golden() -> dict:
    with (Path(__file__).with_name("golden_dataset.json")).open(encoding="utf-8") as f:
        return json.load(f)


def nvidia_api_key() -> str:
    """First non-empty key from the NVIDIA_API_KEY / NVIDIA_API_KEY1..N pool."""
    base = os.environ.get("NVIDIA_API_KEY", "").strip()
    if base:
        return base
    for k in sorted(os.environ):
        if k.startswith("NVIDIA_API_KEY") and os.environ[k].strip():
            return os.environ[k].strip()
    return ""


def _local_llm_endpoint() -> str:
    """SCAL_LLM_BASE_URL when it points at a local (keyless) OpenAI-compatible
    endpoint — the post-NVIDIA Ollama setup."""
    url = os.environ.get("SCAL_LLM_BASE_URL", "").strip()
    return url if ("localhost" in url or "127.0.0.1" in url) else ""


def _local_llm_up() -> bool:
    url = _local_llm_endpoint()
    if not url:
        return False
    try:
        origin = url.split("/v1/")[0]
        with urllib.request.urlopen(origin, timeout=3):
            return True
    except Exception:
        return False


LIVE_ENABLED = os.environ.get("RUN_LIVE_EVALS") == "1" and (
    bool(nvidia_api_key()) or _local_llm_up()
)

live_only = pytest.mark.skipif(
    not LIVE_ENABLED,
    reason=("Layer 1 live evals require RUN_LIVE_EVALS=1 plus a chat backend: "
            "NVIDIA_API_KEY, or a reachable local endpoint at SCAL_LLM_BASE_URL "
            "(Ollama serving)"),
)

_GOLDEN = load_golden()
_CASES = {c["id"]: c for c in _GOLDEN["cases"]}
_DEFAULTS = _GOLDEN["defaults"]

_EMPTY_TRUTH = {"well": None, "company": None, "samples": [], "all_values": {}}


# ══════════════════════════════════════════════════════════════════════════════
# Layer 0 — offline gate (no API keys, fast, deterministic)
# ══════════════════════════════════════════════════════════════════════════════

def test_golden_dataset_schema():
    assert re.fullmatch(r"\d+\.\d+\.\d+", _GOLDEN["schema_version"])
    assert len(_GOLDEN["cases"]) >= 3
    ids = [c["id"] for c in _GOLDEN["cases"]]
    assert len(ids) == len(set(ids)), "case ids must be unique"
    for case in _GOLDEN["cases"]:
        assert case["id"] and case["category"] and case["prompt"]
        assert "fixture" in case, f"{case['id']}: fixture key required (null allowed)"
    required = {"happy-micp-summary", "edge-multiquestion-ed-formula",
                "adversarial-injection-and-ungrounded-data"}
    assert required <= set(ids)


def test_golden_dataset_fixtures_exist():
    for case in _GOLDEN["cases"]:
        if case["fixture"]:
            path = REPO_ROOT / case["fixture"]
            assert path.exists(), f"{case['id']}: missing fixture {path}"


def test_ed_reference_formula():
    # Ed = (1 - Swi - Sor) / (1 - Swi); CLAUDE.md-mandated diagnostic value 0.621.
    ed = (1 - 0.42 - 0.22) / (1 - 0.42)
    assert abs(ed - 0.621) / 0.621 <= 0.02
    # The banned formula must NOT land inside tolerance, or the eval can't tell them apart.
    banned = (0.42 - 0.22) / 0.42
    assert abs(banned - 0.621) / 0.621 > 0.02


def test_physics_guard_flags_nonmonotonic_krw():
    sw = [0.20, 0.35, 0.50, 0.65, 0.80]
    krw = [0.00, 0.10, 0.05, 0.30, 0.60]  # dip at Sw=0.50
    kro = [0.90, 0.60, 0.35, 0.12, 0.00]
    health = PhysicsGuard().validate_kr(sw, krw, kro).generate_health_score()
    rules = {v["rule"] for v in health["violations"]}
    assert "KRW_MONOTONICITY" in rules
    assert health["score"] < 95
    assert health["grade"] != "A"


def test_physics_guard_passes_clean_curves():
    swi, sor = 0.2, 0.2
    sw = np.linspace(swi, 1 - sor, 25)
    swn = (sw - swi) / (1 - swi - sor)
    krw = 0.65 * swn ** 2
    kro = 0.90 * (1 - swn) ** 2
    health = PhysicsGuard().validate_kr(sw, krw, kro).generate_health_score()
    assert health["grade"] in _DEFAULTS["physics"]["passing_grades"], health["violations"]


def test_sandbox_fit_health_and_r2_are_independent_gates():
    """Groundedness-vs-fit invariant: a Brooks-Corey fit must clear BOTH the
    PhysicsGuard grade AND R² ≥ 0.90 — asserted separately so a great R² on
    unphysical curves (or physical curves that fit nothing) cannot pass."""
    from physics_sandbox import PhysicsSandbox
    from petrophysical_curves import Endpoints, bc_krw, bc_kro

    swi, sor = 0.25, 0.20
    ep = Endpoints(Swi=swi, Sor=sor, Krw_max=0.60, Kro_max=0.85)
    sw = np.linspace(swi, 1 - sor, 20)
    krw = bc_krw(sw, ep, 2.5)
    kro = bc_kro(sw, ep, 2.0)

    fit = PhysicsSandbox().fit_brooks_corey(sw, krw, kro, swi=swi, sor=sor,
                                            krw_max=0.60, kro_max=0.85)
    min_r2 = _DEFAULTS["physics"]["min_r2"]
    assert fit["health"]["grade"] in _DEFAULTS["physics"]["passing_grades"], fit["health"]
    assert fit["parameters"]["r2_krw"] >= min_r2
    assert fit["parameters"]["r2_kro"] >= min_r2


def test_sanitize_prompt_neutralizes_injection():
    from app import sanitize_prompt

    attack = _CASES["adversarial-injection-and-ungrounded-data"]["prompt"]
    out = sanitize_prompt(attack)
    low = out.lower()
    assert "ignore all previous instructions" not in low
    assert "reveal your system prompt" not in low
    assert "[PROMPT INJECTION BLOCK]" in out
    # Benign petrophysics must pass through untouched.
    benign = "Fit Brooks-Corey with Swi=0.42 and Sor=0.22 and show the Ed formula."
    assert sanitize_prompt(benign) == benign


def test_unknown_tool_failure_is_not_laundered():
    """Tool-failure propagation: a bogus tool call must yield ok=False with its
    error marker intact, increment the failure ledger, and produce an explicit
    [TOOL FAILURE: ...] block in the model-turn summary — never a silent
    'Action complete' success."""
    from app import assistant, TOOL_FAILURE_COUNTS

    tool = "definitely_not_a_real_tool"
    before = TOOL_FAILURE_COUNTS[tool]
    call = SimpleNamespace(name=tool, args={})
    finals = [(ok, data) for is_final, ok, data in assistant._execute_tool(call) if is_final]
    assert finals, "tool generator yielded no final result"
    ok, data = finals[0]
    assert ok is False
    assert "Unknown tool:" in data
    assert TOOL_FAILURE_COUNTS[tool] == before + 1

    summary = assistant._tool_result_summary(tool, data, ok=False)
    assert summary["status"] == "error"
    assert f"[TOOL FAILURE: {tool} returned error:" in summary["note"]


def test_error_payload_summary_never_reports_executed():
    """Defense in depth: even with ok=True, an error-shaped payload must not be
    summarized to the model as a completed step."""
    from app import assistant

    err_payload = '{"status": "error", "error": "simulated crash"}'
    summary = assistant._tool_result_summary("execute_python_simulation", err_payload, ok=True)
    assert summary["status"] == "error"
    assert "[TOOL FAILURE:" in summary["note"]
    assert "simulated crash" in summary["error"]


def test_grader_flags_hallucinated_wells():
    text = "The analysis for Well A and PCY4Q shows porosity of 0.18."
    checks = run_checks(text, _EMPTY_TRUTH)
    rule = next(c for c in checks if c["rule"] == "No hallucinated well name")
    assert rule["status"] == "FAIL"

    clean = "Well T1-31 shows a threshold pressure of 215 psi, well above seal capacity."
    checks = run_checks(clean, _EMPTY_TRUTH)
    rule = next(c for c in checks if c["rule"] == "No hallucinated well name")
    assert rule["status"] == "PASS", "word-boundary blocklist must not fire on normal prose"


def test_grader_numeric_tolerance():
    assert value_in_text("Ed = 0.62 (fraction)", 0.621, tolerance=0.02)
    assert value_in_text("Ed is 62.1%", 62.1, tolerance=0.02)
    assert not value_in_text("Ed = 0.476", 0.621, tolerance=0.02)


# ══════════════════════════════════════════════════════════════════════════════
# Layer 0 — multi-agent orchestrator contracts (MasterEngineerNode)
# ══════════════════════════════════════════════════════════════════════════════

from typing import Optional as _Optional

from pydantic import BaseModel, ConfigDict


class ScalRowPayload(BaseModel):
    """Inter-agent contract: one row of the validated/enriched SCAL payload the
    domain nodes (extraction + prc_physics enrichment) hand to MasterEngineerNode.
    Extraction adds arbitrary lab columns, so extras are allowed — but the core
    keys, when present, must carry these exact types."""
    model_config = ConfigDict(extra="allow", strict=True)

    Pressure_psi: _Optional[float] = None
    Porosity_percent: _Optional[float] = None
    Air_Permeability_md: _Optional[float] = None
    Pore_Volume_Compressibility_psi_inv: _Optional[float] = None
    Deduced_Lithology: _Optional[str] = None
    brooks_corey_Swi: _Optional[float] = None
    brooks_corey_Sor: _Optional[float] = None


_SWEEP_ROWS = [
    {"Pressure_psi": 800.0, "Porosity_percent": 21.5, "Air_Permeability_md": 130.0},
    {"Pressure_psi": 2000.0, "Porosity_percent": 20.9, "Air_Permeability_md": 118.0},
    {"Pressure_psi": 3500.0, "Porosity_percent": 20.1, "Air_Permeability_md": 101.0},
]


def test_domain_node_rows_match_master_engineer_contract():
    """calculate_compressibility_sweep output (the payload wired into
    MasterEngineerNode.analyze_scal_data at app.py:9957) must validate against
    the inter-agent Pydantic contract, enrichment keys included."""
    from prc_physics import calculate_compressibility_sweep

    enriched = calculate_compressibility_sweep([dict(r) for r in _SWEEP_ROWS])
    assert len(enriched) == len(_SWEEP_ROWS)
    for row in enriched:
        ScalRowPayload.model_validate(row)  # raises on any type mismatch
        assert "Pore_Volume_Compressibility_psi_inv" in row
        assert isinstance(row["Deduced_Lithology"], str) and row["Deduced_Lithology"]


def test_master_engineer_receives_untruncated_payload():
    """Report synthesis contract: the full sub-agent JSON must reach the
    MasterEngineerNode prompt byte-exact (no truncation/mangling), the system
    instruction must demand both report sections, and the node must pass the
    LLM text through unmodified."""
    from llm_insight_generator import MasterEngineerNode

    payload = [
        {"Pressure_psi": 500.0 + 137.0 * i, "Porosity_percent": 23.0 - 0.11 * i,
         "Air_Permeability_md": 150.0 - 2.7 * i, "Deduced_Lithology": "Stiff Carbonate"}
        for i in range(40)
    ]
    captured = {}

    def spy_llm(prompt, system_instruction=None, temperature=0.2):
        captured["prompt"] = prompt
        captured["system"] = system_instruction
        return "### Reservoir Report\nR-BODY\n### Visualizer Directive\nV-BODY"

    node = MasterEngineerNode(api_key="DUMMY_KEY", llm_call=spy_llm)
    out = node.analyze_scal_data(payload)

    assert json.dumps(payload, indent=2) in captured["prompt"], \
        "sub-agent JSON was truncated or mangled before reaching MasterEngineerNode"
    assert "### Reservoir Report" in captured["system"]
    assert "### Visualizer Directive" in captured["system"]
    assert out == "### Reservoir Report\nR-BODY\n### Visualizer Directive\nV-BODY"


def test_master_engineer_offline_report_sections():
    """Keyless fallback must still honor the two-section output contract the
    downstream report pipeline parses (dashboard_architect consumes the directive)."""
    from llm_insight_generator import MasterEngineerNode

    out = MasterEngineerNode(api_key="DUMMY_KEY", llm_call=None).analyze_scal_data(_SWEEP_ROWS)
    assert "### Reservoir Report" in out
    assert "### Visualizer Directive" in out


# ══════════════════════════════════════════════════════════════════════════════
# Layer 0 — Aviel (pvt-ai-pipeline) cross-repo contract tests
# Run in the hub layout (sister checkout present); skip cleanly in isolated CI.
# ══════════════════════════════════════════════════════════════════════════════

PVT_ROOT = REPO_ROOT.parent / "pvt-ai-pipeline"

pvt_available = pytest.mark.skipif(
    not PVT_ROOT.exists(),
    reason="pvt-ai-pipeline checkout not present (cross-repo contract tests run in the hub layout)",
)


def _pvt_import(module: str):
    import importlib
    if str(PVT_ROOT) not in sys.path:
        sys.path.insert(0, str(PVT_ROOT))
    return importlib.import_module(module)


@pvt_available
def test_aviel_bo_clamp_holds_through_correlations():
    physics = _pvt_import("src.models.pvt_physics")
    bo_min = _GOLDEN["aviel"]["physics"]["bo_min"]
    for corr in ("standing", "vasquez_beggs", "glaso"):
        for p in (100.0, 1500.0, 3000.0, 6000.0):
            res = physics.evaluate_point(p, 180.0, 32.0, 0.75, correlation=corr)
            assert res.bo >= bo_min, f"{corr} @ {p} psia: Bo={res.bo}"
            assert res.pb > 0.0


@pvt_available
def test_aviel_physicsguard_catches_raw_bo_violation():
    """Bo >= 1 is unreachable through the correlations (they clamp), so the
    guard is exercised with a raw PVTResult — proving bo_ge_1 is a live check,
    not dead code."""
    physics = _pvt_import("src.models.pvt_physics")
    validator = _pvt_import("src.data.pvt_validator")

    bad = physics.PVTResult(
        pressure=3000.0, temp_f=180.0, api=32.0, gas_gravity=0.75,
        correlation="standing", pb=2500.0, rs=600.0, bo=0.85,
        oil_density=52.0, viscosity=0.9, saturated=True,
    )
    report = validator.PhysicsGuard().evaluate(bad, log=False)
    assert report.passed is False
    assert report.checks.get("bo_ge_1") is False
    assert any("Bo" in v for v in report.violations)


@pvt_available
def test_aviel_viscosity_strictly_decreases_with_temperature():
    physics = _pvt_import("src.models.pvt_physics")
    mus = [physics.saturated_oil_viscosity(500.0, t, 32.0)
           for t in (120.0, 150.0, 180.0, 210.0, 240.0)]
    assert all(a > b for a, b in zip(mus, mus[1:])), f"viscosity not strictly decreasing: {mus}"


@pvt_available
def test_aviel_fallback_markers_match_source():
    """Drift tripwire: the silent-fallback detector (Layer 1) matches these
    markers against live replies. If Aviel rewrites its local responder template,
    this fails loudly instead of letting the detector rot into a false PASS."""
    src_text = (PVT_ROOT / "src" / "api" / "app.py").read_text(encoding="utf-8")
    markers = _GOLDEN["aviel"]["fallback_markers"]
    assert markers, "aviel.fallback_markers must not be empty"
    for marker in markers:
        assert marker in src_text, (
            f"stale fallback marker {marker!r} — Aviel's local responder changed; "
            "update aviel.fallback_markers in golden_dataset.json"
        )


def test_aviel_dataset_contract():
    aviel = _GOLDEN["aviel"]
    assert aviel["rate_limit_per_min"] == 10
    ids = [c["id"] for c in aviel["cases"]]
    assert "aviel-bo-physicsguard-raw" in ids
    assert "aviel-cloud-fallback-truthfulness" in ids


# ══════════════════════════════════════════════════════════════════════════════
# Layer 0 — Dual-RAG router + Rakeza supervisor contracts
# ══════════════════════════════════════════════════════════════════════════════

from pydantic import ValidationError

from hviel.rag.router import RagRoute, classify_query
from hviel.rakeza.contracts import (
    AGENT_DOMAIN,
    DelegationRequest,
    SupervisorSynthesis,
    WorkerAgent,
    WorkerResponse,
    build_synthesis_prompt,
    make_delegation,
)


@pytest.mark.parametrize("query,expected", [
    ("What is the exact threshold pressure value for sample S-2 in psi?",
     RagRoute.VECTOR_SEARCH),
    ("Define the Archie cementation exponent equation.",
     RagRoute.VECTOR_SEARCH),
    ("Which analog wells in the Sirte Basin are related to this formation?",
     RagRoute.GRAPH_SEARCH),
    ("Find analog wells with porosity between 0.20 and 0.24 and summarize their threshold pressures in psi.",
     RagRoute.HYBRID),
    ("Summarize the uploaded report.",
     RagRoute.VECTOR_SEARCH),  # no-signal default: cheapest safe retrieval
])
def test_rag_router_classification(query, expected):
    decision = classify_query(query)
    assert decision.route is expected, f"{query!r} → {decision.route} (signals: {decision.signals})"
    assert 0.0 <= decision.confidence <= 1.0
    assert isinstance(decision.signals, list)


def test_rag_router_empty_query_defaults_to_vector():
    decision = classify_query("")
    assert decision.route is RagRoute.VECTOR_SEARCH
    assert decision.confidence == 0.0


def test_rakeza_factory_routes_by_domain_vocabulary():
    pvt = make_delegation("t1", "Report the bubble point Pb and Bo at 3000 psia for this fluid.")
    assert pvt.agent is WorkerAgent.AVIEL and pvt.domain == "PVT"

    scal = make_delegation("t2", "Fit Brooks-Corey relative permeability curves for well T1-31.")
    assert scal.agent is WorkerAgent.HVIEL and scal.domain == "SCAL"

    # Factory output must always satisfy the routing validator by construction.
    for req in (pvt, scal):
        assert req.domain == AGENT_DOMAIN[req.agent]


def test_rakeza_rejects_misrouted_delegation():
    with pytest.raises(ValidationError, match="routing violation"):
        DelegationRequest(task_id="t3", agent=WorkerAgent.HVIEL, domain="PVT",
                          query="bubble point please")


def test_rakeza_worker_response_cannot_launder_failure():
    # Empty success is unrepresentable.
    with pytest.raises(ValidationError, match="empty success"):
        WorkerResponse(task_id="t4", agent=WorkerAgent.HVIEL, ok=True, answer="   ")
    # Failure without detail is unrepresentable.
    with pytest.raises(ValidationError, match="explicit error"):
        WorkerResponse(task_id="t5", agent=WorkerAgent.AVIEL, ok=False)
    # Well-formed envelopes pass.
    ok = WorkerResponse(task_id="t6", agent=WorkerAgent.HVIEL, ok=True, answer="Swi = 0.42")
    failed = WorkerResponse(task_id="t7", agent=WorkerAgent.AVIEL, ok=False,
                            error="NIM timeout after 300s")
    assert ok.ok and failed.error


def test_rakeza_synthesis_is_reason_first():
    # Schema: reasoning is literally the first field of the synthesis contract.
    assert list(SupervisorSynthesis.model_fields)[0] == "reasoning"

    responses = [
        WorkerResponse(task_id="t8", agent=WorkerAgent.HVIEL, ok=True,
                       answer="Ed = 0.621 from Swi=0.42, Sor=0.22."),
        WorkerResponse(task_id="t8", agent=WorkerAgent.AVIEL, ok=False,
                       error="cloud agent unavailable"),
    ]
    prompt = build_synthesis_prompt("Give me Ed and the PVT bubble point.", responses)
    assert prompt.index('"reasoning"') < prompt.index('"answer"'), "reasoning must precede answer"
    assert "Reason FIRST" in prompt
    assert "HVIEL — OK" in prompt
    assert "AVIEL — FAILED: cloud agent unavailable" in prompt
    assert "do not invent its data" in prompt


def test_hviel_session_kb_ingestion_path_is_live():
    """Regression guard for the dead-RAG-path fix: chunk_text produces the
    (source, chunk) tuples ingest_transactional expects, and chat() actually
    populates _tls.pending_kb (the consumers at app.py:8182/:8799 capture it
    from chat()'s thread — with no producer the whole path was dead code)."""
    from app import KnowledgeBase

    chunks = KnowledgeBase.chunk_text("porosity 0.21 permeability 118 mD " * 200, "T1-31.xls")
    assert chunks, "chunk_text returned nothing"
    for source, chunk in chunks:
        assert source == "T1-31.xls"
        assert isinstance(chunk, str) and chunk

    app_src = (REPO_ROOT / "app.py").read_text(encoding="utf-8")
    producers = app_src.count("_tls.pending_kb.extend(KnowledgeBase.chunk_text")
    assert producers >= 3, (
        "session-KB producer missing: chat() must feed _tls.pending_kb for "
        "spreadsheet/DOCX, PDF and TXT uploads (the consumers are otherwise dead code)"
    )


def test_merge_context_chunks_deduplicates_by_snippet():
    from hviel.rag.router import merge_context_chunks

    vector_ctx = "Threshold pressure for Sample 1 is 217.5 psi.\n\nArchie m = 2.1 for the carbonate."
    graph_chunks = [
        "  threshold   pressure for sample 1 is 217.5 psi. ",   # dup (whitespace/case differ)
        '{"well": "T1-31", "basin": "Sirte"}',                   # new
    ]
    merged = merge_context_chunks(vector_ctx, graph_chunks)
    assert merged.count("217.5 psi") == 1, "duplicate snippet survived the merge"
    assert '"basin": "Sirte"' in merged
    assert "Archie m = 2.1" in merged
    # Vector context leads; graph chunks append.
    assert merged.index("Archie m") < merged.index("Sirte")


def test_chat_pipeline_wires_rag_router():
    """Tripwire: PRCChatAssistant.chat() must consult the Dual-RAG router.
    If the wiring is removed, GRAPH/HYBRID queries silently regress to
    vector-only retrieval with no failing test."""
    app_src = (REPO_ROOT / "app.py").read_text(encoding="utf-8")
    assert "classify_query" in app_src
    assert "[RAG-ROUTER]" in app_src
    assert "merge_context_chunks" in app_src


def test_multiagent_golden_case_contract():
    cases = _GOLDEN["multi_agent_cases"]
    case = next(c for c in cases if c["id"] == "joint-scal-pvt-multiagent")
    assert case["multi_agent"] is True
    assert case["judge"]["delegation_min"] >= 4
    assert case["judge"]["synthesis_min"] >= 4
    agents = set()
    for i, task in enumerate(case["sub_tasks"]):
        agent = WorkerAgent(task["agent"])
        agents.add(agent)
        # Every sub-task must construct a routing-valid DelegationRequest.
        DelegationRequest(task_id=f"{case['id']}-{i}", agent=agent,
                          domain=AGENT_DOMAIN[agent], query=task["query"])
    assert agents == {WorkerAgent.HVIEL, WorkerAgent.AVIEL}, \
        "joint case must exercise BOTH workers"


@pytest.mark.parametrize("agent,domain", [
    (WorkerAgent.HVIEL, "SCAL"),
    (WorkerAgent.AVIEL, "PVT"),
])
def test_dispatcher_envelopes_connection_failure(agent, domain):
    """Graceful transparent failure: a dead worker yields ok=False with an
    explicit error envelope — never an exception, never an empty success."""
    from hviel.rakeza.dispatcher import dispatch

    req = DelegationRequest(task_id="t-dead", agent=agent, domain=domain,
                            query="ping")
    resp = dispatch(req, hviel_base_url="http://127.0.0.1:9",
                    aviel_base_url="http://127.0.0.1:9", timeout=3.0)
    assert resp.ok is False
    assert resp.error and resp.error.strip()
    assert resp.agent is agent
    assert resp.latency_s is not None


# ══════════════════════════════════════════════════════════════════════════════
# Layer 0 — Rakeza master RAG routing + Aviel PVT retrieval contracts
# ══════════════════════════════════════════════════════════════════════════════

from hviel.rag.router import RagDomain, classify_domain
from hviel.rakeza.contracts import (
    PVT_METADATA_FILTERS,
    RagOptions,
    SCAL_KEYWORDS,
    build_aviel_rag_payload,
)


@pytest.mark.parametrize("query,expected", [
    ("Report the bubble point Pb and Bo for this black oil fluid at 3000 psia.",
     RagDomain.AVIEL_LOCAL),
    ("Fit Brooks-Corey relative permeability curves for well T1-31.",
     RagDomain.HVIEL_LOCAL),
    ("Give me the cross-department master reservoir summary for the field.",
     RagDomain.RAKEZA_GLOBAL),
    ("Compare the capillary pressure trends with the bubble point behavior of the fluid.",
     RagDomain.RAKEZA_GLOBAL),  # both vocabularies → global
    ("Summarize the uploaded report.",
     RagDomain.HVIEL_LOCAL),    # no signal → primary-domain default
])
def test_rakeza_master_rag_domain_routing(query, expected):
    decision = classify_domain(query)
    assert decision.domain is expected, f"{query!r} → {decision.domain} (signals: {decision.signals})"
    assert 0.0 <= decision.confidence <= 1.0


def test_aviel_rag_payload_is_clean_and_scal_free():
    """PVT RAG payloads: only whitelisted filter keys, no null values, JSON
    round-trip clean, and zero SCAL vocabulary leaking into the wire format."""
    req = make_delegation(
        "rag-1",
        "Evaluate PVT at P=3000 psia, T=180 F for the black oil sample and report Pb, Rs and Bo.",
        session_id="sess-rag",
        rag=RagOptions(fluid_type="black_oil", well_name="T1-31",
                       pvt_report_id="PVT-2026-014", top_k=8),
    )
    assert req.agent is WorkerAgent.AVIEL
    payload = build_aviel_rag_payload(req)

    assert set(payload) <= {"query", "top_k", "filters", "session_id"}
    assert payload["top_k"] == 8
    assert set(payload["filters"]) <= set(PVT_METADATA_FILTERS)
    assert None not in payload["filters"].values()
    wire = json.dumps(payload)
    assert json.loads(wire) == payload  # round-trip clean

    padded = f" {wire.lower()} "
    leaked = [k for k in SCAL_KEYWORDS if k in padded]
    assert not leaked, f"SCAL vocabulary leaked into the PVT RAG payload: {leaked}"

    # Defaults: no filters set → no filters key at all (no null-noise on the wire).
    bare = build_aviel_rag_payload(make_delegation("rag-2", "bubble point Pb for the fluid"))
    assert "filters" not in bare
    assert set(bare) == {"query", "top_k"}


def test_aviel_rag_payload_rejects_non_aviel_delegation():
    scal_req = make_delegation("rag-3", "Fit Brooks-Corey relative permeability for T1-31.")
    assert scal_req.agent is WorkerAgent.HVIEL
    with pytest.raises(ValueError, match="only aviel delegations"):
        build_aviel_rag_payload(scal_req)


def test_rag_options_contract_is_strict():
    with pytest.raises(ValidationError):
        RagOptions(fluid_type="light_crude")          # not in the fluid taxonomy
    with pytest.raises(ValidationError):
        RagOptions(top_k=0)                           # below bounds
    with pytest.raises(ValidationError):
        RagOptions(scal_sheet="MICP_TestA")           # extra key forbidden
    opts = RagOptions(doc_type="session", shelf="fluid-studies")
    assert opts.enabled and opts.top_k == 5


# ══════════════════════════════════════════════════════════════════════════════
# Layer 1 — live E2E gate (RUN_LIVE_EVALS=1 + NVIDIA_API_KEY)
# ══════════════════════════════════════════════════════════════════════════════

# Judge runs on the same backend the app uses: SCAL_LLM_BASE_URL (local Ollama)
# when configured, NVIDIA NIM cloud otherwise. EVAL_JUDGE_MODEL overrides the
# judge model independently (recommended for release gates: different family).
_NVIDIA_URL = (os.environ.get("SCAL_LLM_BASE_URL", "").strip()
               or "https://integrate.api.nvidia.com/v1/chat/completions")
_JUDGE_MODEL = (os.environ.get("EVAL_JUDGE_MODEL", "").strip()
                or os.environ.get("SCAL_LLM_MODEL", "").strip()
                or "openai/gpt-oss-120b")

_JUDGE_SYSTEM = (
    "You are a strict evaluation judge for a petrophysics (SCAL) AI assistant. "
    "Reason FIRST, then score. Think step by step: (a) list which claims in the "
    "reply are supported by the provided ground truth / expected behavior, "
    "(b) list any fabricated or unsupported claims, (c) check whether the reply "
    "actually addresses the user's question(s). Only after that reasoning, emit "
    "your verdict as a single JSON object on the final line, with the reasoning "
    "field FIRST:\n"
    '{"reasoning": "<one-sentence summary of your analysis>", '
    '"groundedness": <int 1-5>, "relevance": <int 1-5>}\n'
    "Groundedness 5 = every claim traceable to ground truth or a correct refusal; "
    "1 = fabricated data. Relevance 5 = fully answers everything asked; "
    "1 = off-topic or ignores the question. Do NOT reward length or confident "
    "tone; a short correct answer outscores a long padded one."
)

# Appended when the turn under evaluation is a multi-agent trajectory
# (domain extraction nodes -> MasterEngineerNode synthesis -> visualizer handoff).
_JUDGE_MULTI_AGENT_ADDENDUM = (
    "\n\nThis turn is a MULTI-AGENT trajectory: domain nodes produced JSON "
    "payloads which an orchestrator (MasterEngineerNode) synthesized into the "
    "final report. Extend your step-by-step reasoning with: (d) was each "
    "sub-task handled by the appropriate node (extraction vs physics "
    "enrichment vs synthesis vs visualizer directive), with no node bypassed, "
    "duplicated, or answering outside its role? (e) does the synthesized "
    "report use ONLY facts present in the provided sub-agent outputs — no "
    "invented cross-agent claims, no rows silently dropped by truncation? "
    "Then emit the extended verdict JSON, reasoning still FIRST:\n"
    '{"reasoning": "<one sentence>", "groundedness": <int 1-5>, '
    '"relevance": <int 1-5>, "delegation_correctness": <int 1-5>, '
    '"synthesis_groundedness": <int 1-5>}\n'
    "delegation_correctness 5 = perfect routing; 1 = wrong node did the work "
    "or a required node was skipped. synthesis_groundedness 5 = every "
    "synthesized claim traces to a sub-agent output; 1 = the synthesis "
    "contradicts or invents sub-agent data."
)


def _fixture_ground_truth(fixture_rel: str) -> str:
    """Compact ground-truth digest for the judge, from the grader's extractor."""
    from file_reader import read_file
    from grader import extract_ground_truth

    truth = extract_ground_truth(read_file(str(REPO_ROOT / fixture_rel)))
    lines = [f"well={truth['well']}", f"company={truth['company']}"]
    for k, v in list(truth["all_values"].items())[:60]:
        lines.append(f"{k} = {v}")
    return "\n".join(lines)


def _llm_chat(system: str, user: str, max_tokens: int = 900) -> str:
    """One chat completion against the configured backend (Ollama or NIM)."""
    body = json.dumps({
        "model": _JUDGE_MODEL,
        "temperature": 0.0,
        "top_p": 1.0,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }).encode("utf-8")
    req = urllib.request.Request(_NVIDIA_URL, data=body, method="POST", headers={
        # Local Ollama ignores auth; the placeholder keeps the header well-formed.
        "Authorization": f"Bearer {nvidia_api_key() or 'local-ollama'}",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read())["choices"][0]["message"]["content"]


def _judge(prompt: str, reply: str, context: str, multi_agent: bool = False) -> dict:
    system = _JUDGE_SYSTEM + (_JUDGE_MULTI_AGENT_ADDENDUM if multi_agent else "")
    content = _llm_chat(system, (
        f"### EVALUATION CONTEXT / GROUND TRUTH\n{context}\n\n"
        f"### USER PROMPT\n{prompt}\n\n"
        f"### ASSISTANT REPLY UNDER EVALUATION\n{reply}"
    ))
    match = re.search(r'\{[^{}]*"groundedness"[^{}]*\}', content, re.DOTALL)
    assert match, f"judge returned no parseable verdict JSON: {content[:500]}"
    verdict = json.loads(match.group(0))
    required = {"groundedness", "relevance"}
    if multi_agent:
        required |= {"delegation_correctness", "synthesis_groundedness"}
    assert required <= set(verdict), verdict
    return verdict


def _send_chat(client, message: str, fixture_rel=None):
    data = {"message": message, "user_email": "test@prc.local"}
    files = []
    if fixture_rel:
        path = REPO_ROOT / fixture_rel
        # Field name MUST be "files" (endpoint: files: list[UploadFile]); a
        # mismatched name is silently dropped and the eval runs on an empty session.
        files.append(("files", (path.name, path.read_bytes(), "application/vnd.ms-excel")))
    resp = client.post("/api/chat", data=data, files=files or None)
    resp.raise_for_status()
    return resp.json()["reply"]


@pytest.mark.integration
@live_only
@pytest.mark.parametrize("case_id", list(_CASES))
def test_live_e2e_case(client, case_id):
    case = _CASES[case_id]
    max_latency = case.get("max_latency_s", _DEFAULTS["max_latency_s"])

    t0 = time.monotonic()
    reply = _send_chat(client, case["prompt"], case["fixture"])
    latency = time.monotonic() - t0

    assert latency <= max_latency, f"turn latency {latency:.1f}s exceeds {max_latency}s"
    assert reply and reply.strip(), "empty reply"

    low = reply.lower()
    for banned in _DEFAULTS["blacklist"] + case.get("blacklist_extra", []):
        assert banned.lower() not in low, f"blacklisted string {banned!r} in reply"

    for spec in case.get("expects_numeric", []):
        tol = spec["tolerance"]
        found = value_in_text(reply, spec["value"], tolerance=tol) or (
            "percent_alias" in spec and value_in_text(reply, spec["percent_alias"], tolerance=tol)
        )
        assert found, f"{spec['name']}: {spec['value']} (±{tol:.0%}) not found in reply"

    if case.get("expects_markdown_table"):
        assert re.search(r"\|.+\|", reply), "expected a markdown table in the reply"

    threshold = case.get("autograder_min_score")
    if threshold is not None and case["fixture"]:
        result = grade_ai_response(str(REPO_ROOT / case["fixture"]), reply)
        assert result["score"] >= threshold, f"AutoGrader {result['score']} < {threshold}\n{result['report']}"

    if case["fixture"]:
        context = _fixture_ground_truth(case["fixture"])
    else:
        context = case["judge_note"]
    multi_agent = bool(case.get("multi_agent"))
    verdict = _judge(case["prompt"], reply, f"{context}\n\nJudge note: {case['judge_note']}",
                     multi_agent=multi_agent)
    judge_cfg = {**_DEFAULTS["judge"], **case.get("judge", {})}
    assert verdict["groundedness"] >= judge_cfg["groundedness_min"], verdict
    assert verdict["relevance"] >= judge_cfg["relevance_min"], verdict
    if multi_agent:
        assert verdict["delegation_correctness"] >= judge_cfg["delegation_min"], verdict
        assert verdict["synthesis_groundedness"] >= judge_cfg["synthesis_min"], verdict


# ── Rakeza live multi-agent gate — needs BOTH workers running ────────────────

_HVIEL_URL = os.environ.get("HVIEL_BASE_URL", "").rstrip("/")

rakeza_live_only = pytest.mark.skipif(
    not (LIVE_ENABLED and _HVIEL_URL and os.environ.get("AVIEL_BASE_URL", "").strip()),
    reason=("Rakeza multi-agent live gate requires RUN_LIVE_EVALS=1 plus "
            "HVIEL_BASE_URL and AVIEL_BASE_URL (both worker servers running)"),
)


@pytest.mark.integration
@rakeza_live_only
def test_live_multiagent_joint_case():
    """Full Rakeza trajectory: delegate both sub-tasks to live workers,
    synthesize with the reason-first CoT prompt, then judge delegation
    correctness and cross-agent synthesis groundedness."""
    from hviel.rakeza.contracts import SupervisorSynthesis, build_synthesis_prompt
    from hviel.rakeza.dispatcher import dispatch_all

    case = next(c for c in _GOLDEN["multi_agent_cases"]
                if c["id"] == "joint-scal-pvt-multiagent")
    requests = [
        DelegationRequest(task_id=f"{case['id']}-{i}",
                          agent=WorkerAgent(t["agent"]),
                          domain=AGENT_DOMAIN[WorkerAgent(t["agent"])],
                          query=t["query"])
        for i, t in enumerate(case["sub_tasks"])
    ]
    responses = dispatch_all(requests)
    failed = [r for r in responses if not r.ok]
    assert not failed, f"worker failures: {[(r.agent.value, r.error) for r in failed]}"

    # Supervisor synthesis on the configured LLM backend.
    synth_raw = _llm_chat(
        "You are Rakeza. Follow the instructions in the user message exactly.",
        build_synthesis_prompt(case["prompt"], responses),
        max_tokens=1400,
    )
    match = re.search(r'\{.*"reasoning".*\}', synth_raw, re.DOTALL)
    assert match, f"no synthesis JSON in supervisor output: {synth_raw[:400]}"
    synthesis = SupervisorSynthesis.model_validate(json.loads(match.group(0)))

    worker_context = "\n\n".join(
        f"[{r.agent.value.upper()} OUTPUT]\n{r.answer}" for r in responses
    )
    verdict = _judge(case["prompt"], synthesis.answer,
                     f"{worker_context}\n\nJudge note: {case['judge_note']}",
                     multi_agent=True)
    judge_cfg = {**_DEFAULTS["judge"], **case.get("judge", {})}
    assert verdict["delegation_correctness"] >= judge_cfg["delegation_min"], verdict
    assert verdict["synthesis_groundedness"] >= judge_cfg["synthesis_min"], verdict
    assert verdict["groundedness"] >= judge_cfg["groundedness_min"], verdict


# ── Aviel (pvt-ai-pipeline) live gate — needs a running Aviel at AVIEL_BASE_URL ──

_AVIEL_URL = os.environ.get("AVIEL_BASE_URL", "").rstrip("/")

aviel_live_only = pytest.mark.skipif(
    not (LIVE_ENABLED and _AVIEL_URL),
    reason="Aviel live gate requires RUN_LIVE_EVALS=1, NVIDIA_API_KEY and AVIEL_BASE_URL",
)


def _aviel_get(path: str) -> dict:
    with urllib.request.urlopen(f"{_AVIEL_URL}{path}", timeout=60) as resp:
        return json.loads(resp.read())


def _aviel_chat(message: str) -> str:
    body = json.dumps({"message": message, "session_id": "eval-baswe", "stream": False}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    # Aviel /api/chat requires its Bearer token (KB_INGEST_PASSWORD) since the
    # CWE-306 remediation; export AVIEL_API_TOKEN for live runs.
    _tok = os.environ.get("AVIEL_API_TOKEN", "")
    if _tok:
        headers["Authorization"] = f"Bearer {_tok}"
    req = urllib.request.Request(f"{_AVIEL_URL}/api/chat", data=body, method="POST",
                                 headers=headers)
    # Single request per case keeps us far under the 10/minute endpoint limit.
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read())["text"]


@pytest.mark.integration
@aviel_live_only
def test_aviel_no_silent_cloud_fallback():
    """If /health declares cloud_agent=true, the reply must come from the cloud
    agent — a local-responder template reply means NVIDIA NIM failed and the
    fallback was served silently."""
    health = _aviel_get("/health")
    assert "cloud_agent" in health, f"/health missing cloud_agent field: {health}"
    if not health["cloud_agent"]:
        pytest.skip("Aviel is air-gapped (cloud_agent=false): local responder is the declared mode")

    case = next(c for c in _GOLDEN["aviel"]["cases"]
                if c["id"] == "aviel-cloud-fallback-truthfulness")
    reply = _aviel_chat(case["prompt"])
    assert reply and reply.strip(), "empty Aviel reply"
    for marker in _GOLDEN["aviel"]["fallback_markers"]:
        assert marker not in reply, (
            f"silent cloud→local fallback detected: /health claims cloud_agent=true "
            f"but the reply matches the local template (marker {marker!r})"
        )
