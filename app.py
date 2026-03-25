from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from typing import Optional
import json
import os
import re
import time
import uuid
import pandas as pd

from conversational_core import PRCChatAssistant
from petrophysics_engine import ArchieCalculator
from report_builder import SCALReportBuilder

app = FastAPI(title="PRC Conversational Intelligence Hub")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from dotenv import load_dotenv

# Centralize the API environment directly into memory
load_dotenv()
api_key = os.environ.get('GEMINI_API_KEY', 'DUMMY_KEY')
chat_ai = PRCChatAssistant(api_key=api_key)

# Server-side session memory store — persists entire conversation per browser session
# Structure: { session_id: { "title": str, "created_at": float, "messages": list } }
SESSION_STORE: dict = {}

@app.post("/api/chat")
async def process_chat(
    message: str = Form(""),
    session_id: str = Form(""),
    file: Optional[UploadFile] = None
):
    """
    Primary ingestion node mapping live conversational interactions and processing
    the autonomous structural execution triggers initiated by the LLM.
    """
    try:
        # Resolve or create server-side session memory
        if not session_id or session_id not in SESSION_STORE:
            session_id = session_id or str(uuid.uuid4())
            # Auto-title from first user message (truncated to 40 chars)
            title = (message[:40] + '...') if len(message) > 40 else (message or 'New Study')
            SESSION_STORE[session_id] = {
                "title": title,
                "created_at": time.time(),
                "messages": []
            }
        chat_history = SESSION_STORE[session_id]["messages"]
        
        file_bytes = None
        mime_type = None
        if file:
            raw_bytes = await file.read()
            m_type = file.content_type
            
            # Gemini fundamentally rejects raw Excel binaries. We must aggressively intercept and parse them.
            if m_type in ['application/vnd.ms-excel', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet']:
                import io
                excel_df = pd.read_excel(io.BytesIO(raw_bytes))
                csv_extract = excel_df.to_csv(index=False)
                # Inject the parsed matrix directly into the LLM's cognitive context stream
                message += f"\n\n[USER ATTACHED SPREADSHEET '{file.filename}' TRANSLATED TO ARRAY]:\n{csv_extract}"
            else:
                # If it's a photo or PDF, Gemini handles it natively.
                file_bytes = raw_bytes
                mime_type = m_type
            
        # 1. Talk strictly to the Multimodal Gemini Co-Author
        ai_response = chat_ai.process_chat(chat_history, message, file_bytes, mime_type)
        
        # 2. Stealth Surveillance: Actively intercept JSON triggers hiding inside the response text stream
        match = re.search(r'```json\s*(\{.*?__PRC_REPORT__.*?\})\s*```', ai_response, re.DOTALL)
        
        if match:
            # The AI successfully deduced the math parameters natively from the conversation!
            trigger_data = json.loads(match.group(1))
            
            df = pd.DataFrame(trigger_data['data'])
            
            # Execute backend physics calculations natively seamlessly 
            physics_calc = ArchieCalculator()
            archie_params = physics_calc.compute_archie_parameters(df)
            endpoints = physics_calc.compute_saturation_endpoints(df)
            
            # Construct the absolute elite Matplotlib/Docx render
            well_name = f"Conversational_Study_{int(time.time())}"
            exporter = SCALReportBuilder(well_name=well_name, raw_df=df)
            exporter.build_title_page()
            exporter.add_archies_table(archie_params)
            exporter.add_saturation_endpoints(endpoints)
            exporter.add_ai_conclusion(trigger_data['ai_conclusion'])
            
            docx_path = exporter.export()
            
            # Deliver the generated intercept payload
            return {
                "status": "success",
                "is_report_ready": True,
                "download_url": f"/api/download/{docx_path}",
                "reply": "Excellent parameters! I have confidently processed the arrays, executed Archie's mathematical regressions, and synthesized all our visual assessments into the proprietary PRC Word Document format.\n\nClick the module below to instantly securely extract your finalize study!"
            }
            
        # If no trigger was tripped, it's just a normal conversation reply
        # Strip out any potential isolated formatting artifacts so the user receives a purely clean text stream
        clean_response = re.sub(r'```json.*?```', '', ai_response, flags=re.DOTALL)
        
        # Append both turns to server memory before returning
        chat_history.append({"role": "user", "text": message})
        chat_history.append({"role": "model", "text": clean_response.strip()})
        SESSION_STORE[session_id]["messages"] = chat_history
        
        return {
            "status": "success",
            "is_report_ready": False,
            "session_id": session_id,
            "reply": clean_response.strip()
        }
        
    except Exception as e:
        return {"status": "error", "session_id": session_id, "reply": f"Deep Learning Inference Failure: {str(e)}"}

@app.delete("/api/session/{session_id}")
async def clear_session(session_id: str):
    """Wipe a session from the server store (when user clicks delete)."""
    SESSION_STORE.pop(session_id, None)
    return {"status": "cleared"}

@app.get("/api/sessions")
async def list_sessions():
    """Return all sessions sorted newest-first for the sidebar."""
    sessions = [
        {"id": sid, "title": data["title"], "created_at": data["created_at"]}
        for sid, data in SESSION_STORE.items()
    ]
    return sorted(sessions, key=lambda x: x["created_at"], reverse=True)

@app.get("/api/session/{session_id}")
async def load_session(session_id: str):
    """Load full message history for a session (used when clicking sidebar entry)."""
    if session_id not in SESSION_STORE:
        return {"status": "not_found", "messages": []}
    return {"status": "ok", "messages": SESSION_STORE[session_id]["messages"]}

@app.get("/api/download/{filename}")
async def download_file(filename: str):
    if os.path.exists(filename):
        return FileResponse(path=filename, filename=filename, media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    return {"error": "Target Architecture Not Compiled"}

@app.get("/")
def read_root(): return {"message": "PRC Chat Matrix Array Node Localhost"}
