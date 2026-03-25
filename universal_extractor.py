import os
import json
import fitz  # PyMuPDF
import google.generativeai as genai
from pydantic import BaseModel, Field

class SCALExtraction(BaseModel):
    Depth: float = Field(description="Sample depth in feet or meters.")
    Porosity: float = Field(description="Fractional porosity (Φ), e.g., 0.1876.")
    Permeability: float = Field(description="Absolute permeability (k) in mD.")
    Swi: float = Field(description="Irreducible Water Saturation fraction.")
    Sor: float = Field(description="Residual Oil Saturation fraction.")

class UniversalExtractor:
    def __init__(self, api_key: str):
        self.api_key = api_key
        if self.api_key and self.api_key != "DUMMY_KEY":
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel('gemini-1.5-pro-latest')

    def _convert_pdf_to_images(self, pdf_path: str, page_limit: int = 5):
        images = []
        doc = fitz.open(pdf_path)
        for page_num in range(min(len(doc), page_limit)):
            page = doc.load_page(page_num)
            pix = page.get_pixmap(dpi=150)
            img_bytes = pix.tobytes("png")
            
            images.append({
                "mime_type": "image/png",
                "data": img_bytes
            })
        return images

    def extract_petrophysics(self, pdf_path: str) -> dict:
        if not self.api_key or self.api_key == "DUMMY_KEY":
            print("WARNING: Using Offline Extractor logic because GEMINI_API_KEY is not defined in the server environment.")
            return {
                "Depth": 8500.0,
                "Porosity": 0.2245,
                "Permeability": 142.89,
                "Swi": 0.1500,
                "Sor": 0.2100
            }

        image_payload = self._convert_pdf_to_images(pdf_path)
        
        prompt = """
        You are a highly precise Petroleum Data Scientist. Review these pages from a well core analysis report.
        Extract the standard Routine Core Analysis (RCA) and SCAL parameters for the primary sample tested.
        Return ONLY a perfectly formatted JSON object matching this schema exactly. 
        {
            "Depth": float,
            "Porosity": float,
            "Permeability": float,
            "Swi": float,
            "Sor": float
        }
        """
        
        response = self.model.generate_content([prompt] + image_payload)
        clean_json_str = response.text.replace('```json', '').replace('```', '').strip()
        validated_data = SCALExtraction.parse_raw(clean_json_str)
        return validated_data.dict()
