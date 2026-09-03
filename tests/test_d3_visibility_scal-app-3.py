"""D3.1 visibility — batch scal-app-3 (app.py third quarter: the model
summary `_tool_result_summary`, `chat()` and its `_generate` loops,
`generate_document_json`, the KnowledgeBase, `init_db`/lifespan, and the
session-owner / health / telemetry / admin-summary routes).

Every test forces the failure (a monkeypatched dependency raises / returns
the bad shape, a scripted mock model turn) and asserts what the CALLER sees:
the return value, a raised exception, an HTTP status, a marker in the payload
the model or the route receives, or an entry on the request degradation
channel (`app.degradations()` — the list that reaches the route JSON, the SSE
`done` event and the answer trailer). A log line alone never passes.
"""
import contextlib
import threading

import pytest
from fastapi.testclient import TestClient

import app
import llm_adapter as la
from llm_json_utils import LLMJsonParseError
from scenario_support import EMAIL, clear_session, seed_session

SID = "d3-vis-app3"
REAL_USER = "engineer@prc.ly"       # not the test identity: the response cache is live


@pytest.fixture(autouse=True)
def _fresh_request_state():
    app._tls.degradations = []
    app._tls.request_failed = None
    app._tls.current_session_id = SID
    app.reset_tool_call_ledger(SID)
    yield
    app.CHAT.load_script(None)
    app._tls.degradations = []
    app._tls.request_failed = None
    clear_session(SID)
    for q in ("DELETE FROM m WHERE sid=?", "DELETE FROM sessions WHERE sid=?",
              "DELETE FROM kb WHERE sid=?", "DELETE FROM session_cache WHERE sid=?"):
        try:
            app.db(q, (SID,))
        except Exception:
            pass


def _degraded(kind: str) -> bool:
    return any(d.startswith(kind + ":") for d in app.degradations())


def _db_raises(monkeypatch, prefix: str):
    orig = app.db

    def fake(query, params=()):
        if query.lstrip().startswith(prefix):
            raise RuntimeError("db down (simulated)")
        return orig(query, params)
    monkeypatch.setattr(app, "db", fake)


def _script(steps, name="d3-app3"):
    s = la.MockScript.from_dict({"name": name, "on_exhausted": "error", "steps": steps})
    app.CHAT.load_script(s)
    return s


def _sent(script) -> str:
    """Everything the model was sent, across every call."""
    return "\n".join(str(m.get("content", "")) for step in script.transcript for m in step["messages"])


def _chat(msg, *, stream=False, f_parts=(), kb_context="", history=(), email=EMAIL):
    return app.assistant.chat(list(history), msg, kb_context=kb_context, f_parts=list(f_parts),
                              stream=stream, sid=SID, email=email)


def _tokens(gen) -> str:
    return "".join(c.get("text", "") for c in gen if isinstance(c, dict) and c.get("type") == "token")


@contextlib.contextmanager
def _broken_conn():
    class Cur:
        def execute(self, *a, **k):
            raise RuntimeError("connection lost (simulated)")

        def fetchall(self):
            return []

    class Conn:
        def cursor(self):
            return Cur()

        def rollback(self):
            pass

        def commit(self):
            pass
    yield Conn(), "?"


# ── _tool_result_summary ─────────────────────────────────────────────────────

def test_empty_audit_ledger_is_not_a_trend_to_analyse():
    s = app.assistant._tool_result_summary("get_audit_history",
                                           "No audit records found for this session. The Auditor's Ledger is currently empty.", True)
    assert s["status"] == "empty" and "trend" not in s["note"].lower().split("no trend")[0]
    assert "no trend" in s["note"].lower()


def test_fit_summary_says_computed_only_for_a_rendered_plot():
    raw = '{"status": "ready", "model": "ri"}'
    plotted = app.assistant._tool_result_summary("fit_petrophysical_curve", raw, True,
                                                 rendered="__PRC_PLOT__\n{}\n")
    assert plotted["status"] == "success" and "Archie n" in plotted["note"]
    blank = app.assistant._tool_result_summary("fit_petrophysical_curve", raw, True, rendered="")
    assert blank["status"] != "success" and "computed" not in blank.get("note", "")


def test_loop_hands_the_summary_what_was_actually_rendered(monkeypatch):
    """A fit whose formatter produced nothing must not be summarised as 'plot computed'."""
    monkeypatch.setattr(app.assistant, "_format_tool_response", lambda name, args, result: "")
    seed_session(SID, n=1.85)
    s = _script([{"assistant": {"text": "", "tool_calls": [{"name": "fit_petrophysical_curve",
                                                             "args": {"model": "ri"}}]}},
                 {"assistant": "done"}])
    _chat("fit the RI curve")
    tool_msgs = [m for m in s.transcript[1]["messages"] if m.get("role") == "tool"]
    assert tool_msgs and "computed" not in str(tool_msgs[-1].get("content"))


