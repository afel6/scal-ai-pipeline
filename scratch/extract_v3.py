import sys

def extract_prompt(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    marker = 'SYSTEM_PROMPT = """'
    start_idx = content.find(marker)
    if start_idx == -1:
        print("Marker not found")
        return
    
    start_idx += len(marker)
    end_idx = content.find('"""', start_idx)
    if end_idx == -1:
        print("End quote not found")
        return
    
    return content[start_idx:end_idx]

if __name__ == "__main__":
    prompt = extract_prompt('v3_app.py')
    if prompt:
        with open('v3_prompt_body.md', 'w', encoding='utf-8') as f:
            f.write(prompt)
        print("Extracted successfully")
