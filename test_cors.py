from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import uvicorn, threading, time, urllib.request

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])

@app.get('/test')
def test():
    with open('t.txt', 'w') as f: f.write('hello')
    return FileResponse('t.txt')

def run():
    uvicorn.run(app, host='127.0.0.1', port=8001, log_level='error')

t = threading.Thread(target=run, daemon=True)
t.start()
time.sleep(2)
req = urllib.request.Request('http://127.0.0.1:8001/test', headers={'Origin': 'http://localhost'})
res = urllib.request.urlopen(req)
print(res.headers)
