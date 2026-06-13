import os
from google import genai

key = os.environ.get("GEMINI_API_KEY", "")
# Read from the app.py directly if it's there? No, we will read the env
import sys
sys.path.append(r"c:\Users\Asus\Downloads\scal-ai-pipeline")
try:
    from app import GEMINI_KEY_POOL
    if GEMINI_KEY_POOL:
        key = GEMINI_KEY_POOL[0]
except ImportError:
    pass

if key:
    client = genai.Client(api_key=key, http_options={'api_version': 'v1beta'})
    try:
        for m in client.models.list():
            print(m.name)
    except Exception as e:
        print("V1BETA ERROR:", e)

    client_v1 = genai.Client(api_key=key, http_options={'api_version': 'v1'})
    try:
        for m in client_v1.models.list():
            print(m.name)
    except Exception as e:
        print("V1 ERROR:", e)
else:
    print("Skipping models test as no GEMINI_API_KEY is available.")
