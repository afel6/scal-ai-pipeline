import os

files_to_bundle = [
    "app.py",
    "document_engines.py",
    "frontend/src/App.jsx",
    "frontend/src/KrPlot.jsx"
]

output_file = "PRC_AI_UPGRADE_BUNDLE.txt"

with open(output_file, "w", encoding="utf-8") as outfile:
    outfile.write("PRC SCAL AI PIPELINE - ARCHITECTURAL UPGRADE BUNDLE\n")
    outfile.write("="*60 + "\n\n")
    
    for filepath in files_to_bundle:
        outfile.write(f"FILE: {filepath}\n")
        outfile.write("-" * 40 + "\n")
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as infile:
                outfile.write(infile.read())
        else:
            outfile.write(f"ERROR: {filepath} not found.\n")
        outfile.write("\n\n" + "="*60 + "\n\n")

print(f"Bundle created: {output_file}")
