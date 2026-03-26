from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from typing import Optional
import json
import os
import re
import time
import uuid
import sqlite3
import pandas as pd
from dotenv import load_dotenv

from conversational_core import PRCChatAssistant
from petrophysics_engine import ArchieCalculator
from report_builder import SCALReportBuilder

load_dotenv()

app = FastAPI(title="PRC Conversational Intelligence Hub")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_key = os.environ.get('GEMINI_API_KEY', 'DUMMY_KEY')
chat_ai = PRCChatAssistant(api_key=api_key)

# ── Local SQLite Database ──────────────────────────────────────────────────────
DB_PATH = "prc_sessions.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at REAL NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                text TEXT NOT NULL,
                download_url TEXT,
                created_at REAL NOT NULL,
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            )
        """)
        conn.commit()

init_db()

# ── Session Helpers ────────────────────────────────────────────────────────────
def create_session(session_id: str, title: str):
    with get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO sessions (id, title, created_at) VALUES (?, ?, ?)",
            (session_id, title, time.time())
        )
        conn.commit()

def session_exists(session_id: str) -> bool:
    with get_db() as conn:
        row = conn.execute("SELECT id FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return row is not None

def get_messages(session_id: str) -> list:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT role, text, download_url FROM messages WHERE session_id = ? ORDER BY created_at ASC",
            (session_id,)
        ).fetchall()
        return [{"role": r["role"], "text": r["text"], "download_url": r["download_url"]} for r in rows]

def save_message(session_id: str, role: str, text: str, download_url: str = None):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO messages (session_id, role, text, download_url, created_at) VALUES (?, ?, ?, ?, ?)",
            (session_id, role, text, download_url, time.time())
        )
        conn.commit()

def delete_session(session_id: str):
    with get_db() as conn:
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.commit()

def list_all_sessions() -> list:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, title, created_at FROM sessions ORDER BY created_at DESC"
        ).fetchall()
        return [{"id": r["id"], "title": r["title"], "created_at": r["created_at"]} for r in rows]

# ── Routes ─────────────────────────────────────────────────────────────────────
@app.post("/api/chat")
async def process_chat(
    message: str = Form(""),
    session_id: str = Form(""),
    engineer_name: str = Form("PRC Engineering Staff"),
    file: Optional[UploadFile] = None
):
    try:
        # Create new session if needed
        if not session_id or not session_exists(session_id):
            session_id = session_id or str(uuid.uuid4())
            title = (message[:40] + '...') if len(message) > 40 else (message or 'New Study')
            create_session(session_id, title)

        chat_history = get_messages(session_id)

        file_bytes = None
        mime_type = None
        if file:
            raw_bytes = await file.read()
            m_type = file.content_type
            if m_type in ['application/vnd.ms-excel', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet']:
                import io
                excel_df = pd.read_excel(io.BytesIO(raw_bytes))
                total_rows = len(excel_df)
                MAX_ROWS = 300
                # Prepend statistical summary so AI understands the full dataset even if truncated
                summary = excel_df.describe(include='all').to_string()
                if total_rows > MAX_ROWS:
                    excel_df = excel_df.head(MAX_ROWS)
                    truncation_note = f"[NOTE: File has {total_rows} rows. Showing first {MAX_ROWS} rows. Full statistical summary included below.]\n"
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
        # Classify errors into professional, user-facing messages
        if 'RESOURCE_EXHAUSTED' in err or '429' in err:
            friendly = "The AI service is currently at capacity due to high usage. Please wait 60 seconds and try again."
        elif 'API_KEY_INVALID' in err or 'PERMISSION_DENIED' in err or '403' in err:
            friendly = "The AI service is temporarily unavailable. Please contact your system administrator."
        elif 'INVALID_ARGUMENT' in err or '400' in err:
            friendly = "I was unable to process your request. Please try rephrasing your question or re-uploading the file."
        else:
            friendly = "The AI service encountered a temporary issue. Please try again in a moment."
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
