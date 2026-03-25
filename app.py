from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
import shutil
import os
import sys

from extractor import ReportExtractor
from physics_engine import PhysicsEngine
from neural_network import SCALNeuralNetwork
from report_generator import ReportGenerator

import numpy as np

app = FastAPI(title="SCAL AI Pipeline")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

print("Initializing Neural Network...")
nn = SCALNeuralNetwork()
# Placeholder dummy training for demo purposes
X_hist = np.random.rand(10, 4)
y_hist = np.random.rand(10)
nn.train(X_hist, y_hist, epochs=10)

@app.post("/api/analyze")
async def analyze_report(file: UploadFile = File(...)):
    file_location = f"temp_{file.filename}"
    with open(file_location, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    try:
        extractor = ReportExtractor(file_location)
        extractor.extract_text()
        raw_data = extractor.parse_scal_data()
        
        scal_data = {k: PhysicsEngine.format_precision(v) for k, v in raw_data.items()}
        
        # Validation
        PhysicsEngine.validate_saturations(scal_data['Swi'], scal_data['Sor'])
        
        # Neural Net Prediction
        predicted_val = nn.predict_endpoint(scal_data)
        
        # Report Generation
        report_name = f"report_{file.filename}.md"
        report_gen = ReportGenerator(scal_data, predicted_val)
        report_gen.generate_markdown(report_name)
        
        return {
            "status": "success",
            "data": scal_data,
            "predictions": {"krw_at_sor": float(f"{predicted_val:.4f}")},
            "report_generated": report_name
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        if os.path.exists(file_location):
            os.remove(file_location)

@app.get("/")
def read_root():
    return {"message": "SCAL AI Pipeline API is running."}
