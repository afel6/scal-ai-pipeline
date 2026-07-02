import os
os.environ["DATABASE_URL"] = ""
import sys
import pytest
import time
import hashlib
from unittest.mock import MagicMock

# Mock google.genai client to prevent network calls during Genkit initialization
original_client = None
try:
    import google.genai
    original_client = google.genai.Client
    class MockModels:
        def list(self):
            return []
    class MockClient:
        def __init__(self, *args, **kwargs):
            self.models = MockModels()
    google.genai.Client = MockClient
except ImportError:
    pass

# Mock google.generativeai if needed
try:
    import google.generativeai as genai
    genai.configure = MagicMock()
    genai.GenerativeModel = MagicMock()
except ImportError:
    sys.modules['google.generativeai'] = MagicMock()

# Collision-safe import helper
def import_scal_app():
    original_path = list(sys.path)
    scal_dir = os.path.dirname(os.path.dirname(__file__))
    sys.path = [scal_dir] + [p for p in original_path if p != scal_dir]
    try:
        import app as scal_app
        return scal_app
    finally:
        sys.path = original_path

def import_pvt_app():
    original_path = list(sys.path)
    pvt_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "pvt-ai-pipeline")
    sys.path = [pvt_dir] + [p for p in original_path if p != pvt_dir]
    old_app = sys.modules.pop('app', None)
    old_config = sys.modules.pop('config', None)
    try:
        from src.api import app as pvt_app
        return pvt_app
    except (ImportError, ModuleNotFoundError) as e:
        print(f"Skipping PVT app import: {e}")
        return None
    finally:
        sys.path = original_path
        if old_app:
            sys.modules['app'] = old_app
        if old_config:
            sys.modules['config'] = old_config

scal_app = import_scal_app()
pvt_app = import_pvt_app()

# Restore original client to prevent mock leakage to other tests
if original_client is not None:
    google.genai.Client = original_client

from scal_file_handler import compress_traceability_ledger


class TestSCALFileIsolationRegressions:
    @pytest.fixture(autouse=True)
    def clean_db(self):
        try:
            scal_app.db("DELETE FROM user_files WHERE user_email LIKE ?", ("test_reg%",))
            scal_app.db("DELETE FROM m WHERE user_email LIKE ?", ("test_reg%",))
            scal_app.db("DELETE FROM session_cache WHERE sid LIKE ?", ("test_reg%",))
            scal_app.db("DELETE FROM sessions WHERE user_email LIKE ?", ("test_reg%",))
        except Exception:
            pass
        yield
        try:
            scal_app.db("DELETE FROM user_files WHERE user_email LIKE ?", ("test_reg%",))
            scal_app.db("DELETE FROM m WHERE user_email LIKE ?", ("test_reg%",))
            scal_app.db("DELETE FROM session_cache WHERE sid LIKE ?", ("test_reg%",))
            scal_app.db("DELETE FROM sessions WHERE user_email LIKE ?", ("test_reg%",))
        except Exception:
            pass

    def test_compress_traceability_ledger_fail_loud(self):
        # 1. Test clean matching (no mismatch)
        input_text = (
            "Source File: Mercury Injection Well T1-31.xls\n"
            "Worksheet: Sample 1\n"
            "Data Range: Row 14 Col 2 / Row 1 Col 4\n"
            "Extraction Engine: Deterministic Analytical Parser\n"
        )
        # Expected filenames match exactly (case insensitively)
        output = compress_traceability_ledger(input_text, ["Mercury Injection Well T1-31.xls"])
        assert "🔒 Data Integrity Status" in output
        assert "❌ Source Mismatch" not in output

        # 2. Test mismatch (fails loud)
        mismatch_output = compress_traceability_ledger(input_text, ["FFCAL-OBP, T1-31.xls"])
        assert "❌ Source Mismatch / Cannot Verify" in mismatch_output
        assert "Error: The cited source does not match the uploaded file's content hash." in mismatch_output
        assert "🔒 Data Integrity Status" not in mismatch_output

    def test_content_hash_cache_keying(self):
        sid = "test_reg_session"
        email = "test_reg@prc.ly"
        file_content_1 = b"file content 1 - Mercury Injection Well T1-31.xls"
        hash_1 = hashlib.sha256(file_content_1).hexdigest()

        # Check that resolve_cache_key returns the hash when a message with file_hash exists
        scal_app.db(
            "INSERT INTO m (sid, role, text, ts, user_email, fname, file_hash) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sid, "user", "msg1", time.time(), email, "Mercury Injection Well T1-31.xls", hash_1)
        )

        resolved = scal_app.resolve_cache_key(sid)
        assert resolved == hash_1

        # Test cache load and save using resolved cache key
        scal_app.SESSION_DATA_CACHE[hash_1] = {
            "ground_truth": "═══ FILE: Mercury Injection Well T1-31.xls ═══\nSome data",
            "labeled_values": {"porosity": 0.25}
        }
        scal_app.save_session_cache_to_db(sid)

        # Clear in-memory cache
        scal_app.SESSION_DATA_CACHE.pop(hash_1, None)
        assert hash_1 not in scal_app.SESSION_DATA_CACHE

        # Reload from DB via sid (which should resolve to hash_1)
        scal_app.load_session_cache_from_db(sid)
        assert hash_1 in scal_app.SESSION_DATA_CACHE
        assert scal_app.SESSION_DATA_CACHE[hash_1]["labeled_values"]["porosity"] == 0.25