# ── chat(): context assembly ─────────────────────────────────────────────────

def test_rag_router_import_failure_reaches_the_caller(monkeypatch):
    import hviel.rag.router as router

    def boom(*a, **k):
        raise ImportError("No module named 'src.rakeza' (simulated)")
    monkeypatch.setattr(router, "classify_query", boom)
    _script([{"assistant": "ok"}])
    reply = _chat("What does the Amott index measure?")
    assert _degraded("rag-router") and "[degraded: rag-router: ImportError" in reply


def test_vector_store_outage_on_a_graph_route_is_visible(monkeypatch):
    import rag_database

    class Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("chroma store unreadable (simulated)")
    monkeypatch.setattr(rag_database, "RAGDatabase", Boom)
    _script([{"assistant": "ok"}])
    reply = _chat("Which analog wells are related to this formation?")
    assert _degraded("rag-vector-store"), app.degradations()
    assert "[degraded: rag-vector-store" in reply


def test_session_file_registry_failure_is_visible(monkeypatch):
    _db_raises(monkeypatch, "SELECT fname, MAX(ts)")
    s = _script([{"assistant": "ok"}])
    _chat("What does the Amott index measure?", kb_context="past session memory")
    assert _degraded("session-file-registry"), app.degradations()
    assert "SESSION FILE REGISTRY unavailable" in _sent(s)


def test_pdf_extraction_failure_is_stated_to_the_model_and_the_caller(monkeypatch):
    def boom(_b):
        raise RuntimeError("pdf parser crashed (simulated)")
    monkeypatch.setattr(app, "_sfh_extract_pdf", boom)
    s = _script([{"assistant": "ok"}])
    reply = _chat("summarize the report", f_parts=[(b"%PDF-1.4 junk", "application/pdf", "report.pdf")])
    sent = _sent(s)
    assert "[PDF DOCUMENT: report.pdf" in sent and "extraction FAILED" in sent
    assert _degraded("pdf-extract") and "[degraded: pdf-extract" in reply


def test_txt_extraction_failure_is_stated_to_the_model_and_the_caller(monkeypatch):
    def boom(text, source):
        raise RuntimeError("chunker crashed (simulated)")
    monkeypatch.setattr(app.KnowledgeBase, "chunk_text", staticmethod(boom))
    s = _script([{"assistant": "ok"}])
    _chat("summarize the notes", f_parts=[(b"some plain text notes", "text/plain", "notes.txt")])
    sent = _sent(s)
    assert "[DOCUMENT: notes.txt" in sent and "extraction FAILED" in sent
    assert _degraded("txt-extract"), app.degradations()


def test_stored_document_recovery_failure_names_the_real_cause(monkeypatch):
    _db_raises(monkeypatch, "SELECT DISTINCT fname, file_hash")
    reply = _chat("what values are in the uploaded file?")      # data reference, no data: refusal gate
    assert "can't answer that from this session" in reply
    assert _degraded("stored-document") and "[degraded: stored-document" in reply


def test_labeled_values_are_never_labelled_fully_verified_extraction():
    seed_session(SID, labeled={"n": 1.85, "wettability.amott_water_index_iw": 0.68})
    app.record_tool_call(SID, "fit_petrophysical_curve", "success", {"model": "ri"}, ["n"], values={"n": 1.85})
    s = _script([{"assistant": "ok"}])
    _chat("what is the wettability of the sample?")
    sent = _sent(s)
    assert "FULLY-VERIFIED EXTRACTION PARAMETERS" not in sent
    assert "CACHED LABELED VALUES" not in sent
    assert "TOOL-FITTED PARAMETERS" in sent and '"n": 1.85' in sent.split("TOOL-FITTED PARAMETERS", 1)[1]
    # the ABSOLUTE TRUTH claim no longer spans the mixed dict
    assert "This data is ABSOLUTE TRUTH" not in sent


def test_user_corrections_fetch_failure_is_visible(monkeypatch):
    _db_raises(monkeypatch, "SELECT original_issue")
    s = _script([{"assistant": "ok"}])
    reply = _chat("What does the Amott index measure?")
    assert "[user corrections unavailable" in _sent(s)
    assert _degraded("user-corrections") and "[degraded: user-corrections" in reply


