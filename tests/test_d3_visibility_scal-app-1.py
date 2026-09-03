"""D3.1 visibility — batch scal-app-1 (app.py imports/config/DB/audit/summaries,
ground-truth cache, aligned-column matchers, provenance tokens, library ingest,
api metrics, corrections).

Every test forces the failure (monkeypatched dependency raises / returns the
bad shape) and asserts what the CALLER sees: a return value, a raised
exception, a marker in the payload, or an entry on the request degradation
channel (`app.degradations()` — the list that reaches the route JSON, the SSE
`done` event and the answer trailer). A log line alone never passes.
"""
import hashlib
import json
import time

import numpy as np
import pytest

import app

SID = "d3-vis-app1"


@pytest.fixture(autouse=True)
def _fresh_request_state():
    app._tls.degradations = []
    app._tls.current_session_id = SID
    yield
    app._tls.degradations = []
    with app.SESSION_DATA_CACHE_LOCK:
        app.SESSION_DATA_CACHE.pop(SID, None)
    try:
        app.db("DELETE FROM session_cache WHERE sid=?", (SID,))
    except Exception:
        pass


def _db_raises(monkeypatch, only_prefix: str | None = None):
    orig = app.db

    def fake(query, params=()):
        if only_prefix is None or query.lstrip().startswith(only_prefix):
            raise RuntimeError("db down (simulated)")
        return orig(query, params)
    monkeypatch.setattr(app, "db", fake)


def _seed(labeled=None, raw_excel=None, ground_truth="seeded by test_d3_visibility_scal-app-1"):
    with app.SESSION_DATA_CACHE_LOCK:
        app.SESSION_DATA_CACHE[SID] = {
            "ground_truth": ground_truth,
            "labeled_values": dict(labeled or {}),
            "flat_vectors": {},
            "raw_excel_data": dict(raw_excel or {}),
        }


def _degraded(kind: str) -> bool:
    return any(d.startswith(kind + ":") for d in app.degradations())


# ── pydantic monkeypatches (Genkit-era shims) ────────────────────────────────

def test_genkit_pydantic_shims_are_gone():
    from pydantic import TypeAdapter
    assert TypeAdapter.json_schema.__name__ == "json_schema"
    assert not hasattr(app, "ensure_properties")


# ── _log_physics_audit ───────────────────────────────────────────────────────

def test_physics_audit_insert_failure_is_visible_to_the_request(monkeypatch):
    _db_raises(monkeypatch, "INSERT INTO physics_audits")
    assert app._log_physics_audit(SID, "ri", {"score": 80, "violations": []}) is False
    assert _degraded("physics-audit-not-logged"), app.degradations()


def test_physics_audit_success_returns_true_and_missing_score_raises():
    assert app._log_physics_audit(SID, "ri", {"score": 91, "violations": []}) is True
    app.db("DELETE FROM physics_audits WHERE session_id=?", (SID,))
    with pytest.raises(ValueError):
        app._log_physics_audit(SID, "ri", {"violations": []})


# ── background summary back-fill ─────────────────────────────────────────────

def test_summary_backfill_failure_is_logged_as_a_warning(monkeypatch, caplog):
    monkeypatch.setattr(app, "_extract_petrophysical_summary",
                        lambda text, fname: {"well_name": "W-1", "data_type": "RI", "n_saturation": 1.9})
    _db_raises(monkeypatch, "UPDATE user_files")
    with caplog.at_level("WARNING"):
        app._save_summary_background(SID, "d3@prc.local", "n = 1.9", "d3.xlsx")
    app.db("DELETE FROM session_summaries WHERE session_id=?", (SID,))
    assert any("back-fill" in r.message and "user_files" in r.message for r in caplog.records), \
        [r.message for r in caplog.records]


# ── session memory / file history context ────────────────────────────────────

def test_session_summary_db_failure_is_a_marker_not_an_empty_string(monkeypatch):
    _db_raises(monkeypatch)
    out = app.get_session_summary_context(SID)
    assert "[SESSION MEMORY UNAVAILABLE" in out
    assert _degraded("session-memory"), app.degradations()


