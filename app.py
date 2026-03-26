from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import json
import uuid
import time
import pandas as pd
import re
import sqlite3
from typing import Optional
from datetime import datetime
import google.generativeai as genai
from docx import Document
from docx.shared import Inches, Pt, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH

# ── CONFIGURATION ──
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "DUMMY_KEY")
DB_PATH = "chat_history.db"

# ── AI ENGINE ──
class PRCChatAssistant:
    def __init__(self, api_key: str):
        self.api_key = api_key
        if self.api_key and self.api_key != "DUMMY_KEY":
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel(
                model_name='gemini-1.5-flash',
                system_instruction="You are 'Hviel', a Senior Reservoir Engineer at the PRC. Request data (Porosity, Sw, RI) then trigger report via JSON: { '__PRC_REPORT__': true, 'data': [...], 'ai_conclusion': '...' }."
            )
    def process_chat(self, history: list, msg: str, f: bytes = None, m: str = None) -> str:
        h = [{"role": 'user' if x['role'] == 'user' else 'model', "parts": [x['text']]} for x in history]
        c = [msg]
        if f: c.append({'mime_type': m, 'data': f})
        return self.model.start_chat(history=h).send_message(c).text

# ── REPORTING ──
class SCALReportBuilder:
    def __init__(self, well_name, raw_df, engineer_name):
        self.doc = Document()
        self.well_name = well_name
        self.raw_df = raw_df
        self.engineer_name = engineer_name
    def build_report(self, archie_params, ai_conclusion):
        self.doc.add_heading(f'PRC TECHNICAL EVALUATION: {self.well_name}', 0)
        self.doc.add_paragraph(f"Engineer: {self.engineer_name}\nDate: {datetime.now().strftime('%Y-%m-%d')}")
        self.doc.add_heading('Petrophysical Summary', level=1)
        table = self.doc.add_table(rows=1, cols=4); table.style = 'Table Grid'
        hdrs = ['Porosity', 'FF', 'Sw', 'RI']
        for i, h in enumerate(hdrs): table.rows[0].cells[i].text = h
        for p in archie_params:
            row = table.add_row().cells
            row[0].text = str(p['Porosity']); row[1].text = str(round(1/(p['Porosity']**2),2)); row[2].text = str(p['Brine_Saturation']); row[3].text = str(p['Resistivity_Index'])
        self.doc.add_heading('AI Conclusion', level=1)
        self.doc.add_paragraph(ai_conclusion)
        f = f"{self.well_name}_Report.docx"
        self.doc.save(f)
        return f

# ── DB ──
def init_db():
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, role TEXT, text TEXT, download_url TEXT, created_at REAL)')
    conn.commit(); conn.close()
def save_msg(sid, role, text, url=None):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("INSERT INTO messages (session_id, role, text, download_url, created_at) VALUES (?, ?, ?, ?, ?)", (sid, role, text, url, time.time()))
    conn.commit(); conn.close()
def get_msgs(sid):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("SELECT role, text, download_url FROM messages WHERE session_id = ? ORDER BY id ASC", (sid,))
    rows = c.fetchall(); conn.close()
    return [{"role": r, "text": t, "download_url": d} for r, t, d in rows]

# ── ENDPOINTS ──
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
chat_ai = PRCChatAssistant(api_key=GEMINI_API_KEY)
init_db()

@app.post("/api/chat")
async def chat_endpoint(message: str = Form(...), session_id: Optional[str] = Form(None), engineer_name: str = Form("PRC Engineer"), file: Optional[UploadFile] = File(None)):
    if not session_id or session_id == "undefined": session_id = str(uuid.uuid4())
    history = get_msgs(session_id)
    f_bytes, m_type = None, None
    if file:
        f_bytes = await file.read(); m_type = file.content_type
        if "spreadsheet" in m_type or file.filename.endswith(('.xlsx', '.csv')):
             df = pd.read_excel(f_bytes) if not file.filename.endswith('.csv') else pd.read_csv(pd.io.common.BytesIO(f_bytes))
             message += f"\n[FILE DATA]:\n{df.head(10).to_string()}"
             f_bytes = None
    try:
        resp = chat_ai.process_chat(history, message, f_bytes, m_type)
        m = re.search(r'```json\s*(\{.*?__PRC_REPORT__.*?\})\s*```', resp, re.DOTALL)
        if m:
            data = json.loads(m.group(1)); df = pd.DataFrame(data['data'])
            builder = SCALReportBuilder(f"Study_{int(time.time())}", df, engineer_name)
            doc_path = builder.build_report(data['data'], data['ai_conclusion'])
            dl_url = f"/api/download/{doc_path}"
            reply = "Report Generated. Click below to download."
            save_msg(session_id, "user", message); save_msg(session_id, "model", reply, dl_url)
            return {"status":"success", "is_report_ready":True, "download_url":dl_url, "session_id":session_id, "reply":reply}
        reply = re.sub(r'```json.*?```', '', resp, flags=re.DOTALL).strip()
        save_msg(session_id, "user", message); save_msg(session_id, "model", reply)
        return {"status":"success", "session_id":session_id, "reply":reply}
    except Exception as e:
        return {"status":"error", "is_error":True, "reply": f"AI at capacity. Wait 3 mins. ({str(e)[:50]})"}

@app.get("/api/download/{filename}")
async def dl(filename: str): return FileResponse(path=filename, filename=filename)

@app.get("/")
def root(): return {"status": "PRC AI HUB ONLINE"}
