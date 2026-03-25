import sys
import os
import numpy as np
from extractor import ReportExtractor
from physics_engine import PhysicsEngine
from neural_network import SCALNeuralNetwork
from report_generator import ReportGenerator

def main(pdf_path):
    print("\n--- INITIATING SCAL AI PIPELINE ---")
    
    if not os.path.exists(pdf_path):
        print(f"[!] Error: File '{pdf_path}' not found.")
        sys.exit(1)
        
    # 1. Data Ingestion
    print(f"[*] Extracting data from {pdf_path}...")
    extractor = ReportExtractor(pdf_path)
    extractor.extract_text()
    raw_data = extractor.parse_scal_data()
    
    # 2. Data Processing (Apply 4 decimal precision)
    scal_data = {k: PhysicsEngine.format_precision(v) for k, v in raw_data.items()}
        
    # 3. Physics Validation
    print("[*] Running Physics Engine constraints...")
    try:
        PhysicsEngine.validate_saturations(scal_data['Swi'], scal_data['Sor'])
        print("    -> Validation PASSED.")
    except ValueError as e:
        print(f"    -> CRITICAL ERROR: {e}")
        sys.exit(1)

    # 4. Machine Learning Inference
    print("[*] Initializing TensorFlow/Keras Neural Network...")
    nn = SCALNeuralNetwork()
    
    # (Simulated training step using dummy random noise for local standalone execution)
    X_hist = np.random.rand(10, 4)
    y_hist = np.random.rand(10)
    nn.train(X_hist, y_hist, epochs=10)
    
    print("[*] Predicting target Relative Permeability...")
    predicted_val = nn.predict_endpoint(scal_data)
    
    # 5. Output Report
    print("[*] Compiling final report...")
    report_gen = ReportGenerator(scal_data, predicted_val)
    report_gen.generate_markdown()
    
    print("--- PIPELINE EXECUTION COMPLETE ---\n")

if __name__ == "__main__":
    # To run locally: python main.py <path_to_pdf_report>
    input_file = "sample_report.pdf" if len(sys.argv) < 2 else sys.argv[1]
    main(input_file)
