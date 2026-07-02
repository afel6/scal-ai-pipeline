import os
import sys
import time
import hashlib

print("Starting manual test runner...")

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
    try:
        import app as pvt_app
        return pvt_app
    except (ImportError, ModuleNotFoundError) as e:
        print(f"Skipping PVT app import: {e}")
        return None
    finally:
        sys.path = original_path

print("Importing apps...")
scal_app = import_scal_app()
pvt_app = import_pvt_app()

print("Importing compress_traceability_ledger...")
from scal_file_handler import compress_traceability_ledger

print("Running test_compress_traceability_ledger_fail_loud...")
# 1. Test clean matching (no mismatch)
input_text = (
    "Source File: Mercury Injection Well T1-31.xls\n"
    "Worksheet: Sample 1\n"
    "Data Range: Row 14 Col 2 / Row 1 Col 4\n"
    "Extraction Engine: Deterministic Analytical Parser\n"
)
output = compress_traceability_ledger(input_text, ["Mercury Injection Well T1-31.xls"])
print("Clean match output length:", len(output))
assert "🔒 Data Integrity Status" in output
assert "❌ Source Mismatch" not in output

# 2. Test mismatch (fails loud)
mismatch_output = compress_traceability_ledger(input_text, ["FFCAL-OBP, T1-31.xls"])
print("Mismatch match output length:", len(mismatch_output))
assert "❌ Source Mismatch / Cannot Verify" in mismatch_output

print("Running test_content_hash_cache_keying...")
sid = "test_reg_session"
email = "test_reg@prc.ly"
file_content_1 = b"file content 1 - Mercury Injection Well T1-31.xls"
hash_1 = hashlib.sha256(file_content_1).hexdigest()

scal_app.db("DELETE FROM m WHERE user_email='test_reg@prc.ly'")
scal_app.db(
    "INSERT INTO m (sid, role, text, ts, user_email, fname, file_hash) VALUES (?, ?, ?, ?, ?, ?, ?)",
    (sid, "user", "msg1", time.time(), email, "Mercury Injection Well T1-31.xls", hash_1)
)

resolved = scal_app.resolve_cache_key(sid)
assert resolved == hash_1

scal_app.SESSION_DATA_CACHE[hash_1] = {
    "ground_truth": "═══ FILE: Mercury Injection Well T1-31.xls ═══\nSome data",
    "labeled_values": {"porosity": 0.25}
}
scal_app.save_session_cache_to_db(sid)

scal_app.SESSION_DATA_CACHE.pop(hash_1, None)
scal_app.load_session_cache_from_db(sid)
assert hash_1 in scal_app.SESSION_DATA_CACHE
assert scal_app.SESSION_DATA_CACHE[hash_1]["labeled_values"]["porosity"] == 0.25

print("SCAL tests passed!")

if pvt_app:
    print("Running PVT tests...")
    with pvt_app.KB._conn() as con:
        con.execute("DELETE FROM kb_chunks WHERE source LIKE 'test_reg%'")
        con.execute("DELETE FROM kb_documents WHERE filename LIKE 'test_reg%'")
        con.commit()
    pvt_app.SESSION_FILES.clear()

    hash_1 = "a" * 64
    hash_2 = "b" * 64

    pvt_app.KB.ingest("test_reg_file1.xlsx", "This is content from file 1.", doc_type="session", sha=hash_1)
    pvt_app.KB.ingest("test_reg_file2.xlsx", "This is content from file 2.", doc_type="session", sha=hash_2)

    results_no_hash = pvt_app.KB.search("content", k=5)
    for r in results_no_hash:
        assert r["doc_type"] != "session"

    results_hash_1 = pvt_app.KB.search("content", k=5, active_fhash=hash_1)
    sources = [r["source"] for r in results_hash_1]
    assert "test_reg_file1.xlsx" in sources
    assert "test_reg_file2.xlsx" not in sources

    text = "According to the report test_reg_file1.xlsx, the bubble point is 2000 psi."
    output = pvt_app.verify_citation(text, "test_reg_file1.xlsx")
    assert "### ❌ Source Mismatch" not in output

    mismatch_output = pvt_app.verify_citation(text, "test_reg_file2.xlsx")
    assert "### ❌ Source Mismatch / Cannot Verify" in mismatch_output
    print("PVT tests passed!")

print("All manual tests completed successfully!")
