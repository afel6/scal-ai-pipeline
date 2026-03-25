from google import genai
from google.genai import types

class PRCChatAssistant:
    """
    Advanced LLM Architecture mapping persistent conversational inputs natively 
    into absolute numerical outputs for the PRC architecture.
    """
    def __init__(self, api_key: str):
        self.api_key = api_key
        if self.api_key and self.api_key != "DUMMY_KEY":
            self.client = genai.Client(api_key=api_key)
        
        self.system_instruction = """
        You are a highly intellectual Senior Reservoir Engineer and Petrophysicist actively running the Libyan Petroleum Research Center (PRC) SCAL Artificial Intelligence.
        
        YOUR OBJECTIVE:
        Dynamically interact with petroleum engineers. They will ask you questions or upload laboratory data (CSV text snippets, images of core samples, or visual insights).
        You must actively interview them to retrieve the fundamental mathematical parameters required to solve a Final SCAL Report.
        Specifically, you need numerical data equivalent to calculating Archie's Parameters (Porosity, Permeability, Formation Factor, Resistivity Index, Brine Saturation).
        
        If they upload an image of a core sample, visually execute geological analysis for structural fractures, vugs, or wettability index indications (e.g., oil staining) and actively share your precise visual insights.
        If they paste textual data containing numbers, enthusiastically confirm your comprehension of it.
        
        CRITICAL AUTONOMOUS TRIGGER KEY:
        Once you have confidently collected enough numerical Petrophysical data from the user (i.e. at least 2 or 3 solid sets of Porosity, FF, Sw, and RI arrays, or their variants) to mathematically establish Archie's parameters, you MUST STOP requesting data. 
        You MUST then silently trigger the deep-learning backend structure by exclusively outputting a JSON object matching this exact format:
        
        ```json
        {
            "__PRC_REPORT__": true,
            "data": [
                {"Porosity": 0.22, "Formation_Factor": 18.5, "Brine_Saturation": 1.0, "Resistivity_Index": 1.0},
                {"Porosity": 0.18, "Formation_Factor": 25.4, "Brine_Saturation": 0.3, "Resistivity_Index": 8.4}
            ],
            "ai_conclusion": "Write a brilliant, dense, extremely professional 2-paragraph engineering narrative analyzing the specific wettability, fracture mechanics, and fluid insights you observed with the user during this conversation."
        }
        ```
        WARNING: Do NOT ever use the string `__PRC_REPORT__` internally unless you are executing the instantaneous compilation of the final MS Word Report document.
        """

    def process_chat(self, chat_history: list, new_message: str, file_bytes: bytes = None, mime_type: str = None) -> str:
        if not self.api_key or self.api_key == "DUMMY_KEY":
            return "CRITICAL FAULT: Gemini Environment variables disabled. Connect keys to resume conversational processing."
            
        # Parse persistent conversation mapping natively to the LLM context bounds
        contents = []
        for msg in chat_history:
            role = 'user' if msg['role'] == 'user' else 'model'
            contents.append(types.Content(role=role, parts=[types.Part.from_text(text=msg['text'])]))
            
        # Attach the live user payload seamlessly
        active_parts = []
        if new_message:
            active_parts.append(types.Part.from_text(text=new_message))
            
        # Process multimodal attachments (Lab photos, spread arrays, etc)
        if file_bytes and mime_type:
            active_parts.append(
                types.Part.from_bytes(data=file_bytes, mime_type=mime_type)
            )
            
        if active_parts:
            contents.append(types.Content(role='user', parts=active_parts))
            
        # Switching to 'Flash' architecture to bypass zero-quota limits on newly generated Free API Keys
        response = self.client.models.generate_content(
            model='gemini-2.5-flash', 
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=self.system_instruction,
                temperature=0.3 # Precision focused responses
            )
        )
        
        return response.text