def test_kb_search_marker_becomes_a_request_degradation():
    _script([{"assistant": "ok"}])
    reply = _chat("What does the Amott index measure?",
                  kb_context="[KB DEGRADED: search-error: RuntimeError: boom]")
    assert _degraded("knowledge-base"), app.degradations()
    assert "[degraded: knowledge-base: search-error" in reply


# ── chat(): response cache ───────────────────────────────────────────────────

def test_cache_hit_is_gated_like_a_fresh_answer(monkeypatch):
    orig = app.db

    def fake(query, params=()):
        if query.lstrip().startswith("SELECT response FROM response_cache"):
            return [("Sor = {{val:sor}}. The Archie saturation exponent n for Sample B0-7 is 1.987 [fit_petrophysical_curve, model=ri].",)]
        return orig(query, params)
    monkeypatch.setattr(app, "db", fake)
    reply = _chat("What does the Amott index measure?", email=REAL_USER)
    assert "{{val:" not in reply and "1.987" not in reply


def _capture_cache_writes(monkeypatch):
    writes = []
    orig = app.db

    def fake(query, params=()):
        if query.lstrip().startswith("INSERT INTO response_cache"):
            writes.append(params[1])
            return []
        return orig(query, params)
    monkeypatch.setattr(app, "db", fake)
    return writes


def test_tool_bearing_and_empty_answers_are_never_cached(monkeypatch):
    writes = _capture_cache_writes(monkeypatch)
    seed_session(SID, n=1.85)
    _script([{"assistant": {"text": "", "tool_calls": [{"name": "get_audit_history", "args": {}}]}},
             {"assistant": "The ledger is empty."}])
    _chat("audit history please", email=REAL_USER)
    _script([{"assistant": ""}])
    _tokens(_chat("What does the Amott index measure?", stream=True, email=REAL_USER))
    assert writes == [], writes
    _script([{"assistant": "A plain text answer."}])
    _chat("Define the Amott index.", email=REAL_USER)
    assert writes == ["A plain text answer."]


# ── _generate(): provider outcomes ───────────────────────────────────────────

def test_empty_provider_answer_is_a_failure_not_a_blank_stream():
    _script([{"assistant": ""}])
    out = _tokens(_chat("What does the Amott index measure?", stream=True))
    assert "[!]" in out and "empty response" in out
    assert app._tls.request_failed


def test_empty_provider_answer_non_stream_names_the_provider():
    _script([{"assistant": ""}])
    reply = _chat("What does the Amott index measure?")
    assert "empty response" in reply and app._tls.request_failed


