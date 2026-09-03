"""D3.1 visibility — batch scal-app-4 (app.py last quarter: the session
delete / Q0 parser, the SSE stream worker, POST /api/chat and its bootstrap
and checkpoint loop, the KB/skills admin routes, the session-cache helpers,
/api/clear-session, the background document task, the task/download routes
and /api/scal/calibrate).

Every test forces the failure (a monkeypatched dependency raises / returns
the bad shape, a scripted mock model turn) and asserts what the CALLER sees:
the return value, a raised exception, an HTTP status, a marker in the payload
or an entry on the request degradation channel. A log line alone never passes.
"""
import asyncio
import csv
import hashlib
import json
import pathlib
import shutil
import tempfile
import threading
import time
import types

import pytest
from fastapi.testclient import TestClient

import app
import llm_adapter as la
from scenario_support import EMAIL, clear_session, seed_session

SID = "d3-vis-app4"
_DB = app.db                     # unpatched, for cleanup while a db monkeypatch is live
MULTI_Q = ("Q1: report the Archie saturation exponent for sample D2-1\n"
           "Q2: report the Amott water index for sample D2-1\n"
           "Q3: report the USBM wettability index for sample D2-1")


def _wipe(sid):
    clear_session(sid)
    for q in ("DELETE FROM m WHERE sid=?", "DELETE FROM sessions WHERE sid=?",
              "DELETE FROM kb WHERE sid=?", "DELETE FROM session_cache WHERE sid=?",
              "DELETE FROM physics_audits WHERE session_id=?"):
        try:
            app.db(q, (sid,))
        except Exception:
            pass
    app.TASKS_DB.pop(sid, None)


@pytest.fixture(autouse=True)
def _fresh_request_state(monkeypatch):
    app._tls.degradations = []
    app._tls.request_failed = None
    app._tls.current_session_id = SID
    app.reset_tool_call_ledger(SID)
    monkeypatch.setattr(time, "sleep", lambda s: None)          # retry back-off
    monkeypatch.setattr(app.CHAT, "sleeper", lambda s: None)
    _wipe(SID)
    yield
    app.CHAT.load_script(None)
    app._tls.degradations = []
    app._tls.request_failed = None
    _wipe(SID)


def _degraded(kind, lst=None):
    return any(d.startswith(kind + ":") for d in (app.degradations() if lst is None else lst))


def _db_raises(monkeypatch, *prefixes):
    orig = app.db

    def fake(query, params=()):
        if any(query.lstrip().startswith(p) for p in prefixes):
            raise RuntimeError("db down (simulated)")
        return orig(query, params)
    monkeypatch.setattr(app, "db", fake)


def _script(steps, name="d3-app4"):
    s = la.MockScript.from_dict({"name": name, "on_exhausted": "error", "steps": steps})
    app.CHAT.load_script(s)
    return s


def _answer_script(text="Plain scripted answer with no numbers.", n=8):
    return _script([{"assistant": text}] * n)


def _failing_script(n=12):
    return _script([{"error": "HTTP 503 upstream (simulated)"}] * n)


def _model_rows(sid=SID):
    return [r[0] or "" for r in app.db("SELECT text FROM m WHERE sid=? AND role='model' ORDER BY id", (sid,))]


def _sse_events(text):
    out = []
    for line in text.splitlines():
        if line.startswith("data: "):
            out.append(json.loads(line[6:]))
    return out


def _stream(message, timeout=25):
    """GET /api/chat/stream from a thread so a never-terminating stream fails
    the test instead of hanging it."""
    box = {}

    def run():
        try:
            box["r"] = TestClient(app.app).get("/api/chat/stream", params={
                "message": message, "session_id": SID, "user_email": EMAIL}).text
        except Exception as e:      # pragma: no cover - surfaced below
            box["err"] = e
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout)
    assert not t.is_alive(), "SSE stream never terminated (done sentinel lost)"
    if "err" in box:
        raise box["err"]
    return _sse_events(box["r"])


def _post_chat(message, files=None):
    return TestClient(app.app).post("/api/chat", data={"message": message, "session_id": SID,
                                                       "user_email": EMAIL}, files=files)


class _FullQueue(asyncio.Queue):
    """A queue whose backlog always reads as near-full: every non-terminal item is dropped."""
    def qsize(self):
        return 1950


