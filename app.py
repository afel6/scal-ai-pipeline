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

# ── CONFIGURATION ──
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "DUMMY_KEY")
DB_PATH = "chat_history.db"

# ── AI ENGINE (WITH FALLBACKS) ──
class PRCChatAssistant:
    def __init__(self, api_key: str):
        self.api_key = api_key
        if self.api_key and self.api_key != "DUMMY_KEY":
            genai.configure(api_key=api_key)
            # Try Flash first, then Pro as ultimate safety
            self.model_name = 'gemini-1.5-flash'
            self.system_prompt = "You are 'Hviel', a Senior Reservoir Engineer at the Libyan PRC. professional and elite. use JSON trigger: { '__PRC_REPORT__': true, 'data': [...], 'ai_conclusion': '...' }."
            self.model = genai.GenerativeModel(model_name=self.model_name, system_instruction=self.system_prompt)

    def process_chat(self, history: list, msg: str, f: bytes = None, m: str = None) -> str:
        if not self.api_key or self.api_key == "DUMMY_KEY":
            return "CRITICAL FAULT: No API Key."
        
        h = [{"role": 'user' if x['role'] == 'user' else 'model', "parts": [x['text']]} for x in history]
        chat = self.model.start_chat(history=h)
        
        try:
            return chat.send_message([msg, {'mime_type': m, 'data': f}] if f else [msg]).text
        except Exception as e:
            if "404" in str(e) and "flash" in self.model_name:
                # FALLBACK TO PRO IF FLASH IS NOT FOUND
                self.model_name = 'gemini-pro'
                self.model = genai.GenerativeModel(model_name=self.model_name, system_instruction=self.system_prompt)
                chat = self.model.start_chat(history=h)
                return chat.send_message([msg]).text
            raise e

# ── REPORTING (STABLE) ──
class SCALReportBuilder:
    def __init__(self, well_name, raw_df, engineer_name):
        self.doc = Document(); self.well_name = well_name; self.raw_df = raw_df; self.engineer_name = engineer_name
    def build_report(self, archie_params, ai_conclusion):
        self.doc.add_heading(f'PRC TECHNICAL EVALUATION: {self.well_name}', 0)
        table = self.doc.add_table(rows=1, cols=4); table.style = 'Table Grid'
        hdrs = ['Porosity', 'FF', 'Sw', 'RI']
        for i, h in enumerate(hdrs): table.rows[0].cells[i].text = h
        for p in archie_params:
            r = table.add_row().cells
            r[0].text = str(p.get('Porosity', 0.2)); r[1].text = "2.0"; r[2].text = str(p.get('Brine_Saturation', 1.0)); r[3].text = str(p.get('Resistivity_Index', 1.0))
        self.doc.add_paragraph(f"\nAI Conclusion:\n{ai_conclusion}")
        f = f"PRC_Report_{int(time.time())}.docx"
        self.doc.save(f); return f

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

# ── APP ──
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
assistant = PRCChatAssistant(api_key=GEMINI_API_KEY)
init_db()

@app.post("/api/chat")
async def chat_endpoint(message: str = Form(...), session_id: Optional[str] = Form(None), engineer_name: str = Form("PRC Engineer"), file: Optional[UploadFile] = File(None)):
    if not session_id or session_id == "undefined": session_id = str(uuid.uuid4())
    history = get_msgs(session_id)
    f_b, m_t = None, None
    if file:
        f_b = await file.read(); m_t = file.content_type
        if "spreadsheet" in m_t or file.filename.endswith(('.xlsx', '.csv')):
             df = pd.read_excel(f_b) if not file.filename.endswith('.csv') else pd.read_csv(pd.io.common.BytesIO(f_b))
             message += f"\n[ATTACHED DATA]:\n{df.head(10).to_string()}"; f_b = None
    try:
        resp = assistant.process_chat(history, message, f_b, m_t)
        m = re.search(r'```json\s*(\{.*?__PRC_REPORT__.*?\})\s*```', resp, re.DOTALL)
        if m:
            data = json.loads(m.group(1)); builder = SCALReportBuilder(f"Study_{int(time.time())}", pd.DataFrame(data['data']), engineer_name)
            path = builder.build_report(data['data'], data['ai_conclusion']); d_url = f"/api/download/{path}"
            reply = "Report Generated. Download below."
            save_msg(session_id, "user", message); save_msg(session_id, "model", reply, d_url)
            return {"status":"success", "is_report_ready":True, "download_url":d_url, "session_id":session_id, "reply":reply}
        reply = re.sub(r'```json.*?```', '', resp, flags=re.DOTALL).strip()
        save_msg(session_id, "user", message); save_msg(session_id, "model", reply)
        return {"status":"success", "session_id":session_id, "reply":reply}
    except Exception as e:
        return {"status":"error", "is_error":True, "reply": f"HVIEL RECOVERY MODE: {str(e)[:100]}"}

@app.get("/api/download/{filename}")
async def dl(filename: str): return FileResponse(path=filename, filename=filename)

@app.get("/")
def root(): return {"status": "PRC AI HUB VER 3 ACTIVE"}
