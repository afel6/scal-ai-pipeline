from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import shutil
import os

from enterprise_ingestion import EnterpriseIngestion
from prc_thermodynamics import PRCThermodynamics
from reservoir_batch_predictor import ReservoirBatchPredictor
from prc_word_exporter import PRCWordExporter

app = FastAPI(title="PRC Enterprise AI Pipeline")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ingestion_engine = EnterpriseIngestion()
batch_predictor = ReservoirBatchPredictor()

@app.post("/api/batch_process")
async def batch_process(file: UploadFile = File(...)):
    file_location = f"temp_{file.filename}"
    with open(file_location, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    try:
        # 1. Macro-Ingestion
        df = ingestion_engine.parse_tabular_data(file_location)
        if df.empty:
            return {"status": "error", "message": "Failed to extract valid tabular data from the report."}
            
        # 2. Physics & Prediction Batch Processing
        batch_results = batch_predictor.process_entire_well(df)
        
        # 3. Microsoft Word Export
        well_name = file.filename.split('.')[0]
        exporter = PRCWordExporter(well_name=well_name)
        exporter.generate_title_page()
        
        # Extract rows for the CCA table
        cca_rows = []
        for i, res in enumerate(batch_results):
            raw = res['raw_data']
            cca_rows.append({
                'id': raw.get('id', f'Sample_{i}'),
                'depth': raw.get('depth', 0.0),
                'porosity': raw.get('porosity', 0.0),
                'permeability': raw.get('permeability', 0.0),
                'grain_density': raw.get('grain_density', 0.0)
            })
        exporter.add_cca_table(cca_rows)
        
        # Add physics plots for the samples
        for res in batch_results[:3]: # Limiting to 3 to prevent extreme MS Word page counts
            sw = res['ai_insights']['sw_array']
            krw = res['ai_insights']['krw_array']
            kro = res['ai_insights']['kro_array']
            exporter.add_scal_physics_plot(sw, krw, kro, res['depth'])
            
        docx_path = exporter.export()
        
        return {
            "status": "success",
            "message": "Batch processing complete.",
            "download_url": f"/api/download/{docx_path}",
            "samples_processed": len(batch_results)
        }
        
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        if os.path.exists(file_location):
            os.remove(file_location)

@app.get("/api/download/{filename}")
async def download_file(filename: str):
    if os.path.exists(filename):
        return FileResponse(path=filename, filename=filename, media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    return {"error": "File not found."}

@app.get("/")
def read_root():
    return {"message": "PRC Enterprise Pipeline Online."}
