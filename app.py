from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from typing import Optional
import json
import os
import re
import time
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

# Centralize the API environment directly into memory
api_key = os.environ.get('GEMINI_API_KEY', 'DUMMY_KEY')
chat_ai = PRCChatAssistant(api_key=api_key)

@app.post("/api/chat")
async def process_chat(
    history: str = Form(...), 
    message: str = Form(""), 
    file: Optional[UploadFile] = None
):
    """
    Primary ingestion node mapping live conversational interactions and processing
    the autonomous structural execution triggers initiated by the LLM.
    """
    try:
        chat_history = json.loads(history)
        
        file_bytes = None
        mime_type = None
        if file:
            file_bytes = await file.read()
            mime_type = file.content_type
            
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
        
        return {
            "status": "success",
            "is_report_ready": False,
            "reply": clean_response.strip()
        }
        
    except Exception as e:
        return {"status": "error", "reply": f"Deep Learning Inference Failure: {str(e)}"}

@app.get("/api/download/{filename}")
async def download_file(filename: str):
    if os.path.exists(filename):
        return FileResponse(path=filename, filename=filename, media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    return {"error": "Target Architecture Not Compiled"}

@app.get("/")
def read_root(): return {"message": "PRC Chat Matrix Array Node Localhost"}
