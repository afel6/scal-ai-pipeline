from pathlib import Path

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "hviel_system_prompt.md"

def test_prompt_file_exists():
    assert PROMPT_PATH.exists(), "SYSTEM_PROMPT file was deleted"

def test_prompt_minimum_length():
    content = PROMPT_PATH.read_text(encoding="utf-8")
    word_count = len(content.split())
    # Note: User specified word_count >= 800. 
    # The current prompt might be shorter, but v3 will definitely be longer.
    assert word_count >= 800, f"SYSTEM_PROMPT shrank to {word_count} words; minimum 800. Check for unintended rewrite."

def test_prompt_contains_required_phases():
    content = PROMPT_PATH.read_text(encoding="utf-8")
    required = [
        "PHASE 1", "PHASE 2", "PHASE 3", "PHASE 4",
        "PHASE 4.1", "PHASE 4.2", "PHASE 5", "PHASE 5.1", "PHASE 5.2",
        "PHASE 6", "SECTION 9",
        "NO blank lines between table rows",
        "NO HTML in tables",
        "forced fit", "free fit",
        "NOT IN DATA", "NOT IN THIS UPLOAD",
        "REFUSAL PROTOCOL",
    ]
    missing = [r for r in required if r not in content]
    assert not missing, f"SYSTEM_PROMPT is missing required sections: {missing}"
