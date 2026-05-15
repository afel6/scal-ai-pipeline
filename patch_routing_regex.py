import os
import re

file_path = r'C:\Users\Asus\Downloads\scal-ai-pipeline\app.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Replace the beginning of _generate
def_generate_pattern = r'(def _generate\(\):\s+)(for attempt in range\(len\(self\._keys\)\):)'
def_generate_repl = r'''\1# Dynamic Model Routing
            msg_low_routing = msg.lower() if msg else ""
            needs_pro = (
                len(f_parts) > 0 or 
                bool(extracted_context) or 
                any(x in msg_low_routing for x in ["simulate", "audit", "calculate", "fit", "report", "plot", "parameter"])
            )
            active_model = "gemini-2.5-pro" if needs_pro else "gemini-2.5-flash"

            \2'''

content = re.sub(def_generate_pattern, def_generate_repl, content)

# Replace the streaming call
stream_pattern = r'(client\.models\.generate_content_stream\(\s+model=)self\.model_name(,\s*contents=current_contents,\s*config=cfg\s*\))'
stream_repl = r'\g<1>active_model\2'
content = re.sub(stream_pattern, stream_repl, content)

# Replace the non-streaming call
non_stream_pattern = r'(client\.models\.generate_content\(\s+model=)self\.model_name(,\s*contents=current_contents,\s*config=cfg\s*\))'
non_stream_repl = r'\g<1>active_model\2'
content = re.sub(non_stream_pattern, non_stream_repl, content)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("PATCH APPLIED WITH REGEX")
