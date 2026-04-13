import os, urllib.request, json
from dotenv import load_dotenv
load_dotenv()
key = os.getenv('CLAUDE_API_KEY')
print("Testing Key:", key[:15] + "...")
req = urllib.request.Request('https://api.anthropic.com/v1/messages', method='POST', headers={'x-api-key': key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'}, data=b'{"model":"claude-3-5-sonnet-20240620","max_tokens":10,"messages":[{"role":"user","content":"hi"}]}')
try:
    urllib.request.urlopen(req)
    print('SUCCESS')
except Exception as e:
    resp = e.read().decode('utf-8')
    print('ERROR:', resp)
