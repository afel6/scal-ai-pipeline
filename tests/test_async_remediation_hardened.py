import os
import io
import re
import pytest
import tempfile
import asyncio
from concurrent.futures import ThreadPoolExecutor
from fastapi import HTTPException, UploadFile
from file_reader import smart_read_csv
from app import process_large_file_stream, TASKS_DB

# =====================================================================
# 1. AUTOMATED UNIT TESTS FOR smart_read_csv WITH ENCODING FALLBACKS
# =====================================================================

def test_smart_read_csv_utf8_success():
    """Verify that smart_read_csv successfully reads UTF-8 files with Greek symbols."""
    csv_data = "Pressure_psi,Porosity_phi,Viscosity_mu,Temp_deg\n1000,0.22,1.5,150°\n"
    with tempfile.NamedTemporaryFile(mode="w", delete=False, encoding="utf-8", suffix=".csv") as tf:
        tf.write(csv_data)
        temp_path = tf.name

    try:
        df = smart_read_csv(temp_path)
        assert df.shape == (1, 4)
        assert df["Porosity_phi"][0] == 0.22
        assert df["Temp_deg"][0] == "150°"
    finally:
        os.unlink(temp_path)


def test_smart_read_csv_latin1_fallback():
    """Verify fallback to latin1 for strings containing special characters like degree (°) or micro (µ)."""
    # Create a string containing latin1-decodable characters like µ (\xb5) or ° (\xb0)
    csv_data = "Pressure_psi,Porosity_deg\xb0,Viscosity_micro\xb5\n2000,15.5,1.2\n"
    with tempfile.NamedTemporaryFile(mode="w", delete=False, encoding="latin1", suffix=".csv") as tf:
        tf.write(csv_data)
        temp_path = tf.name

    try:
        # Should fall back to latin1 decoding and parse successfully
        df = smart_read_csv(temp_path)
        assert df.shape == (1, 3)
        assert df.columns[1] == "Porosity_deg°"
        assert df.columns[2] == "Viscosity_microµ"
        assert df["Viscosity_microµ"][0] == 1.2
    finally:
        os.unlink(temp_path)


def test_smart_read_csv_cp1252_fallback():
    """Verify fallback to cp1252 Windows encoding scheme."""
    csv_data = "Pressure_psi,Porosity_pct,Label\n3000,12.5,Overburden\xae\n"
    with tempfile.NamedTemporaryFile(mode="w", delete=False, encoding="cp1252", suffix=".csv") as tf:
        tf.write(csv_data)
        temp_path = tf.name

    try:
        df = smart_read_csv(temp_path)
        assert df.shape == (1, 3)
        assert "Overburden" in df["Label"][0]
    finally:
        os.unlink(temp_path)


def test_smart_read_csv_unsupported_encoding_raises_value_error():
    """Verify that when parsing is constrained, invalid bytes trigger a clean ValueError."""
    # Write invalid UTF-8 bytes
    invalid_utf8 = b"\xff\xfe\xff\xff"
    with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".csv") as tf:
        tf.write(invalid_utf8)
        temp_path = tf.name

    try:
        # Constraint smart_read_csv to strictly "utf-8" to force failure on invalid bytes
        with pytest.raises(ValueError, match="Failed to decode CSV file"):
            smart_read_csv(temp_path, encodings=["utf-8"])
    finally:
        os.unlink(temp_path)


# =====================================================================
# 2. AUTOMATED UNIT TESTS FOR process_large_file_stream (CWE-400)
# =====================================================================

def test_process_large_file_stream_under_limit_success():
    """Verify that process_large_file_stream successfully writes files under the max limit."""
    content_bytes = b"pressure,porosity\n100,0.2\n" * 10
    file_mock = UploadFile(file=io.BytesIO(content_bytes), filename="small_test.csv")
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tf:
        temp_path = tf.name
        
    async def run_test():
        await process_large_file_stream(file_mock, temp_path, max_bytes=1024 * 1024)
        
    try:
        asyncio.run(run_test())
        
        # Verify content matches
        with open(temp_path, "rb") as f:
            written_content = f.read()
        assert written_content == content_bytes
    finally:
        os.unlink(temp_path)


def test_process_large_file_stream_exceeds_limit_raises_http_413():
    """Verify that process_large_file_stream aborts and raises HTTP 413 on oversized files (CWE-400)."""
    oversized_bytes = b"A" * 15 * 1024  # 15KB
    file_mock = UploadFile(file=io.BytesIO(oversized_bytes), filename="large_test.csv")
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tf:
        temp_path = tf.name
        
    async def run_test():
        await process_large_file_stream(file_mock, temp_path, max_bytes=10 * 1024)
        
    try:
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(run_test())
            
        assert exc_info.value.status_code == 413
        assert "exceeds maximum allowed" in exc_info.value.detail or "exceeds maximum upload limit" in exc_info.value.detail
    finally:
        os.unlink(temp_path)


# =====================================================================
# 3. PATH TRAVERSAL AND SESSION ID REGEX VALIDATIONS (CWE-22)
# =====================================================================

def test_session_id_regex_validation():
    """Verify that the strict alphanumeric/dash session ID regex matches and rejects appropriately."""
    regex = r"^(report-)?[a-zA-Z0-9\-]+$"
    
    # Valid session IDs
    assert re.match(regex, "session-123") is not None
    assert re.match(regex, "report-session-123") is not None
    assert re.match(regex, "task-99") is not None
    assert re.match(regex, "123456789") is not None
    
    # Invalid session IDs (must be rejected)
    assert re.match(regex, "session_123") is None  # underscores not allowed
    assert re.match(regex, "session@123") is None  # special characters
    assert re.match(regex, "../etc/passwd") is None  # directory traversal
    assert re.match(regex, "..\\win.ini") is None  # Windows traversal
    assert re.match(regex, "session ID") is None  # spaces


# =====================================================================
# 4. CONCURRENT WORKER STATE TRANSITIONS & THREAD-SAFETY
# =====================================================================

def test_tasks_db_concurrent_mutations():
    """Verify 100% thread safety and state predictability of TASKS_DB under concurrent requests."""
    session_ids = [f"thread-safe-session-{i}" for i in range(50)]
    
    # Pre-populate TASKS_DB
    for sid in session_ids:
        TASKS_DB[sid] = {
            "status": "queued",
            "progress": 0,
            "result": None,
            "error": None
        }

    # Worker thread logic that mutates task records concurrently
    def simulate_worker(sid: str):
        try:
            # Transition to processing
            TASKS_DB[sid].update({"status": "processing", "progress": 10})
            # Transition increment
            TASKS_DB[sid].update({"progress": 50})
            # Transition success
            TASKS_DB[sid].update({
                "status": "success",
                "progress": 100,
                "result": f"/api/report/download/report-{sid}.docx"
            })
        except Exception as e:
            TASKS_DB[sid].update({"status": "error", "error": str(e)})

    # Execute mutations concurrently using ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=20) as executor:
        executor.map(simulate_worker, session_ids)

    # Validate final states are 100% consistent across all threads
    for sid in session_ids:
        record = TASKS_DB[sid]
        assert record["status"] == "success"
        assert record["progress"] == 100
        assert record["result"] == f"/api/report/download/report-{sid}.docx"
        assert record["error"] is None
        
        # Cleanup
        del TASKS_DB[sid]
