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
        
        # We can extract some basic scal_data or just leave empty or default if not parsed
        scal_data = {"source": file, "well_id": well_id}
        
        db.ingest_report(well_id, scal_data, content)
        print(f"Ingested {file} as {well_id}")
        
if __name__ == "__main__":
    run_ingestion()
