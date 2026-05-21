with open(r"c:\Users\Asus\Downloads\scal-ai-pipeline\app.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

for idx, line in enumerate(lines):
    if "__PRC_PLOT__" in line:
        print(f"Line {idx+1}: {line.strip()}")
        # print 5 lines before and after
        start = max(0, idx - 5)
        end = min(len(lines), idx + 10)
        for i in range(start, end):
            print(f"  {i+1}: {lines[i]}", end="")
        print("-" * 40)
