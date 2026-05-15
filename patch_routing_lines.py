import os

file_path = r'C:\Users\Asus\Downloads\scal-ai-pipeline\app.py'
with open(file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i in range(len(lines)):
    if 'def _generate():' in lines[i]:
        # Insert routing logic right after def _generate():
        lines.insert(i+1, '''            # Dynamic Model Routing
            msg_low_routing = msg.lower() if msg else ""
            needs_pro = (
                len(f_parts) > 0 or 
                bool(extracted_context) or 
                any(x in msg_low_routing for x in ["simulate", "audit", "calculate", "fit", "report", "plot", "parameter"])
            )
            active_model = "gemini-2.5-pro" if needs_pro else "gemini-2.5-flash"\n''')
        break

for i in range(len(lines)):
    if 'client.models.generate_content_stream(' in lines[i]:
        if 'model=self.model_name' in lines[i+1]:
            lines[i+1] = lines[i+1].replace('model=self.model_name', 'model=active_model')
    elif 'client.models.generate_content(' in lines[i]:
        if 'model=self.model_name' in lines[i+1]:
            lines[i+1] = lines[i+1].replace('model=self.model_name', 'model=active_model')

with open(file_path, 'w', encoding='utf-8') as f:
    f.writelines(lines)
print("PATCH APPLIED WITH LINES")
