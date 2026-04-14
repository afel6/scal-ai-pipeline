import requests
import os

url = "https://scal-ai-pipeline.onrender.com/api/download/PRC_DOCX_1775424467.docx"
res = requests.get(url)

print(f"STATUS: {res.status_code}")
print("HEADERS:")
for k, v in res.headers.items():
    print(f"  {k}: {v}")

content_disp = res.headers.get("Content-Disposition")
print(f"\nContent-Disposition: {content_disp}")
