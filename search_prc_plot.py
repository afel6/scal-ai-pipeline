import os

keywords = ["__PRC_PLOT__", "plotData", "curves"]
workspace = r"c:\Users\Asus\Downloads\scal-ai-pipeline"

for root, dirs, files in os.walk(workspace):
    if ".venv" in root or ".git" in root or "node_modules" in root or ".gemini" in root:
        continue
    for file in files:
        if file.endswith((".py", ".js", ".jsx", ".html")):
            path = os.path.join(root, file)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                for kw in keywords:
                    if kw in content:
                        print(f"Found '{kw}' in: {os.path.relpath(path, workspace)}")
            except Exception as e:
                pass