def test_session_summary_corrupt_key_params_is_marked(monkeypatch):
    monkeypatch.setattr(app, "db", lambda q, p=(): [("W-1", "RI", "{not json")])
    out = app.get_session_summary_context(SID)
    assert "Well: W-1" in out and "key_params unreadable" in out
    assert _degraded("session-memory"), app.degradations()


def test_file_history_db_failure_is_a_marker_not_no_files(monkeypatch):
    _db_raises(monkeypatch)
    out = app.get_user_file_history_context("d3@prc.local", sid=SID)
    assert "[FILE HISTORY UNAVAILABLE" in out
    assert _degraded("file-history"), app.degradations()


def test_file_history_corrupt_key_params_is_marked(monkeypatch):
    def fake(q, p=()):
        if "DISTINCT fname" in q:
            return [("f1.xlsx",)]
        return [("f1.xlsx", "SCAL", "{bad", time.time())]
    monkeypatch.setattr(app, "db", fake)
    out = app.get_user_file_history_context("d3@prc.local", sid=SID)
    assert "f1.xlsx" in out and "key_params unreadable" in out
    assert _degraded("file-history"), app.degradations()


# ── _env_int ─────────────────────────────────────────────────────────────────

def test_env_int_bad_value_names_the_variable(monkeypatch):
    monkeypatch.setenv("D3_TEST_INT", "abc")
    assert app._env_int("D3_TEST_INT", 42) == 42
    assert any(d.startswith("env-default:") and "D3_TEST_INT" in d for d in app.degradations()), app.degradations()
    monkeypatch.setenv("D3_TEST_INT", "7")
    assert app._env_int("D3_TEST_INT", 42) == 7


# ── ground-truth preview parsing ─────────────────────────────────────────────

def test_sheet_preview_reports_unparseable_rows():
    rows = ["    ROW 1: [1, 2]", "    ROW 2: [1, 2, ]]]", "    ROW 3: [3, 4]"]
    out = app.format_sheet_as_markdown("S", ["a", "b"], rows, "3x2")
    assert "[1 ROWS UNPARSEABLE" in out, out


def test_truncate_marks_unparseable_column_headers():
    gt = ('  SHEET: "S"\n    COLUMNS (2): [oops unbalanced\n    FULL SHAPE: 1x2\n'
          "    ROW 1: [1, 2]\n")
    out = app._truncate_ground_truth(gt)
    assert "[COLUMN HEADERS UNPARSEABLE" in out and "Col 0" in out, out


# ── populate_cache_from_ground_truth ─────────────────────────────────────────

def _gt(*sheets):
    parts = []
    for name, cols, rows in sheets:
        parts.append(f'  SHEET: "{name}"\n    COLUMNS ({len(cols)}): {cols!r}\n    FULL SHAPE: {len(rows)}x{len(cols)}')
        for i, r in enumerate(rows, 1):
            parts.append(f"    ROW {i}: {r!r}")
    return "\n".join(parts) + "\n"


def _labeled():
    with app.SESSION_DATA_CACHE_LOCK:
        return dict(app.SESSION_DATA_CACHE[SID]["labeled_values"])


def test_populate_skips_a_sheet_whose_headers_do_not_parse():
    _seed()
    gt = '  SHEET: "Bad"\n    COLUMNS (2): [\'Swi, frac\', \'Sor\'\n    ROW 1: [0.25, 0.3]\n'
    app.populate_cache_from_ground_truth(SID, gt)
    labeled = _labeled()
    assert not any(k.startswith("bad.") for k in labeled) and "swi" not in labeled and "sor" not in labeled, labeled
    assert _degraded("cache-columns-unparseable"), app.degradations()


def test_populate_binds_scalar_cells_never_a_column_of_rows():
    _seed()
    app.populate_cache_from_ground_truth(SID, _gt(
        ("Samples", ["Porosity", "Permeability"], [[0.20, 150.0], [0.25, 300.0]]),
        ("Summary", ["Swi", "Sor"], [[0.25, 0.30]]),
    ))
    labeled = _labeled()
    assert "porosity" not in labeled and "permeability" not in labeled, labeled
    assert labeled["swi"] == 0.25 and labeled["sor"] == 0.30


