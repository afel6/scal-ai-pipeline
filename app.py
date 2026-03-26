from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import os, json, uuid, time, re, sqlite3
import pandas as pd
from typing import Optional
from datetime import datetime
import google.generativeai as genai
from docx import Document

# ── CONFIG ──
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "DUMMY_KEY")
DB_PATH = "chat_history.db"

# ── HVIEL BRAIN (ULTRA STABLE) ──
class PRCChatAssistant:
    def __init__(self, key):
        self.key = key
        if key and key != "DUMMY_KEY":
            genai.configure(api_key=key)
            self.model = genai.GenerativeModel('gemini-2.5-flash')
    def chat(self, history, msg, f=None, m=None):
        h = [{"role":'user' if x['role']=='user' else 'model', "parts":[x['text']]} for x in history]
        c = [msg]
        if f: c.append({'mime_type':m, 'data':f})
        try:
            return self.model.start_chat(history=h).send_message(c).text
        except:
            fallback = genai.GenerativeModel('gemini-2.0-flash')
            return fallback.start_chat(history=h).send_message(msg).text

# ── REPORTING ──
class Reporter:
    @staticmethod
    def build(well, df, eng, insight):
        doc = Document(); doc.add_heading(f'PRC EVALUATION: {well}', 0)
        doc.add_paragraph(f"Engineer: {eng}\nAnalysis:\n{insight}")
        f = f"PRC_{int(time.time())}.docx"; doc.save(f); return f

# ── APP ──
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
assistant = PRCChatAssistant(GEMINI_API_KEY)
def db(q, p=()):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor(); c.execute(q, p); res = c.fetchall(); conn.commit(); conn.close(); return res
db('CREATE TABLE IF NOT EXISTS m (id INTEGER PRIMARY KEY, sid TEXT, role TEXT, text TEXT, url TEXT, ts REAL)')

@app.post("/api/chat")
async def handle(message: str = Form(...), session_id: Optional[str] = Form(None), engineer_name: str = Form("PRC Engineer"), file: Optional[UploadFile] = File(None)):
    sid = session_id if (session_id and session_id != "undefined") else str(uuid.uuid4())
    history = [{"role":r, "text":t} for r,t,u in db("SELECT role, text, url FROM m WHERE sid = ? ORDER BY id", (sid,))]
    f_b, m_t = None, None
    if file:
        f_b = await file.read(); m_t = file.content_type
        if "sheet" in m_t or file.filename.endswith(('.xlsx', '.csv')):
             df = pd.read_excel(f_b) if not file.filename.endswith('.csv') else pd.read_csv(pd.io.common.BytesIO(f_b))
             message += f"\n[DATA]:\n{df.head(5).to_string()}"; f_b = None
    try:
        resp = assistant.chat(history, message, f_b, m_t)
        if '__PRC_REPORT__' in resp:
            path = Reporter.build(f"Study_{int(time.time())}", None, engineer_name, resp)
            url = f"/api/download/{path}"
            db("INSERT INTO m (sid, role, text, url, ts) VALUES (?, ?, ?, ?, ?)", (sid, "model", "Report Ready", url, time.time()))
            return {"status":"success", "is_report_ready":True, "download_url":url, "session_id":sid, "reply":"Report Ready."}
        db("INSERT INTO m (sid, role, text, ts) VALUES (?, ?, ?, ?)", (sid, "model", resp, time.time()))
        return {"status":"success", "session_id":sid, "reply":resp}
    except Exception as e:
        return {"status":"error", "is_error":True, "reply": f"SYSTEM RECOVERY ACTIVE: {str(e)[:50]}"}

@app.get("/api/diag")
def diag():
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        models = [m.name for m in genai.list_models()]
        return {"models": models, "key_len": len(GEMINI_API_KEY), "key_start": GEMINI_API_KEY[:4]}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/download/{filename}")
async def dl(filename: str): return FileResponse(path=filename, filename=filename)

@app.get("/")
def root(): return {"v": "PRC-HUB-ULTRA-VER-6-FINAL"}
