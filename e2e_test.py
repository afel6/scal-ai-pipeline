import csv
from physics_validator import PhysicsGuard
from rag_database import RAGDatabase
import json

def test_e2e():
    print("Running E2E simulation test with test_scal_data.csv...")
    
    # 1. Read CSV
    try:
        sw = []
        krw = []
        kro = []
        with open("test_scal_data.csv", "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                sw.append(float(row["Sw"]))
                krw.append(float(row["Krw"]))
                kro.append(float(row["Kro"]))
        print(f"Loaded {len(sw)} rows from CSV.")
    except Exception as e:
        print(f"Failed to read CSV: {e}")
        return

    # 2. Physics Guard Validation
    print("Running Physics Guard Validation...")
    guard = PhysicsGuard()
    try:
        guard.validate_kr(sw, krw, kro)
        health_score = guard.generate_health_score()
        print(f"Physics Guard Score: {health_score['score']}")
        print(f"Physics Guard Grade: {health_score['grade']}")
        print(f"Violations: {len(health_score['violations'])}")
        for v in health_score['violations']:
            print(f" - {v['rule']}: {v['detail']}")
    except Exception as e:
        print(f"Physics validation failed: {e}")
        return
        
    # 3. RAG Database
    print("Testing RAG database ingestion and query...")
    try:
        db = RAGDatabase(persist_directory="./chroma_db_e2e_test")
        
        well_id = "test_well_from_csv"
        scal_data = {"Porosity": 0.20, "Permeability": 100.0, "HealthScore": health_score['score']}
        report_text = f"Test well data ingested with {len(sw)} points. Health score was {health_score['score']}."
        
        db.ingest_report(well_id, scal_data, report_text)
        print("Data ingested to RAG successfully.")
        
        results = db.query_analog_wells(current_porosity=0.20, current_perm=100.0, n_results=1)
        if len(results) > 0:
            print("Analog wells query successful. Found:")
            print(json.dumps(results[0], indent=2))
        else:
            print("No results found in query.")
    except Exception as e:
        print(f"RAG database testing failed: {e}")
        return

if __name__ == "__main__":
    run_e2e_test()
