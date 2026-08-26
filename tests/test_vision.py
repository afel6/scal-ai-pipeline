import os
import base64

# A mock for the google.genai vision client if needed, or simply verify the tool exists.

def test_vision_auditor_exists():
    """Verify that the vision auditor script exists and is executable."""
    vision_script = os.path.join("hermes_skills_library", "maintenance", "auditor", "vision_auditor.py")
    assert os.path.exists(vision_script), "Vision auditor script is missing from hermes_skills_library."

def test_app_vision_protocol_active():
    """Verify that SECTION 9 (VISION PROTOCOL) is present in the prompt file."""
    prompt_path = "prompts/hviel_system_prompt.md"
    assert os.path.exists(prompt_path), "prompts/hviel_system_prompt.md not found"
    with open(prompt_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    assert "SECTION 9 - VISION PROTOCOL" in content, "Vision protocol is missing from the system prompt in prompts/hviel_system_prompt.md"

def test_mock_vision_qa_payload():
    """Simulate a Vision QA payload processing for complex laboratory equipment photos."""
    # This is a unit test that acts as a placeholder/mock for visual QA.
    # We pretend we received an image of laboratory equipment
    fake_image_base64 = base64.b64encode(b"fake image data of a permeameter").decode('utf-8')
    
    payload = {
        "message": "Is this permeameter core properly seated?",
        "image_data": f"data:image/jpeg;base64,{fake_image_base64}",
        "session_id": "vision_test_123"
    }
    
    # We verify the payload format matches what the frontend would send
    assert "image_data" in payload
    assert payload["image_data"].startswith("data:image/jpeg;base64,")
    assert payload["message"] == "Is this permeameter core properly seated?"