def test_populate_refuses_ambiguous_canonical_keys_and_substring_aliases():
    _seed()
    app.populate_cache_from_ground_truth(SID, _gt(
        ("A", ["Sor"], [[0.30]]),
        ("B", ["Residual_Oil_Saturation"], [[0.35]]),
        ("Drilling", ["Absorption", "Slope"], [[5.0, 2.2]]),
    ))
    labeled = _labeled()
    assert "sor" not in labeled and "n" not in labeled, labeled
    assert _degraded("cache-alias-ambiguous"), app.degradations()


def test_populate_refuses_ambiguous_bare_keys_across_sheets():
    """A non-canonical label present on two sheets with different scalars must
    not be last-writer-wins under the bare key (rendered CACHED · HIGH)."""
    _seed()
    app.populate_cache_from_ground_truth(SID, _gt(
        ("A", ["Depth", "Temp"], [[100.0, 60.0]]),
        ("B", ["Depth", "Temp"], [[200.0, 60.0]]),
    ))
    labeled = _labeled()
    assert "depth" not in labeled, labeled
    assert labeled["a.depth"] == 100.0 and labeled["b.depth"] == 200.0     # sheet-qualified keys stay
    assert labeled["temp"] == 60.0                                          # agreeing candidates bind
    assert _degraded("cache-alias-ambiguous"), app.degradations()
    assert "[unverified" in app.process_provenance_tokens("{{val:depth}}", SID)


# ── cache_excel_data_vectors ─────────────────────────────────────────────────

def test_csv_read_failure_reaches_the_vector_lookup_error(monkeypatch, tmp_path):
    _seed()
    csv = tmp_path / "d3.csv"
    csv.write_text("Sw,RI\n1.0,1.0\n0.5,3.6\n", encoding="utf-8")

    def boom(path, **kw):
        raise ValueError("bad encoding (simulated)")
    monkeypatch.setattr(app, "smart_read_csv", boom)
    app.cache_excel_data_vectors(SID, str(csv))
    with app.SESSION_DATA_CACHE_LOCK:
        errors = list(app.SESSION_DATA_CACHE[SID].get("vector_errors", []))
    assert errors and "bad encoding" in errors[0], errors
    assert _degraded("cache-vectors"), app.degradations()
    with pytest.raises(app.VectorLookupError, match="bad encoding"):
        app.find_cached_vector(SID, "sw")


def test_sheet_without_a_numeric_table_is_recorded(tmp_path):
    _seed()
    csv = tmp_path / "text_only.csv"
    csv.write_text("a,b\nx,y\nz,w\n", encoding="utf-8")
    app.cache_excel_data_vectors(SID, str(csv))
    with app.SESSION_DATA_CACHE_LOCK:
        errors = list(app.SESSION_DATA_CACHE[SID].get("vector_errors", []))
    assert errors and "no numeric table" in errors[0], errors


# ── aligned column matchers ──────────────────────────────────────────────────

def test_bca_depth_is_never_the_permeability_column_and_synthesis_is_visible():
    _seed(raw_excel={"S": {"__aligned_vectors__": {"Porosity (%)": [20.0, 25.0, 30.0],
                                                    "K (mD)": [100.0, 200.0, 300.0]}}})
    phi, perm, depth, sheet, is_pct = app.find_aligned_bca_columns(SID)
    assert phi == [20.0, 25.0, 30.0] and perm == [100.0, 200.0, 300.0] and is_pct
    assert depth == [1.0, 2.0, 3.0], depth
    assert _degraded("depth-synthesized"), app.degradations()


def test_bca_two_porosity_columns_is_a_refusal_not_first_match():
    _seed(raw_excel={"S": {"__aligned_vectors__": {"Porosity": [0.2, 0.25], "PHI": [0.1, 0.3],
                                                    "K (mD)": [100.0, 200.0]}}})
    assert app.find_aligned_bca_columns(SID) == (None, None, None, None, False)
    assert _degraded("aligned-columns-ambiguous"), app.degradations()


