import pytest
import requests
import re

# We'll assume the server is running on localhost:8000
BASE_URL = "http://localhost:8000"

def send_chat(message: str, user_email: str = "test@prc.local"):
    """
    Sends a chat message to the Hviel API.
    Matches the multipart/form-data contract: message, user_email.
    """
    url = f"{BASE_URL}/api/chat"
    data = {
        "message": message,
        "user_email": user_email
    }
    # Using files=[] or just not passing files since it's Optional
    response = requests.post(url, data=data)
    response.raise_for_status()
    return response.json()["reply"]

def test_no_html_in_response():
    """
    Task 3: Asserts <sub, <br, <sup do not appear in the response body when MICP data is analyzed.
    Note: v3 is expected to FAIL this test.
    """
    # Trigger MICP analysis with a prompt that usually causes HTML formatting in v2
    prompt = "Analyze this MICP data: Sample A-1, Pressure 10 psia, Saturation 0.95. Pressure 100 psia, Saturation 0.80."
    reply = send_chat(prompt)
    
    # Check for forbidden HTML tags
    forbidden = ["<sub", "<br", "<sup"]
    for tag in forbidden:
        assert tag not in reply.lower(), f"Forbidden HTML tag '{tag}' found in response."

def test_no_blank_lines_in_markdown_tables():
    """
    Task 3: Regex-asserts no blank lines between markdown table rows in a FF dataset response.
    Note: v3 is expected to FAIL this test.
    """
    # Trigger a table-heavy response
    prompt = "Generate a Formation Factor (FF) summary table for Sample Well-7 at 400, 800, and 1500 psig."
    reply = send_chat(prompt)
    
    # Regex to find blank lines between table rows
    # A table row usually looks like | ... |
    # We look for: | row |\n[whitespace]*\n| next row |
    blank_line_pattern = r"\|.*\|\s*\n\s*\n\s*\|"
    
    assert not re.search(blank_line_pattern, reply), "Found blank lines between markdown table rows."
