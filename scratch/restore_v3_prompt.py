import subprocess
import re
import os

def restore_prompt():
    # 1. Get the app.py content from commit 368dea6
    cmd = ["git", "show", "368dea6:app.py"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        if result.returncode != 0:
            print(f"Error running git show: {result.stderr}")
            return
        app_content = result.stdout
    except Exception as e:
        print(f"Exception running git show: {e}")
        return

    # 2. Extract SYSTEM_PROMPT = """..."""
    # Using re.DOTALL to match across multiple lines
    match = re.search(r'SYSTEM_PROMPT\s*=\s*"""(.*?)"""', app_content, re.DOTALL)
    if not match:
        print("Could not find SYSTEM_PROMPT in app.py from 368dea6")
        return
    
    prompt_body = match.group(1)
    lines = prompt_body.strip().splitlines()
    
    # 3. Apply requested modifications
    # "the prompt body should begin with the line You are a Senior Petrophysicist and SCAL Specialist at PRC (Petroleum Research Center)."
    # Current first line is likely "SYSTEM PROMPT: SENIOR SCAL ANALYST & PETROPHYSICIST"
    lines[0] = "You are a Senior Petrophysicist and SCAL Specialist at PRC (Petroleum Research Center)."
    
    # "and contain ## PHASE 1: TRACK CLASSIFICATION early on."
    # Current line is likely "# PHASE 1: UNIVERSAL SENSING (AUTO-CLASSIFY)"
    phase1_replaced = False
    for i, line in enumerate(lines):
        if "# PHASE 1: UNIVERSAL SENSING (AUTO-CLASSIFY)" in line:
            lines[i] = "## PHASE 1: TRACK CLASSIFICATION"
            phase1_replaced = True
            break
    
    if not phase1_replaced:
        print("Warning: Could not find PHASE 1 header to replace.")
    
    restored_body = "\n".join(lines)
    
    # 4. Read the protective header from prompts/hviel_system_prompt.md
    prompt_file = "prompts/hviel_system_prompt.md"
    if not os.path.exists(prompt_file):
        print(f"Error: {prompt_file} not found.")
        return
        
    with open(prompt_file, "r", encoding="utf-8") as f:
        original = f.read()
    
    header_match = re.search(r'^(<!--.*?-->)', original, re.DOTALL)
    if not header_match:
        print("Error: Could not find protective header in prompts/hviel_system_prompt.md")
        return
    
    header = header_match.group(1)
    
    # 5. Assemble final content
    final_content = header + "\n\n" + restored_body
    
    # 6. Write back to prompts/hviel_system_prompt.md
    with open(prompt_file, "w", encoding="utf-8") as f:
        f.write(final_content)
    
    print("Successfully restored v3 prompt body with requested modifications.")

if __name__ == "__main__":
    restore_prompt()