def test_find_aligned_columns_marks_missing_params_and_synthetic_depth():
    _seed(raw_excel={"S": {"__aligned_vectors__": {"A": [1.0, 2.0], "B": [3.0, 4.0]}}})
    aligned, sheet = app.find_aligned_columns(SID, {"a": ["a"], "b": ["b"], "c": ["c"]})
    assert sheet == "S" and aligned["missing"] == ["c"] and aligned["depth_synthetic"] is True
    assert _degraded("aligned-columns-missing") and _degraded("depth-synthesized"), app.degradations()
    # substring aliasing is gone: 'ka' no longer binds to 'Kair'
    _seed(raw_excel={"S": {"__aligned_vectors__": {"Kair": [1.0, 2.0], "Pm": [3.0, 4.0]}}})
    assert app.find_aligned_columns(SID, {"ka": ["ka"], "pm": ["pm"]}) is None


# ── derived values ───────────────────────────────────────────────────────────

def test_unparseable_derived_input_is_a_marker_not_a_cache_substitution():
    _seed(labeled={"swi": 0.25, "sor": 0.30})
    out = app.process_provenance_tokens("Ed = {{val:displacement_efficiency|swi=abc,sor=0.3}}", SID)
    assert "DERIVED" not in out and "[unverified — unparseable input" in out, out


def test_derived_render_names_the_inputs_actually_used():
    _seed(labeled={"swi": 0.25})
    out = app.process_provenance_tokens("Ed = {{val:displacement_efficiency|sor=0.3}}", SID)
    assert "· DERIVED · HIGH" in out and "swi=0.25 (cache)" in out and "sor=0.3 (input)" in out, out


# ── {{val:key}} resolution grading ───────────────────────────────────────────

def test_cache_token_match_is_graded_below_exact_and_ambiguity_refuses():
    _seed(labeled={"archie.exponent_n": 1.9})
    out = app.process_provenance_tokens("n = {{val:n}}", SID)
    assert "1.900 · CACHED · MEDIUM" in out and "HIGH" not in out, out
    _seed(labeled={"sheet1.n": 1.9, "sheet2.n": 2.1})
    out = app.process_provenance_tokens("n = {{val:n}}", SID)
    assert "[unverified — ambiguous key" in out and "CACHED" not in out, out


def test_exact_key_stays_high_and_the_ground_truth_text_scan_is_gone():
    _seed(labeled={"n": 1.85}, ground_truth="Archie n: 2.5")
    assert "1.850 · CACHED · HIGH" in app.process_provenance_tokens("n = {{val:n}}", SID)
    _seed(labeled={}, ground_truth="Archie n: 2.5")
    out = app.process_provenance_tokens("n = {{val:n}}", SID)
    assert "2.5" not in out and "[unverified — absent from cache]" in out, out


def test_table_cells_keep_markers_and_a_short_provenance_tag():
    _seed(labeled={"iw": 0.68})
    text = ("| P | V |\n|---|---|\n| n | 2.14 {{val:n}} |\n| iw | {{val:iw}} |\n| zz | {{val:zz}} |\n"
            "| g | [unverified - no successful fit produced this value] |\n"
            "| iw2 | {{val:iw (frac)}} |\n")
    out = app.process_provenance_tokens(text, SID)
    cells = [ln.split("|")[2].strip() for ln in out.splitlines()[2:]]
    assert cells[0] == "-" and "2.14" not in out, out
    assert cells[1] == "0.680 · cached" and cells[2] == "-", out
    assert cells[4] == "0.680 · cached (key: iw)", out                    # token match keeps its grade
    assert cells[3] == "[unverified - no successful fit produced this value]", out
    assert app.process_provenance_tokens(out, SID) == out      # idempotent for the routes


# ── library ingest ───────────────────────────────────────────────────────────

_DOC = ("word " * 1200).encode()


