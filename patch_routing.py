import os

file_path = r'C:\Users\Asus\Downloads\scal-ai-pipeline\app.py'
with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

target1 = '''        def _generate():
            for attempt in range(len(self._keys)):'''

replacement1 = '''        def _generate():
            # Dynamic Model Routing
            msg_low_routing = msg.lower() if msg else ""
            needs_pro = (
                len(f_parts) > 0 or 
                bool(extracted_context) or 
                any(x in msg_low_routing for x in ["simulate", "audit", "calculate", "fit", "report", "plot", "parameter"])
            )
            active_model = "gemini-2.5-pro" if needs_pro else "gemini-2.5-flash"

            for attempt in range(len(self._keys)):'''

target2 = '''                            for chunk in client.models.generate_content_stream(
                                model=self.model_name, contents=current_contents, config=cfg
                            ):'''

replacement2 = '''                            for chunk in client.models.generate_content_stream(
                                model=active_model, contents=current_contents, config=cfg
                            ):'''

target3 = '''                        resp = client.models.generate_content(
                            model=self.model_name, contents=current_contents, config=cfg
                        )'''

replacement3 = '''                        resp = client.models.generate_content(
                            model=active_model, contents=current_contents, config=cfg
                        )'''

if target1 in content and target2 in content and target3 in content:
    content = content.replace(target1, replacement1)
    content = content.replace(target2, replacement2)
    content = content.replace(target3, replacement3)
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print("PATCH APPLIED SUCCESSFULLY")
else:
    print("PATCH FAILED - TARGET NOT FOUND")
