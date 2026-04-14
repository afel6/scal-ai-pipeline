import urllib.request
import json
import ssl
ssl._create_default_https_context = ssl._create_unverified_context

req = urllib.request.Request(
    'https://scal-ai-pipeline.onrender.com/api/download/PRC_DOCX_1776127684.docx',
    method='GET',
    headers={
        'Origin': 'https://scal-ai-pipeline.vercel.app',
        'Access-Control-Request-Method': 'GET'
    }
)
try:
    with urllib.request.urlopen(req) as res:
        print('STATUS:', res.getcode())
        print('HEADERS:', res.headers)
except Exception as e:
    print('ERROR:', e)
