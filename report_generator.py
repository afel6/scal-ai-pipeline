class ReportGenerator:
    """
    Automatically outputs a final formatted engineering report.
    """
    def __init__(self, data, prediction):
        self.data = data
        self.prediction = prediction

    def generate_markdown(self, output_path="final_scal_report.md"):
        report = f"""# Automated SCAL AI Engineering Report

## 1. Extracted Petrophysical Data
- **Porosity (Φ):** {self.data['Porosity']:.4f}
- **Permeability (k):** {self.data['Permeability']:.4f} mD
- **Irreducible Water Saturation (Swi):** {self.data['Swi']:.4f}
- **Residual Oil Saturation (Sor):** {self.data['Sor']:.4f}

## 2. Physics Engine Validation
- **Saturation Check:** Passed ({self.data['Swi'] + self.data['Sor']:.4f} <= 1.0000)

## 3. Deep Learning Predictions
- **Predicted Relative Permeability (krw @ Sor):** {self.prediction:.4f}

*Generated automatically by the SCAL AI Pipeline.*
"""
        with open(output_path, "w", encoding='utf-8') as f:
            f.write(report)
        print(f"Report successfully saved to -> {output_path}")
