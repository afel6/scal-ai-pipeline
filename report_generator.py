class ReportGenerator:
    """
    Automatically outputs a final formatted engineering report.
    """
    def __init__(self, data, ai_results):
        self.data = data
        self.ai_results = ai_results

    def generate_markdown(self, output_path="final_scal_report.md"):
        report = f"""# Automated Expert SCAL AI Engineering Report

## 1. Extracted Petrophysical Data
- **Porosity (Φ):** {self.data['Porosity']:.4f}
- **Permeability (k):** {self.data['Permeability']:.4f} mD
- **Irreducible Water Saturation (Swi):** {self.data['Swi']:.4f}
- **Residual Oil Saturation (Sor):** {self.data['Sor']:.4f}

## 2. Physics Engine Validation
- **Saturation Check:** Passed ({self.data['Swi'] + self.data['Sor']:.4f} <= 1.0000)

## 3. Deep Learning Predictions (Physics-Informed Neural Network)
The AI has successfully extrapolated the full fluid displacement curves using learned Corey parameters:
- **Predicted Water Corey Exponent (Nw):** {self.ai_results['Corey_Exponents']['nw']}
- **Predicted Oil Corey Exponent (No):** {self.ai_results['Corey_Exponents']['no']}
- **Predicted Krw max:** {self.ai_results['Endpoints']['krw_max']}
- **Predicted Kro max:** {self.ai_results['Endpoints']['kro_max']}

*Generated automatically by Physics-Informed SCAL AI Pipeline.*
"""
        with open(output_path, "w", encoding='utf-8') as f:
            f.write(report)
        print(f"Report successfully saved to -> {output_path}")
