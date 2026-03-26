import google.generativeai as genai

class PRCChatAssistant:
    def __init__(self, api_key: str):
        self.api_key = api_key
        if self.api_key and self.api_key != "DUMMY_KEY":
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel(
                model_name='gemini-1.5-flash',
                system_instruction="""
                You are 'Hviel', the highly intellectual Senior Reservoir Engineer and Petrophysicist actively running the Libyan Petroleum Research Center (PRC) SCAL Artificial Intelligence.
                
                YOUR IDENTITY & TONE:
                - Your name is Hviel.
                - You speak as a high-level digital consultant, not a generic chatbot.
                - You are mathematically rigorous, professional, and elite.
                
                YOUR OBJECTIVE:
                Dynamically interact with petroleum engineers. They will ask you questions or upload laboratory data (CSV text snippets, images of core samples, or visual insights).
                You must actively interview them to retrieve the fundamental mathematical parameters required to solve a Final SCAL Report.
                Specifically, you need numerical data equivalent to calculating Archie's Parameters (Porosity, Permeability, Formation Factor, Resistivity Index, Brine Saturation).
                
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
                """
            )

    def process_chat(self, chat_history: list, new_message: str, file_bytes: bytes = None, mime_type: str = None) -> str:
        if not self.api_key or self.api_key == "DUMMY_KEY":
            return "CRITICAL FAULT: Gemini Environment variables disabled. Connect keys to resume conversational processing."
            
        history = []
        for msg in chat_history:
            role = 'user' if msg['role'] == 'user' else 'model'
            history.append({"role": role, "parts": [msg['text']]})
            
        chat = self.model.start_chat(history=history)
        
        content = []
        if new_message:
            content.append(new_message)
        if file_bytes and mime_type:
            content.append({'mime_type': mime_type, 'data': file_bytes})
            
        response = chat.send_message(content)
        return response.text
