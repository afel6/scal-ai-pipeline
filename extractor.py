import pdfplumber
import re

class ReportExtractor:
    """
    Extracts text and tables from uploaded PDF/Word well reports.
    """
    def __init__(self, file_path):
        self.file_path = file_path
        self.text = ""

    def extract_text(self):
        # Uses pdfplumber to ingest all pages of the document
        with pdfplumber.open(self.file_path) as pdf:
            for page in pdf.pages:
                extracted = page.extract_text()
                if extracted:
                    self.text += extracted + "\n"
        return self.text

    def parse_scal_data(self):
        """
        Parses Porosity, Permeability, Swi, and Sor.
        Returns a dictionary of the isolated SCAL parameters.
        (Note: In production, Regex patterns should be tailored to exact report layouts)
        """
        # Simulated extraction fallback logic for demonstration
        return {
            'Porosity': 0.2245,
            'Permeability': 142.8900,
            'Swi': 0.1500,
            'Sor': 0.2100
        }
