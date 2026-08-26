import pytest
import re
import os
from fastapi.testclient import TestClient
from app import app


def _resolve_key():
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return key
    # Fall back to the app's key pool (populated from .env via load_dotenv),
    # but never treat the placeholder DUMMY_KEY as usable.
    try:
        from app import GEMINI_KEY_POOL
        if GEMINI_KEY_POOL and GEMINI_KEY_POOL[0] not in ("", "DUMMY_KEY"):
            return GEMINI_KEY_POOL[0]
    except Exception:
        pass
    return ""


_KEY = _resolve_key()

# Both tests exercise the live /api/chat LLM pipeline (real Gemini responses),
# so they are integration tests: skipped on CI (no secret) and run only when a
# real key is present locally. This lets the file be collected by `pytest tests/`
# without a dedicated --ignore entry.
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _KEY, reason="No usable GEMINI_API_KEY available (live API test)"),
]


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c

def send_chat(client, message: str, user_email: str = "test@prc.local", file_path: str = None):
    """
    Sends a chat message to the Hviel API via TestClient.
    Matches the multipart/form-data contract: message, user_email, and optional file.
    """
    url = "/api/chat"
    data = {
        "message": message,
        "user_email": user_email
    }
    
    # Endpoint signature is `files: list[UploadFile] = File(default=[])`, so the
    # multipart field name must be "files" — a mismatched name is silently dropped.
    files = []
    if file_path and os.path.exists(file_path):
        with open(file_path, "rb") as fh:
            files.append(("files", (os.path.basename(file_path), fh.read(), "application/vnd.ms-excel")))

    response = client.post(url, data=data, files=files or None)

    response.raise_for_status()
    return response.json()["reply"]

def test_no_html_in_response(client):
    """
    Task 3: Asserts <sub, <br, <sup do not appear in the response body when MICP data is analyzed.
    """
    fixture_path = "tests/fixtures/Mercury Injection Well T1-31.xls"
    prompt = "Analyze this MICP data and provide a summary of the petrophysical properties."
    reply = send_chat(client, prompt, file_path=fixture_path)
    
    forbidden = ["<sub", "<br", "<sup"]
    for tag in forbidden:
        assert tag not in reply.lower(), f"Forbidden HTML tag '{tag}' found in response."

def test_no_blank_lines_in_markdown_tables(client):
    """
    Task 3: Regex-asserts no blank lines between markdown table rows in a FF dataset response.
    """
    fixture_path = "tests/fixtures/FFCAL-OBP, T1-31.xls"
    prompt = "Generate a Formation Factor (FF) summary table for this dataset."
    reply = send_chat(client, prompt, file_path=fixture_path)
    
    blank_line_pattern = r"\|.*\|\s*\n\s*\n\s*\|"
    assert not re.search(blank_line_pattern, reply), "Found blank lines between markdown table rows."
