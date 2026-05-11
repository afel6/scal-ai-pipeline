import os
import glob
import re
from rag_database import RAGDatabase

def run_ingestion():
    db = RAGDatabase()
    files = glob.glob("*.pdf.md")
    
    for file in files:
        print(f"Ingesting {file}...")
        with open(file, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # extract a basic well_id from the filename
        match = re.search(r'Well[s]?\s*([^,]+)', file, re.IGNORECASE)
        well_id = match.group(1).strip() if match else "UNKNOWN_WELL"
        
        # Regex to extract porosity and permeability from text
        poro_match = re.search(r'porosity[^\d]*(\d+\.?\d*)', content, re.IGNORECASE)
        perm_match = re.search(r'permeability[^\d]*(\d+\.?\d*)', content, re.IGNORECASE)
        
        poro = float(poro_match.group(1)) if poro_match else 0.20 # default 20%
        perm = float(perm_match.group(1)) if perm_match else 100.0 # default 100 mD
        
        scal_data = {
            "source": file, 
            "well_id": well_id,
            "porosity": poro,
            "permeability": perm
        }
        
        db.ingest_report(well_id, scal_data, content)
        print(f"Ingested {file} as {well_id}")
        
if __name__ == "__main__":
    run_ingestion()
