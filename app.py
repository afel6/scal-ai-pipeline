from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import json
import uuid
import time
import pandas as pd
import re
import sqlite3
from typing import List, Optional

# Local imports
from report_builder import SCALReportBuilder
from physics_engine import ArchieCalculator
from conversational_core import PRCChatAssistant

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize API and Database
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "DUMMY_KEY")
chat_ai = PRCChatAssistant(api_key=GEMINI_API_KEY)

DB_PATH = "chat_history.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS messages
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  session_id TEXT, 
                  role TEXT, 
                  text TEXT, 
                  download_url TEXT,
                  created_at REAL)''')
    conn.commit()
    conn.close()

def save_message(session_id, role, text, download_url=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO messages (session_id, role, text, download_url, created_at) VALUES (?, ?, ?, ?, ?)",
              (session_id, role, text, download_url, time.time()))
    conn.commit()
    conn.close()

def get_messages(session_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT role, text, download_url FROM messages WHERE session_id = ? ORDER BY id ASC", (session_id,))
    rows = c.fetchall()
    conn.close()
    return [{"role": r, "text": t, "download_url": d} for r, t, d in rows]

def session_exists(session_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT 1 FROM messages WHERE session_id = ? LIMIT 1", (session_id,))
    exists = c.fetchone() is not None
    conn.close()
    return exists

def delete_session(session_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()

def list_all_sessions():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT DISTINCT session_id, MIN(text), MIN(created_at) FROM messages GROUP BY session_id ORDER BY MIN(created_at) DESC")
    rows = c.fetchall()
    conn.close()
    return [{"id": r[0], "title": r[1][:30] + "...", "created_at": r[2]} for r in rows if r[0]]

init_db()

@app.post("/api/chat")
async def process_chat(
    message: str = Form(...),
    session_id: Optional[str] = Form(None),
    engineer_name: str = Form("PRC Engineer"),
    file: Optional[UploadFile] = File(None)
):
    if not session_id or session_id == "undefined" or session_id == "":
        session_id = str(uuid.uuid4())

    chat_history = get_messages(session_id)
    
    file_bytes = None
    mime_type = None
    
    try:
        if file:
            raw_bytes = await file.read()
            m_type = file.content_type
            
            if "spreadsheet" in m_type or "excel" in m_type or file.filename.endswith(('.xlsx', '.xls', '.csv')):
                excel_df = pd.read_excel(raw_bytes) if not file.filename.endswith('.csv') else pd.read_csv(pd.io.common.BytesIO(raw_bytes))
                summary = excel_df.describe().to_string()
                MAX_ROWS = 15
                total_rows = len(excel_df)
                truncation_note = ""
                if total_rows > MAX_ROWS:
                    truncation_note = f"[File has {total_rows} rows — only first {MAX_ROWS} included for initial analysis.]\n"
                else:
                    truncation_note = f"[File has {total_rows} rows — full data included.]\n"
                csv_extract = excel_df.to_csv(index=False)
                message += f"\n\n[USER ATTACHED SPREADSHEET '{file.filename}']:\n{truncation_note}\n=== STATISTICAL SUMMARY ===\n{summary}\n\n=== RAW DATA (first {min(total_rows, MAX_ROWS)} rows) ===\n{csv_extract}"
            else:
                file_bytes = raw_bytes
                mime_type = m_type

        ai_response = chat_ai.process_chat(chat_history, message, file_bytes, mime_type)

        # Intercept report trigger
        match = re.search(r'```json\s*(\{.*?__PRC_REPORT__.*?\})\s*```', ai_response, re.DOTALL)
        if match:
            trigger_data = json.loads(match.group(1))
            df = pd.DataFrame(trigger_data['data'])
            physics_calc = ArchieCalculator()
            archie_params = physics_calc.compute_archie_parameters(df)
            endpoints = physics_calc.compute_saturation_endpoints(df)
            well_name = f"Conversational_Study_{int(time.time())}"
            exporter = SCALReportBuilder(well_name=well_name, raw_df=df, engineer_name=engineer_name)
            exporter.build_title_page()
            exporter.add_archies_table(archie_params)
            exporter.add_saturation_endpoints(endpoints)
            exporter.add_ai_conclusion(trigger_data['ai_conclusion'])
            docx_path = exporter.export()

            reply = "I have processed the parameters and generated your PRC Final Report.\n\nClick below to download."
            download_url = f"/api/download/{docx_path}"
            save_message(session_id, "user", message)
            save_message(session_id, "model", reply, download_url)

            return {"status": "success", "is_report_ready": True, "download_url": download_url, "session_id": session_id, "reply": reply}

        clean_response = re.sub(r'```json.*?```', '', ai_response, flags=re.DOTALL).strip()
        save_message(session_id, "user", message)
        save_message(session_id, "model", clean_response)
        return {"status": "success", "is_report_ready": False, "session_id": session_id, "reply": clean_response}

    except Exception as e:
        err = str(e)
        if 'RESOURCE_EXHAUSTED' in err or '429' in err:
            friendly = "The AI service is currently at capacity due to high usage. Please wait 3 minutes and try again."
        elif 'API_KEY_INVALID' in err or 'PERMISSION_DENIED' in err or '403' in err:
            friendly = "The AI service is temporarily unavailable. Please contact your system administrator."
        elif 'INVALID_ARGUMENT' in err or '400' in err:
            friendly = "I was unable to process your request. Please try rephrasing your question or re-uploading the file."
        else:
            friendly = "The AI service encountered a temporary issue. Please try again in a moment."
        friendly += f" (Diag Ver 2: {err[:100]})"
        return {"status": "error", "session_id": session_id, "reply": friendly, "is_error": True}

@app.get("/api/sessions")
async def list_sessions():
    return list_all_sessions()

@app.get("/api/session/{session_id}")
async def load_session(session_id: str):
    if not session_exists(session_id):
        return {"status": "not_found", "messages": []}
    return {"status": "ok", "messages": get_messages(session_id)}

@app.delete("/api/session/{session_id}")
async def clear_session(session_id: str):
    delete_session(session_id)
    return {"status": "cleared"}

@app.get("/api/download/{filename}")
async def download_file(filename: str):
    if os.path.exists(filename):
        return FileResponse(path=filename, filename=filename, media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    return {"error": "File not found"}

@app.get("/")
def read_root():
    return {"message": "PRC Chat Matrix — SQLite Local Database Active"}