def _full_queue(monkeypatch):
    ns = types.SimpleNamespace(**{k: v for k, v in vars(asyncio).items() if not k.startswith("__")})
    ns.Queue = _FullQueue
    monkeypatch.setattr(app, "asyncio", ns)


# ── delete_session / parse_q0_questions ──────────────────────────────────────

def test_delete_session_reports_user_files_cleanup_failure(monkeypatch):
    app.db("INSERT INTO sessions (sid, title, user_email, created_at, updated_at) VALUES (?,?,?,?,?)",
           (SID, "t", EMAIL, time.time(), time.time()))
    app.db("INSERT INTO m (sid,role,text,ts,user_email,fname) VALUES (?,?,?,?,?,?)",
           (SID, "user", "hi", time.time(), EMAIL, "well.xlsx"))
    _db_raises(monkeypatch, "DELETE FROM user_files")
    r = TestClient(app.app).delete(f"/api/session/{SID}", params={"email": EMAIL})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "partial"
    assert _degraded("user-files", body["degradations"])


def test_parse_q0_csv_error_is_narrow_and_counted(monkeypatch):
    real = csv.reader

    def reader(rows, *a, **k):
        if any("Q2" in r for r in rows):
            raise csv.Error("bad csv (simulated)")
        return real(rows, *a, **k)
    monkeypatch.setattr(csv, "reader", reader)
    qs = app.parse_q0_questions("Q1,what is porosity\nQ2,what is perm\nQ3,what is Sw")
    assert [q for q, _ in qs] == ["Q1", "Q3"]
    assert _degraded("q0-parse")

    def boom(rows, *a, **k):
        raise RuntimeError("not a csv problem")
    monkeypatch.setattr(csv, "reader", boom)
    with pytest.raises(RuntimeError):
        app.parse_q0_questions("Q1,what is porosity")


# ── SSE stream worker ────────────────────────────────────────────────────────

def test_stream_done_sentinel_survives_a_full_queue(monkeypatch):
    seed_session(SID)
    _answer_script()
    _full_queue(monkeypatch)
    events = _stream("report the amott water index for sample D2-1")
    assert events[-1]["type"] == "done"
    assert any(e["type"] == "error" and "truncat" in e["msg"].lower() for e in events)
    assert _degraded("stream", events[-1]["degradations"])
    assert _model_rows() == []          # a truncated answer is not persisted as an answer


def test_multi_q_truncated_answer_is_not_checkpointed(monkeypatch):
    seed_session(SID)
    _answer_script()
    _full_queue(monkeypatch)
    events = _stream(MULTI_Q)
    assert events[-1]["type"] == "done"
    assert not any("CHECKPOINT" in t for t in _model_rows())


def test_stream_empty_model_output_is_an_error_event(monkeypatch):
    monkeypatch.setattr(app.assistant, "chat", lambda *a, **k: iter([]))
    events = _stream("report the amott water index for sample D2-1")
    assert events[-1]["type"] == "done" and events[-1]["failed"] is True
    assert any(e["type"] == "error" for e in events)
    assert _model_rows() == []


def test_failed_sub_question_is_not_replayed_as_cached_analysis():
    seed_session(SID)               # an empty session refuses before the model is called
    _failing_script()
    r = _post_chat(MULTI_Q)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "error"
    assert body["failed_questions"] == ["Q1", "Q2", "Q3"]
    assert not any("CHECKPOINT" in t for t in _model_rows())
    # A retry regenerates instead of serving the stored failure as a cached answer.
    script = _failing_script()
    events = _stream(MULTI_Q)
    text = "".join(e.get("text", "") for e in events if e["type"] == "token")
    assert "Cached Analysis" not in text
    assert len(script.transcript) >= 3


def test_partially_failed_multi_q_is_partial_with_the_failed_list():
    seed_session(SID)
    _script([{"assistant": "Q1 answered plainly, no numbers."}] + [{"error": "HTTP 503"}] * 12)
    body = _post_chat(MULTI_Q).json()
    assert body["status"] == "partial"
    assert body["failed_questions"] == ["Q2", "Q3"]
    assert sum("CHECKPOINT Q1" in t for t in _model_rows()) == 1


# ── POST /api/chat bootstrap ─────────────────────────────────────────────────

def test_chat_user_files_record_failure_reaches_the_response(monkeypatch):
    _answer_script()
    _db_raises(monkeypatch, "INSERT INTO user_files", "INSERT OR IGNORE INTO user_files")
    r = _post_chat("what does this file say", files={"files": ("notes.txt", b"porosity notes", "text/plain")})
    assert r.status_code == 200, r.text
    assert _degraded("user-files", r.json()["degradations"])