def test_overload_after_retries_is_reported_as_a_failed_request(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("503 Service Unavailable (simulated)")
    monkeypatch.setattr(app, "chat_generate_with_retry", boom)
    reply = _chat("What does the Amott index measure?")
    assert "(503)" in reply and app._tls.request_failed


def test_turn_budget_exhaustion_is_visible_in_the_stream():
    seed_session(SID, n=1.85)
    call = {"assistant": {"text": "", "tool_calls": [{"name": "get_audit_history", "args": {}}]}}
    s = _script([call, call, call, call])
    out = _tokens(_chat("audit history please", stream=True))
    assert "[turn budget exhausted" in out
    assert _degraded("turn-budget"), app.degradations()
    tool_msgs = [m for m in s.transcript[1]["messages"] if m.get("role") == "tool"]
    assert '"empty"' in str(tool_msgs[-1].get("content"))


# ── generate_document_json ───────────────────────────────────────────────────

_DOC_OK = '{"title": "t", "sections": [{"heading": "h", "paragraphs": ["p"]}]}'
_XLSX = (b"not really a workbook", "application/vnd.ms-excel", "core.xlsx")


def _docgen(**kw):
    return app.assistant.generate_document_json("docx", "generate a word report", [], "", "eng",
                                                sid=SID, email=EMAIL, **kw)


def test_docgen_file_read_failure_is_stated_in_the_document_prompt(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("xlsx unreadable (simulated)")
    monkeypatch.setattr(app, "read_file", boom)
    s = _script([{"assistant": _DOC_OK}])
    _docgen(f_parts=[_XLSX])
    assert "[FILE READ FAILED: core.xlsx" in _sent(s) and _degraded("docgen-file-read")


def test_docgen_scal_extraction_failure_is_stated_in_the_document_prompt(monkeypatch):
    monkeypatch.setattr(app, "read_file", lambda *a, **k: {"tables": {}})
    monkeypatch.setattr(app, "to_prompt_string", lambda d: ("raw table text", None))

    def boom(*a, **k):
        raise RuntimeError("handler crashed (simulated)")
    monkeypatch.setattr(app, "extract_file_data", boom)
    s = _script([{"assistant": _DOC_OK}])
    _docgen(f_parts=[_XLSX])
    assert "[SCAL SUMMARY UNAVAILABLE for core.xlsx" in _sent(s) and _degraded("docgen-scal-extraction")


def test_docgen_stored_file_recovery_failure_is_stated_not_data_not_available(monkeypatch):
    _db_raises(monkeypatch, "SELECT DISTINCT fname, file_hash")
    s = _script([{"assistant": _DOC_OK}])
    _docgen(f_parts=[])
    sent = _sent(s)
    assert "[STORED FILE DATA UNAVAILABLE" in sent and "NO FILE DATA UPLOADED" not in sent
    assert _degraded("docgen-stored-files")


def test_docgen_corrections_failure_is_visible(monkeypatch):
    _db_raises(monkeypatch, "SELECT original_issue")
    s = _script([{"assistant": _DOC_OK}])
    _docgen(f_parts=[])
    assert "[user corrections unavailable" in _sent(s) and _degraded("user-corrections")


def test_docgen_unparseable_json_after_the_corrective_retry_raises():
    _script([{"assistant": "Here is your report, no JSON at all."},
             {"assistant": "Still prose, still no JSON."}])
    with pytest.raises(LLMJsonParseError):
        _docgen(f_parts=[])


# ── KnowledgeBase ────────────────────────────────────────────────────────────

def _embedding_breaks(monkeypatch):
    monkeypatch.setattr(app, "_real_embedding_key_configured", lambda: True)

    def boom():
        raise RuntimeError("embedding endpoint down (simulated)")
    monkeypatch.setattr(app, "_get_embed_client", boom)


def test_embed_error_is_a_degradation_not_a_silent_none(monkeypatch):
    _embedding_breaks(monkeypatch)
    assert app.KnowledgeBase._embed("porosity permeability text") is None
    assert _degraded("kb-embed"), app.degradations()


def test_ingest_reports_stored_vs_embedded_counts(monkeypatch):
    _embedding_breaks(monkeypatch)
    stored, embedded = app.KnowledgeBase.ingest_transactional(
        "notes.txt", [("notes.txt", "a chunk of text long enough to be stored")], sid=SID, email=EMAIL)
    assert (stored, embedded) == (1, 0)
    assert _degraded("kb-ingest-unembedded"), app.degradations()


def test_ingest_db_failure_raises_after_rollback(monkeypatch):
    monkeypatch.setattr(app, "_real_embedding_key_configured", lambda: False)
    monkeypatch.setattr(app, "_get_conn", _broken_conn)
    with pytest.raises(RuntimeError):
        app.KnowledgeBase.ingest_transactional("notes.txt", [("notes.txt", "a chunk of text long enough")],
                                               sid=SID, email=EMAIL)


def test_search_db_failure_returns_a_marker_not_no_context(monkeypatch):
    monkeypatch.setattr(app, "_get_conn", _broken_conn)
    out = app.KnowledgeBase.search("porosity and permeability of the samples", sid=SID, email=EMAIL)
    assert out.startswith("[KB DEGRADED: search-error:")


def test_search_corpus_cap_marks_the_keyword_fallback(monkeypatch):
    orig = app._get_conn

    @contextlib.contextmanager
    def capped():
        with orig() as (conn, ph):
            class Cur:
                def __init__(self):
                    self._c = conn.cursor()
                    self._count = False

                def execute(self, q, p=()):
                    self._count = "COUNT(*) FROM kb_vectors" in q
                    return self._c.execute(q, p)

                def fetchone(self):
                    return (6000,) if self._count else self._c.fetchone()

                def __getattr__(self, n):
                    return getattr(self._c, n)

            class Conn:
                def cursor(self):
                    return Cur()

                def __getattr__(self, n):
                    return getattr(conn, n)
            yield Conn(), ph
    monkeypatch.setattr(app, "_get_conn", capped)
    out = app.KnowledgeBase.search("porosity and permeability of the samples", sid=SID, email=EMAIL)
    assert "[KB DEGRADED: keyword-fallback" in out and "6000" in out


def test_search_library_failure_is_marked(monkeypatch):
    def boom(cls):
        raise RuntimeError("library cache corrupt (simulated)")
    monkeypatch.setattr(app._LibraryEmbCache, "get", classmethod(boom))
    out = app.KnowledgeBase.search("porosity and permeability of the samples", sid=SID, email=EMAIL)
    assert "[KB DEGRADED: library-search:" in out


def test_delete_session_data_failure_raises(monkeypatch):
    monkeypatch.setattr(app, "_get_conn", _broken_conn)
    with pytest.raises(RuntimeError):
        app.KnowledgeBase.delete_session_data(SID)


# ── init_db / lifespan ───────────────────────────────────────────────────────

def test_init_db_ddl_failure_fails_closed(monkeypatch):
    _db_raises(monkeypatch, "CREATE TABLE")
    with pytest.raises(RuntimeError):
        app.init_db()


def test_init_db_seed_failure_fails_closed(monkeypatch):
    _db_raises(monkeypatch, "INSERT INTO basin_physics_rules")
    with pytest.raises(RuntimeError):
        app.init_db()


def test_init_db_backfill_failure_is_reported_by_health(monkeypatch):
    monkeypatch.setattr(app, "_BOOT_WARNINGS", [])
    _db_raises(monkeypatch, "INSERT OR IGNORE INTO sessions")
    app.init_db()
    warnings = TestClient(app.app).get("/health").json()["boot_warnings"]
    assert any("sessions backfill" in w for w in warnings), warnings


def test_startup_purge_failure_is_reported_by_health(monkeypatch):
    monkeypatch.setattr(app, "_BOOT_WARNINGS", [])
    def boom():
        raise OSError("uploads dir locked (simulated)")
    monkeypatch.setattr(app, "purge_all_historical_assets", boom)
    monkeypatch.setattr(app, "start_session_ttl_monitor", lambda: None)
    with TestClient(app.app) as c:          # runs lifespan
        warnings = c.get("/health").json()["boot_warnings"]
    assert any("purge" in w and "simulated" in w for w in warnings), warnings


def test_health_reports_a_dead_ttl_monitor(monkeypatch):
    dead = threading.Thread(target=lambda: None)
    dead.start()
    dead.join()
    monkeypatch.setattr(app, "_TTL_MONITOR", dead)
    r = TestClient(app.app).get("/health")
    assert r.status_code == 503 and r.json()["ttl_monitor"] == "dead"


def test_ttl_monitor_start_returns_the_thread_and_health_sees_it_alive(monkeypatch):
    t = app.start_session_ttl_monitor()
    assert isinstance(t, threading.Thread) and t.is_alive()
    monkeypatch.setattr(app, "_TTL_MONITOR", t)
    body = TestClient(app.app).get("/health").json()
    assert body.get("ttl_monitor") == "alive"


def test_doc_engine_init_no_longer_degrades_to_none():
    src = open(app.__file__, encoding="utf-8").read()
    assert "hviel_engine = None" not in src
    assert app.hviel_engine is not None


# ── routes ───────────────────────────────────────────────────────────────────

def test_unowned_session_is_claimed_once_then_protected():
    app.db("INSERT INTO sessions (sid, title, user_email, created_at, updated_at) VALUES (?, 'New Study', NULL, 0, 0)", (SID,))
    app._verify_session_owner(SID, "first@prc.ly")          # claims
    assert app.db("SELECT user_email FROM sessions WHERE sid=?", (SID,))[0][0] == "first@prc.ly"
    with pytest.raises(app.HTTPException) as ei:
        app._verify_session_owner(SID, "second@prc.ly")
    assert ei.value.status_code == 403
    app._verify_session_owner("d3-vis-app3-missing-row", "anyone@prc.ly")   # creating routes still pass


def test_telemetry_db_failures_are_null_with_errors_not_zero(monkeypatch):
    monkeypatch.setattr(app, "ADMIN_PIN", "pin-d3-app3")
    _db_raises(monkeypatch, "SELECT SUM(cost_usd)")
    r = TestClient(app.app).get("/api/v1/telemetry/metrics", headers={"x-admin-pin": "pin-d3-app3"})
    body = r.json()
    m = body["metrics"]
    assert m["cumulative_api_token_cost_usd"] is None
    assert any("cost" in e for e in body["errors"]), body


def test_telemetry_sqlite_health_is_a_probe_not_a_file_stat(monkeypatch):
    if app._PG_AVAILABLE:
        pytest.skip("sqlite-only signal")
    monkeypatch.setattr(app, "ADMIN_PIN", "pin-d3-app3")
    _db_raises(monkeypatch, "SELECT 1")
    r = TestClient(app.app).get("/api/v1/telemetry/metrics", headers={"x-admin-pin": "pin-d3-app3"})
    assert r.json()["metrics"]["db_pool_health"] == "error"


def test_admin_summary_breakdown_failure_is_null_with_errors(monkeypatch):
    _db_raises(monkeypatch, "SELECT model, SUM")
    body = app.get_summary(admin=True)
    assert body["model_breakdown"] is None
    assert any("model breakdown" in e for e in body["errors"]), body