def _purge_doc(data: bytes):
    h = hashlib.sha256(data).hexdigest()
    app.db("DELETE FROM library_chunks WHERE doc_id IN (SELECT id FROM library_docs WHERE file_hash=?)", (h,))
    app.db("DELETE FROM library_docs WHERE file_hash=?", (h,))


def test_library_ingest_refuses_when_no_chunk_embeds(monkeypatch):
    _purge_doc(_DOC)
    monkeypatch.setattr(app.KnowledgeBase, "_embed", staticmethod(lambda text: None))
    res = app._ingest_library_file(_DOC, "d3.txt", "d3@prc.local")
    assert "error" in res and "embed" in res["error"], res
    assert not app.db("SELECT id FROM library_docs WHERE file_hash=?", (hashlib.sha256(_DOC).hexdigest(),))


def test_library_ingest_partial_embedding_is_marked(monkeypatch):
    _purge_doc(_DOC)
    calls = iter(range(10_000))
    monkeypatch.setattr(app.KnowledgeBase, "_embed",
                        staticmethod(lambda text: None if next(calls) % 2 else np.zeros(3, dtype=np.float32)))
    try:
        res = app._ingest_library_file(_DOC, "d3.txt", "d3@prc.local")
        assert res["status"] == "partial" and res["chunks_unembedded"] >= 1 and res["chunks"] > res["chunks_unembedded"], res
    finally:
        _purge_doc(_DOC)


def test_library_ingest_cache_invalidate_runs_after_commit(monkeypatch):
    _purge_doc(_DOC)
    monkeypatch.setattr(app.KnowledgeBase, "_embed", staticmethod(lambda text: np.zeros(3, dtype=np.float32)))

    def boom():
        raise RuntimeError("invalidate exploded (simulated)")
    monkeypatch.setattr(app._LibraryEmbCache, "invalidate", boom)
    try:
        with pytest.raises(RuntimeError, match="invalidate exploded"):
            app._ingest_library_file(_DOC, "d3.txt", "d3@prc.local")
        # the insert was committed — the exception is not reported as a rolled-back ingest
        assert app.db("SELECT id FROM library_docs WHERE file_hash=?", (hashlib.sha256(_DOC).hexdigest(),))
    finally:
        _purge_doc(_DOC)


# ── api metrics ──────────────────────────────────────────────────────────────

def test_api_usage_cost_is_null_for_non_gemini_and_failure_is_visible(monkeypatch):
    app.db("DELETE FROM api_metrics WHERE session_id=?", (SID,))
    app._log_api_usage(SID, "gpt-oss-120b", 10, 10, provider="mock")
    rows = app.db("SELECT cost_usd FROM api_metrics WHERE session_id=?", (SID,))
    app.db("DELETE FROM api_metrics WHERE session_id=?", (SID,))
    assert rows and rows[0][0] is None, rows
    assert app._token_cost_usd("gemini", "gemini-2.5-pro", 1_000_000, 0) == 1.25
    _db_raises(monkeypatch, "INSERT INTO api_metrics")
    app._log_api_usage(SID, "gemini-2.5-flash", 10, 10, provider="gemini")
    assert _degraded("api-metrics-not-logged"), app.degradations()


# ── corrections ──────────────────────────────────────────────────────────────

def test_unsaved_correction_tag_is_not_silently_stripped(monkeypatch):
    _db_raises(monkeypatch, "INSERT INTO user_corrections")
    out = app._extract_and_log_corrections(SID, "d3@prc.local", "n is 1.9 [CORRECTION: n | 1.9] done")
    assert "[correction not saved: n | 1.9]" in out and "[CORRECTION:" not in out, out
    assert _degraded("correction-not-saved"), app.degradations()


def test_saved_correction_tag_is_stripped():
    out = app._extract_and_log_corrections(SID, "d3@prc.local", "n is 1.9 [CORRECTION: n | 1.9] done")
    app.db("DELETE FROM user_corrections WHERE session_id=?", (SID,))
    assert out == "n is 1.9  done"
