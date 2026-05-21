import sys
sys.stdout.reconfigure(encoding='utf-8')

with open(r"c:\Users\Asus\Downloads\scal-ai-pipeline\app.py", "r", encoding="utf-8") as f:
    content = f.read()

# Let's search for "plot_pc =" or similar inside app.py
lines = content.splitlines()
for idx, line in enumerate(lines):
    if "plot_pc =" in line or "plot_ri =" in line or "plot_ff =" in line or "plot_j =" in line or "plot_kr =" in line:
        print(f"Line {idx+1}: {line.strip()}")
        # print the next 20 lines to see the structure
        start = idx
        end = min(len(lines), idx + 35)
        for i in range(start, end):
            print(f"  {i+1}: {lines[i]}")
        print("-" * 60)