def test_chat_spreadsheet_bootstrap_failure_reaches_the_response(monkeypatch):
    _answer_script()
    monkeypatch.setattr(app, "extract_absolute_file_truth", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("xlsx broke")))
    r = _post_chat("what does this file say",
                   files={"files": ("well.xlsx", b"PK\x03\x04" + b"\x00" * 64, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200, r.text
    assert _degraded("bootstrap-extract", r.json()["degradations"])


def test_chat_pdf_bootstrap_failure_reaches_the_response(monkeypatch):
    _answer_script()
    monkeypatch.setattr(app, "_sfh_extract_pdf", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("pdf broke")))
    r = _post_chat("what does this file say", files={"files": ("doc.pdf", b"%PDF-1.4 fake", "application/pdf")})
    assert r.status_code == 200, r.text
    assert _degraded("bootstrap-extract", r.json()["degradations"])


def test_chat_txt_bootstrap_db_failure_reaches_the_response(monkeypatch):
    _answer_script()
    orig = app.db

    def fake(query, params=()):
        if query.lstrip().startswith("INSERT INTO user_files") and len(params) == 6:
            raise RuntimeError("db down (simulated)")
        return orig(query, params)
    monkeypatch.setattr(app, "db", fake)
    r = _post_chat("what does this file say", files={"files": ("notes.txt", b"porosity notes", "text/plain")})
    assert r.status_code == 200, r.text
    assert _degraded("bootstrap-extract", r.json()["degradations"])


def test_crash_diagnostics_claim_matches_the_save(monkeypatch):
    monkeypatch.setattr(app, "sanitize_prompt", lambda m: (_ for _ in ()).throw(RuntimeError("route crash")))
    monkeypatch.setattr(pathlib.Path, "mkdir", lambda *a, **k: (_ for _ in ()).throw(PermissionError("ro fs")))
    r = TestClient(app.app, raise_server_exceptions=False).post(
        "/api/chat", data={"message": "hi", "session_id": SID, "user_email": EMAIL})
    assert r.status_code == 500
    assert "not stored" in r.json()["error"].lower()


# ── admin routes: skills, KB ingest / delete ─────────────────────────────────

def test_skill_parse_error_is_visible(monkeypatch):
    meta = app._parse_skill_md(str(pathlib.Path(tempfile.gettempdir()) / "no-such-skill-d3" / "SKILL.md"))
    assert meta["parse_error"]
    # The library ships no SKILL.md today: plant one so the route's entry is exercised.
    skill_dir = pathlib.Path(app.__file__).parent / "hermes_skills_library" / "d3-app4-tmp" / "probe"
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text("---\nname: probe\n---\n", encoding="utf-8")
    monkeypatch.setattr(app, "_parse_skill_md", lambda p: {"name": "", "description": "", "parse_error": "boom"})
    try:
        skills = TestClient(app.app).get("/api/skills/list").json()["skills"]
    finally:
        shutil.rmtree(skill_dir.parent, ignore_errors=True)
    probe = [s for s in skills if s["name"] == "Probe"]
    assert probe and probe[0]["parse_error"] == "boom"


def test_kb_ingest_word_count_estimate_is_marked(monkeypatch):
    monkeypatch.setattr(app, "ADMIN_PIN", "pin-d3-app4")
    monkeypatch.setattr(app, "_ingest_library_file", lambda *a, **k: {"chunks": 3})
    monkeypatch.setattr(app, "_extract_text_for_library", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no text")))
    r = TestClient(app.app).post("/api/kb/ingest", data={"password": "pin-d3-app4"},
                                 files={"file": ("notes.txt", b"hello world", "text/plain")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["words"] is None and body["words_estimated"] == 450


def test_kb_delete_of_unknown_document_is_404(monkeypatch):
    monkeypatch.setattr(app, "ADMIN_PIN", "pin-d3-app4")
    r = TestClient(app.app).post("/api/kb/delete", data={"password": "pin-d3-app4",
                                                         "filename": "no-such-doc-d3-app4.pdf"})
    assert r.status_code == 404, r.text


# ── session cache helpers / clear-session ────────────────────────────────────

def test_active_hash_db_failure_raises(monkeypatch):
    _db_raises(monkeypatch, "SELECT file_hash")
    with pytest.raises(RuntimeError):
        app.get_session_active_hash(SID)


def _seed_file_hash():
    fhash = hashlib.sha256(b"d3-app4 file").hexdigest()
    app.db("INSERT INTO m (sid, role, text, ts, user_email, fname, file_hash) VALUES (?,?,?,?,?,?,?)",
           (SID, "user", "upload", time.time(), EMAIL, "well.xlsx", fhash))
    with app.SESSION_DATA_CACHE_LOCK:
        app.SESSION_DATA_CACHE[fhash] = {"ground_truth": "FILE: well.xlsx", "labeled_values": {"phi": 0.2}}
    assert app.save_session_cache_to_db(SID) is True
    assert app.db("SELECT sid FROM session_cache WHERE sid=?", (fhash,))
    return fhash


def test_clear_session_evicts_the_file_hash_entry_and_db_row():
    fhash = _seed_file_hash()
    try:
        r = TestClient(app.app).post("/api/clear-session", data={"session_id": SID})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "cleared" and fhash in body["evicted"]
        assert not app.SESSION_DATA_CACHE.get(fhash, {}).get("ground_truth")
        assert app.db("SELECT sid FROM session_cache WHERE sid=?", (fhash,)) == []
    finally:
        app.SESSION_DATA_CACHE.pop(fhash, None)
        app.db("DELETE FROM session_cache WHERE sid=?", (fhash,))


def test_clear_session_db_failure_is_partial(monkeypatch):
    fhash = _seed_file_hash()
    try:
        _db_raises(monkeypatch, "DELETE FROM session_cache")
        body = TestClient(app.app).post("/api/clear-session", data={"session_id": SID}).json()
        assert body["status"] == "partial"
        assert _degraded("session-cache", body["degradations"])
    finally:
        app.SESSION_DATA_CACHE.pop(fhash, None)
        _DB("DELETE FROM session_cache WHERE sid=?", (fhash,))


def test_save_session_cache_returns_false_and_degrades_on_db_failure(monkeypatch):
    with app.SESSION_DATA_CACHE_LOCK:
        app.SESSION_DATA_CACHE[SID] = {"ground_truth": "x", "labeled_values": {}}
    _db_raises(monkeypatch, "INSERT INTO session_cache")
    assert app.save_session_cache_to_db(SID) is False
    assert _degraded("session-cache")


def test_load_session_cache_marks_corrupt_json():
    app.db("INSERT INTO session_cache (sid, ground_truth, labeled_values, flat_vectors, raw_excel_data, updated_at) "
           "VALUES (?,?,?,?,?,?)", (SID, "gt", "{not json", "{}", "{}", time.time()))
    assert app.load_session_cache_from_db(SID) is True
    assert "labeled_values" in app.SESSION_DATA_CACHE[SID]["degraded"]
    assert _degraded("session-cache")


def test_load_session_cache_db_failure_is_visible(monkeypatch):
    _db_raises(monkeypatch, "SELECT ground_truth")
    assert app.load_session_cache_from_db(SID) is None
    assert _degraded("session-cache")


# ── background document task ─────────────────────────────────────────────────

class _Resp:
    def __init__(self, text):
        self.text = text


def _bg(monkeypatch, llm_json, *, gt_fails=True, inv_fails=True, physics_fails=True, uf_fails=True):
    """Run sync_document_generation_task with every external stage stubbed."""
    monkeypatch.setattr(app, "CHAT", types.SimpleNamespace(
        config=types.SimpleNamespace(api_keys=("k",), provider="mock"), load_script=lambda s: None, sleeper=lambda s: None))
    monkeypatch.setattr(app, "read_file", lambda *a, **k: {"well_name": "W-1"})
    monkeypatch.setattr(app, "to_prompt_string", lambda d: ("Sheet: T1\n1,2,3", None))
    if gt_fails:
        monkeypatch.setattr(app, "extract_absolute_file_truth", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("gt broke")))
    else:
        monkeypatch.setattr(app, "extract_absolute_file_truth", lambda *a, **k: "GROUND TRUTH")
    if inv_fails:
        monkeypatch.setattr(app, "SCALFileHandler", lambda p: (_ for _ in ()).throw(RuntimeError("inventory broke")))
    monkeypatch.setattr(app, "chat_generate_with_retry", lambda **k: _Resp(llm_json))
    import prc_physics
    if physics_fails:
        monkeypatch.setattr(prc_physics, "calculate_compressibility_sweep",
                            lambda d: (_ for _ in ()).throw(RuntimeError("physics broke")))
    monkeypatch.setattr(app, "MasterEngineerNode",
                        lambda **k: types.SimpleNamespace(analyze_scal_data=lambda d: "report"))
    monkeypatch.setattr(app, "generate_universal_dashboard", lambda **k: "")
    monkeypatch.setattr(app.visualizer, "generate_plots", lambda *a, **k: None)
    monkeypatch.setattr(app, "PRCReportEngine",
                        lambda **k: types.SimpleNamespace(generate=lambda *a, **kw: "report.docx"))
    if uf_fails:
        _db_raises(monkeypatch, "INSERT INTO user_files")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tf:
        tf.write(b"PK\x03\x04 fake workbook")
        path = tf.name
    app.TASKS_DB[SID] = {"status": "queued", "progress": 0, "result": None, "error": None}
    try:
        app.sync_document_generation_task(SID, path, "well.xlsx", email=EMAIL, message="extract")
    finally:
        shutil.rmtree(pathlib.Path(app.__file__).parent / "outputs" / SID, ignore_errors=True)
    return app.TASKS_DB[SID]


def test_bg_task_skipped_gates_end_as_partial_with_warnings(monkeypatch):
    rows = [{"Pressure_psi": 100, "Porosity_percent": 20.0, "Air_Permeability_md": 5.0}, "junk-row"]
    task = _bg(monkeypatch, json.dumps({"extracted_data": rows}))
    assert task["status"] == "partial", task
    w = "\n".join(task["warnings"])
    for kind in ("ground-truth", "inventory", "physics", "user-files", "extraction"):
        assert kind in w, (kind, w)
    assert task["result"]


def test_bg_task_clean_run_stays_success(monkeypatch):
    rows = [{"Pressure_psi": 100, "Porosity_percent": 20.0, "Air_Permeability_md": 5.0}]
    task = _bg(monkeypatch, json.dumps({"extracted_data": rows}),
               gt_fails=False, inv_fails=False, physics_fails=False, uf_fails=False)
    assert task["status"] in ("success", "partial"), task
    # the only tolerated degradations on a clean run are the real parsers choking on the fake workbook
    assert all(w.startswith(("inventory:", "physics:", "cache-vectors:")) for w in task.get("warnings", [])), task


def test_bg_task_dict_without_extracted_data_is_an_error(monkeypatch):
    task = _bg(monkeypatch, json.dumps({"phase_0b_proof_of_read": {"sheets": ["T1"]}}))
    assert task["status"] == "error" and "extracted_data" in task["error"]


def test_bg_task_zero_rows_is_not_a_100_percent_pass(monkeypatch):
    task = _bg(monkeypatch, json.dumps({"extracted_data": []}))
    assert task["status"] == "error", task
    assert "zero" in task["error"].lower() or "no data rows" in task["error"].lower()
    assert app.db("SELECT health_score FROM physics_audits WHERE session_id=?", (SID,)) == []


# ── task status / download / calibrate ───────────────────────────────────────

def test_task_status_unexpected_error_is_500_not_400(monkeypatch):
    monkeypatch.setattr(app, "verify_user_or_admin", lambda **k: (_ for _ in ()).throw(RuntimeError("auth helper crash")))
    r = TestClient(app.app, raise_server_exceptions=False).get(f"/api/v1/tasks/{SID}")
    assert r.status_code == 500, r.text


def test_download_report_unexpected_error_is_500_not_400(monkeypatch):
    monkeypatch.setattr(app, "verify_user_or_admin", lambda **k: (_ for _ in ()).throw(RuntimeError("auth helper crash")))
    r = TestClient(app.app, raise_server_exceptions=False).get("/api/report/download/x.docx")
    assert r.status_code == 500, r.text


def test_archie_calibration_with_too_few_points_is_400():
    r = TestClient(app.app).post("/api/scal/calibrate",
                                 json={"porosity": [0.2, -0.1], "formation_factor": [25.0, 10.0]})
    assert r.status_code == 400, r.text
    assert "2" in r.json()["error"]


def test_kr_calibration_marks_an_unfitted_default():
    payload = {"sw": [0.05, 0.1, 0.2], "krw": [0.0, 0.01, 0.02], "kro": [0.8, 0.7, 0.6],
               "swi": 0.3, "sor": 0.2, "krw_max": 0.5, "kro_max": 0.8}
    r = TestClient(app.app).post("/api/scal/calibrate", json=payload)
    assert r.status_code == 200, r.text
    fp = r.json()["metadata"]["fit_params"]
    assert fp["fitted"] is False and fp["nw"] == 2.0
    assert "r2_krw" in fp and "r2_kro" in fp


# ── repair round: signals that chat() used to clear before the caller read them ──

Q0_SHEET = ("Sheet: Q0\nQ1,what is porosity\nQ2,what is permeability\n"
            "Q3,what is water saturation\nQ4,what is wettability\n")


def _seed_q0_sheet(monkeypatch):
    """A 'solve all' session: an upload row pointing at a user_files record whose
    extracted text carries a 4-question Q0 sheet; csv.reader chokes on the Q2 line."""
    seed_session(SID)
    fhash = "d3app4q0hash"
    app.db("INSERT INTO m (sid,role,text,ts,user_email,fname,file_hash) VALUES (?,?,?,?,?,?,?)",
           (SID, "user", "uploaded", time.time(), EMAIL, "q0.xlsx", fhash))
    app.db("DELETE FROM user_files WHERE user_email=? AND file_hash=?", (EMAIL, fhash))
    app.db("INSERT INTO user_files (user_email, filename, file_hash, extracted_text, created_at) VALUES (?,?,?,?,?)",
           (EMAIL, "q0.xlsx", fhash, Q0_SHEET, time.time()))
    real = csv.reader

    def reader(rows, *a, **k):
        if any("Q2" in r for r in rows):
            raise csv.Error("bad csv (simulated)")
        return real(rows, *a, **k)
    monkeypatch.setattr(csv, "reader", reader)
    return _answer_script(n=6)


def test_q0_dropped_line_reaches_the_chat_response(monkeypatch):
    script = _seed_q0_sheet(monkeypatch)
    body = _post_chat("solve all").json()
    assert len(script.transcript) == 3, "Q2 dropped: only 3 sub-questions answered"
    assert _degraded("q0-parse", body["degradations"]), body


def test_q0_dropped_line_reaches_the_stream_done_event(monkeypatch):
    _seed_q0_sheet(monkeypatch)
    events = _stream("solve all")
    assert events[-1]["type"] == "done"
    assert _degraded("q0-parse", events[-1]["degradations"]), events[-1]


def test_multi_q_degradations_survive_every_sub_question():
    seed_session(SID)
    _script([{"assistant": "Q1 answered plainly, no numbers."}] + [{"error": "HTTP 503"}] * 12)
    body = _post_chat(MULTI_Q).json()
    assert body["status"] == "partial"
    d = "\n".join(body["degradations"])
    assert "sub-question: Q2" in d and "sub-question: Q3" in d, d


def test_kr_calibration_does_not_claim_curve_fit_after_the_fallback(monkeypatch):
    import petrophysical_curves as pc
    monkeypatch.setattr(pc, "curve_fit", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no convergence")))
    payload = {"sw": [0.3, 0.4, 0.5, 0.6, 0.7, 0.8], "krw": [0.0, 0.02, 0.08, 0.18, 0.32, 0.5],
               "kro": [0.8, 0.5, 0.3, 0.15, 0.05, 0.0], "swi": 0.3, "sor": 0.2, "krw_max": 0.5, "kro_max": 0.8}
    r = TestClient(app.app).post("/api/scal/calibrate", json=payload)
    assert r.status_code == 200, r.text
    fp = r.json()["metadata"]["fit_params"]
    assert fp["fitted"] is True
    assert fp["source"] != "curve_fit" and "log-linear" in fp["source"], fp


def test_bg_task_session_cache_save_failure_reaches_the_warnings(monkeypatch):
    _db_raises(monkeypatch, "INSERT INTO session_cache")
    monkeypatch.setattr(app, "cache_excel_data_vectors", lambda *a, **k: None)
    rows = [{"Pressure_psi": 100, "Porosity_percent": 20.0, "Air_Permeability_md": 5.0}]
    task = _bg(monkeypatch, json.dumps({"extracted_data": rows}),
               gt_fails=False, inv_fails=False, physics_fails=False, uf_fails=False)
    assert task["status"] == "partial", task
    assert any(w.startswith("session-cache:") for w in task["warnings"]), task["warnings"]
