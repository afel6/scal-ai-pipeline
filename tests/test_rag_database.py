import pytest
import os
import shutil
from rag_database import RAGDatabase

def test_rag_database_ingest_and_query():
    test_db_path = "./test_chroma_db"
    if os.path.exists(test_db_path):
        shutil.rmtree(test_db_path)
    
    db = RAGDatabase(persist_directory=test_db_path)
    
    # Ingest test data
    well_id = "test_well_01"
    scal_data = {"Porosity": 0.25, "Permeability": 150.0}
    report_text = "This is a test report for a carbonate well with 25% porosity."
    
    db.ingest_report(well_id, scal_data, report_text)
    
    # Query test data
    results = db.query_analog_wells(current_porosity=0.25, current_perm=150.0, n_results=1)
    
    assert len(results) == 1
    assert "test_well_01" in results[0]["id"]
    assert results[0]["historical_data"]["porosity"] == 0.25
    assert "test report" in results[0]["context"]

    # Cleanup
    if os.path.exists(test_db_path):
        shutil.rmtree(test_db_path, ignore_errors=True)