class TestAvielFileIsolationRegressions:
    @pytest.fixture(autouse=True)
    def clean_db(self):
        if pvt_app:
            with pvt_app.KB._conn() as con:
                con.execute("DELETE FROM kb_chunks WHERE source LIKE 'test_reg%'")
                con.execute("DELETE FROM kb_documents WHERE filename LIKE 'test_reg%'")
                con.execute("DELETE FROM session_files WHERE sid LIKE 'test_reg%'")
                con.commit()
            pvt_app.SESSION_FILES.clear()

    def test_pvt_rag_isolation(self):
        if not pvt_app:
            pytest.skip("pvt_app not imported")

        hash_1 = "a" * 64
        hash_2 = "b" * 64

        # Ingest chunks under hash_1 and hash_2
        pvt_app.KB.ingest("test_reg_file1.xlsx", "This is content from file 1.", doc_type="session", sha=hash_1)
        pvt_app.KB.ingest("test_reg_file2.xlsx", "This is content from file 2.", doc_type="session", sha=hash_2)

        # Search without active_fhash -> should not return session chunks
        results_no_hash = pvt_app.KB.search("content", k=5)
        for r in results_no_hash:
            assert r["doc_type"] != "session"

        # Search with active_fhash = hash_1 -> should only return reference or hash_1 chunks
        results_hash_1 = pvt_app.KB.search("content", k=5, active_fhash=hash_1)
        sources = [r["source"] for r in results_hash_1]
        assert "test_reg_file1.xlsx" in sources
        assert "test_reg_file2.xlsx" not in sources

    def test_aviel_fail_loud_citations(self):
        if not pvt_app:
            pytest.skip("pvt_app not imported")

        # 1. Clean response
        text = "According to the report test_reg_file1.xlsx, the bubble point is 2000 psi."
        output = pvt_app.verify_citation(text, "test_reg_file1.xlsx")
        assert "### ❌ Source Mismatch" not in output
        assert "bubble point" in output

        # 2. Mismatched response
        mismatch_output = pvt_app.verify_citation(text, "test_reg_file2.xlsx")
        assert "### ❌ Source Mismatch / Cannot Verify" in mismatch_output

    def test_aviel_reference_citation_not_false_flagged(self):
        # Regression: citing a legitimate RAG reference doc alongside the active
        # upload must NOT trip the guard (was nuking the whole answer before).
        if not pvt_app:
            pytest.skip("pvt_app not imported")
        text = ("Per test_reg_file1.xlsx and the standard pvt_reference.md, "
                "Bo is 1.25.")
        allowed = {"test_reg_file1.xlsx", "pvt_reference.md"}
        output = pvt_app.verify_citation(text, allowed)
        assert "### ❌ Source Mismatch" not in output
        assert "Bo is 1.25" in output
        # A foreign file outside the allowed set still fails loud.
        foreign = pvt_app.verify_citation(
            "values from leaked_other.xlsx", {"test_reg_file1.xlsx"})
        assert "### ❌ Source Mismatch / Cannot Verify" in foreign

    def test_aviel_session_file_cross_worker_db(self):
        # Regression: active file hash must survive across worker processes.
        # Persist via DB, wipe the in-process L1 cache (simulating a different
        # uvicorn worker), and confirm get_session_file still resolves it.
        if not pvt_app:
            pytest.skip("pvt_app not imported")
        sid = "test_reg_xworker"
        pvt_app.set_session_file(sid, "test_reg_rep.pdf", "body text", "c0ffee")
        pvt_app.SESSION_FILES.clear()                 # other worker has empty L1
        rec = pvt_app.get_session_file(sid)
        assert rec is not None
        assert rec["sha256"] == "c0ffee"
        assert rec["filename"] == "test_reg_rep.pdf"
