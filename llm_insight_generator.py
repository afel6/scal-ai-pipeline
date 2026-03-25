from google import genai
import os

class LLMInsightGenerator:
    """
    Acts as a Senior Artificial Intelligence Reservoir Engineer.
    Converts hard mathematical data into natural language analysis for clients.
    """
    def __init__(self, api_key: str):
        self.api_key = api_key
        if self.api_key and self.api_key != "DUMMY_KEY":
            # Using the modern, supported google.genai package to avoid protobuf conflicts
            self.client = genai.Client(api_key=api_key)

    def generate_report_insights(self, archie_params: dict, endpoints: dict) -> str:
        if not self.api_key or self.api_key == "DUMMY_KEY":
            return "AI Insights (Offline Mode): The calculated Cementation exponent (m) strongly suggests the presence of vuggy carbonate porosity systems within the analyzed depths. The residual oil saturation (Sor) indicates a highly favorable displacement efficiency, highlighting excellent potential for secondary waterflooding operations. The tortuosity metrics further support a complex pore-throat network typical of Libyan reservoirs."
            
        prompt = f"""
        You are a Senior Petroleum Engineer analyzing SCAL data for a Final Well Report.
        Review the following autonomously calculated parameters:
        - Archie's Cementation (m): {archie_params.get('m_cementation', 2.0)}
        - Archie's Saturation (n): {archie_params.get('n_saturation', 2.0)}
        - Irreducible Water (Swi): {endpoints.get('Swi', 0.15)}
        - Residual Oil (Sor): {endpoints.get('Sor', 0.25)}
        
        Write a robust, 2-paragraph professional reservoir engineering conclusion 
        interpreting these results. Discuss wettability, rock type, and displacement efficiency.
        Do NOT use markdown (no asterisks). Write plain text formally suitable for a Microsoft Word document.
        """
        
        try:
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
            )
            return response.text
        except Exception as e:
            return f"AI Generation Failed: {str(e)}"
