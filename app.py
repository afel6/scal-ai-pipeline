from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from typing import List
import shutil
import os
import zipfile
import time

from scal_ingestion import SCALBatchIngestion
from petrophysics_engine import ArchieCalculator
from llm_insight_generator import LLMInsightGenerator
from report_builder import SCALReportBuilder

app = FastAPI(title="PRC Enterprise Pipeline - Archie's Parameters")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_key = os.environ.get('GEMINI_API_KEY', 'DUMMY_KEY')
llm_writer = LLMInsightGenerator(api_key=api_key)
physics_calc = ArchieCalculator()

@app.post("/api/batch_process")
async def batch_process(files: List[UploadFile] = File(...)):
    # Unique dynamically generated ID for batch execution runs
    well_name = f"PRC_Batch_Study_{int(time.time())}"
    temp_dir = f"temp_extraction_{well_name}"
    
    try:
        os.makedirs(temp_dir, exist_ok=True)
        
        # Sequentially buffer every file the user selected into the engine
        for file in files:
            file_path = os.path.join(temp_dir, file.filename)
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
                
            # If any selected file happens to be a Zip, extract its payload simultaneously
            if file.filename.endswith('.zip'):
                with zipfile.ZipFile(file_path, 'r') as zip_ref:
                    zip_ref.extractall(temp_dir)
                
        # 1. Ingest Massive Framework (Will swallow all 55 CSV files natively)
        ingestion = SCALBatchIngestion(temp_dir)
        df = ingestion.compile_well_dataframe()
        
        if df.empty:
            return {"status": "error", "message": "Failed to extract valid tabular data from the uploaded files."}
            
        # 2. Mathematical Archie's & Physics Computations
        archie_params = physics_calc.compute_archie_parameters(df)
        endpoints = physics_calc.compute_saturation_endpoints(df)
        
        # 3. Conversational AI Natural Language Writer
        ai_insights = llm_writer.generate_report_insights(archie_params, endpoints)
        
        # 4. Automate Microsoft Word Generation
        exporter = SCALReportBuilder(well_name=well_name)
        exporter.build_title_page()
        exporter.add_archies_table(archie_params)
        exporter.add_saturation_endpoints(endpoints)
        exporter.add_ai_conclusion(ai_insights)
        
        docx_path = exporter.export()
        
        return {
            "status": "success",
            "message": "Archie's simulation complete.",
            "download_url": f"/api/download/{docx_path}",
            "samples_processed": len(df),
            "ai_conclusion": ai_insights
        }
        
    except Exception as e:
        return {"status": "error", "message": f"Archie's Engine Error: {str(e)}"}
    finally:
        # Guarantee massive folder caches are perfectly wiped
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)

@app.get("/api/download/{filename}")
async def download_file(filename: str):
    if os.path.exists(filename):
        return FileResponse(path=filename, filename=filename, media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    return {"error": "File not found."}

@app.get("/")
def read_root():
    return {"message": "PRC Archie's Parameters API is running."}
