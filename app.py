from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import shutil
import os

from universal_extractor import UniversalExtractor
from physics_validator import PhysicsValidator
from rag_database import RAGDatabase
from predictive_model import PredictiveModel

app = FastAPI(title="SCAL AI Pipeline - Web Edition")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

print("Initializing Advanced Architecture (RAG, PINN, Multimodal Vision)...")
api_key = os.environ.get('GEMINI_API_KEY', 'DUMMY_KEY')
extractor = UniversalExtractor(api_key=api_key)
rag_db = RAGDatabase(persist_directory="./chroma_db")
pinn_model = PredictiveModel()

class ManualData(BaseModel):
    Porosity: float
    Permeability: float
    Swi: float
    Sor: float

@app.post("/api/simulate")
async def simulate_manual_data(data: ManualData):
    try:
        raw_data = data.dict()
        clean_data = PhysicsValidator.validate_core_physics(raw_data)
        
        analog_wells = rag_db.query_analog_wells(
            current_porosity=clean_data['Porosity'], 
            current_perm=clean_data['Permeability']
        )
        
        pinn_model.train_on_rag_history(analog_wells)
        ai_results = pinn_model.simulate_displacement_curve(
            swi=clean_data['Swi'], 
            sor=clean_data['Sor']
        )
        
        rag_db.ingest_report(
            well_id="manual_entry", 
            scal_data=clean_data, 
            report_text="Manual petroleum engineer data entry for simulation."
        )
        
        curve_data = []
        for i in range(len(ai_results['sw_array'])):
            curve_data.append({
                "Sw": float(f"{ai_results['sw_array'][i]:.4f}"),
                "krw": float(f"{ai_results['krw_array'][i]:.4f}"),
                "kro": float(f"{ai_results['kro_array'][i]:.4f}")
            })
            
        return {
            "status": "success",
            "data": clean_data,
            "ai_insights": {
                "Corey_Exponents": ai_results['exponents'],
                "Endpoints": ai_results['endpoints'],
                "Curve_Data": curve_data
            }
        }
    except Exception as e:
        return {"status": "error", "message": f"Simulation Error: {str(e)}"}

@app.post("/api/analyze")
async def analyze_report(file: UploadFile = File(...)):
    file_location = f"temp_{file.filename}"
    with open(file_location, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    try:
        raw_data = extractor.extract_petrophysics(file_location)
        clean_data = PhysicsValidator.validate_core_physics(raw_data)
        
        analog_wells = rag_db.query_analog_wells(
            current_porosity=clean_data['Porosity'], 
            current_perm=clean_data['Permeability']
        )
        
        pinn_model.train_on_rag_history(analog_wells)
        ai_results = pinn_model.simulate_displacement_curve(
            swi=clean_data['Swi'], 
            sor=clean_data['Sor']
        )
        
        rag_db.ingest_report(
            well_id=file.filename.split('.')[0], 
            scal_data=clean_data, 
            report_text="Processed core analysis metric sample."
        )
        
        curve_data = []
        for i in range(len(ai_results['sw_array'])):
            curve_data.append({
                "Sw": float(f"{ai_results['sw_array'][i]:.4f}"),
                "krw": float(f"{ai_results['krw_array'][i]:.4f}"),
                "kro": float(f"{ai_results['kro_array'][i]:.4f}")
            })
            
        return {
            "status": "success",
            "data": clean_data,
            "ai_insights": {
                "Corey_Exponents": ai_results['exponents'],
                "Endpoints": ai_results['endpoints'],
                "Curve_Data": curve_data
            }
        }
    except Exception as e:
        return {"status": "error", "message": f"Pipeline Error: {str(e)}"}
    finally:
        if os.path.exists(file_location):
            os.remove(file_location)

@app.get("/")
def read_root():
    return {"message": "Expert Multimodal SCAL API is running."}
