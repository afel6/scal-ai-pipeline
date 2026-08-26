from google import genai
from google.genai import types
import json

# NOTE (2026-07-05): the report pipeline runs on NVIDIA NIM. The node accepts
# an injected `llm_call` callable — app.py passes its `_nvidia_text_generate`
# helper (signature: llm_call(prompt, system_instruction=None, temperature=0.2))
# so this module never needs to import app.py (no circular import) and stays
# importable standalone. When `llm_call` is None the legacy google-genai client
# path (or the offline fallback text) is used unchanged.
#
# Housekeeping 2026-08-25: the dead LLMInsightGenerator and DashboardArchitectNode
# classes (never instantiated anywhere) were removed; MasterEngineerNode is the
# only node the report pipeline consumes.


class MasterEngineerNode:
    """
    Senior Reservoir Geomechanics & SCAL Engineer.
    Analyzes validated SCAL JSON data and returns geomechanical deductions,
    calculated derivative metrics, risk assessments, and a downstream visualizer directive.
    """
    def __init__(self, api_key: str, llm_call=None):
        self.api_key = api_key
        self.llm_call = llm_call
        self.client = None
        if self.api_key and self.api_key != "DUMMY_KEY":
            self.client = genai.Client(api_key=api_key, http_options={"timeout": 300000})

    def analyze_scal_data(self, validated_json: list) -> str:
        if self.llm_call is None and not self.client:
            # Offline / standard fallback message
            return """### Reservoir Report
Geomechanical Analysis (Offline Mode):
Lithological Deduction: The input petrophysical characteristics suggest a stiff limestone carbonate matrix with variable micro-fracturing.
Derivative Physics Calculations:
- Pore Volume Compressibility (Cp): Estimated around 3.5e-6 psi^-1 under elevated overburden pressure of 3500 psi.
- Entry Pressure (Pd): Estimated at 15.0 psi.
- Irreducible Water Saturation (Swir): Estimated at 18.5%.
Reservoir Risk Profile:
Low overall compressibility indicates a very stiff Eocene/Paleocene Carbonate formation, resulting in 'No Compaction Drive'. Production strategies should rely on early pressure maintenance via water injection.

### Visualizer Directive
Build a dual-plot Streamlit layout displaying Porosity vs. Pressure and Permeability vs. Pressure. Include dynamic sliders for Reservoir Interfacial Tension (IFT) and water/oil fluid densities to dynamically convert lab capillary pressure (Pc) to reservoir height curves using clean math operations."""

        system_instruction = """System Role: Senior Reservoir Geomechanics & SCAL Engineer
Context: You are the lead petroleum engineer for the PRC AI Hub. You receive validated Special Core Analysis (SCAL) and Routine Core Analysis (RCA) JSON data.
Prime Directive: You do NOT just summarize the numbers. You act as an expert consultant for Waha Oil Company. You must interpret what the data actually means for reservoir production, drive mechanisms, and drilling strategy.

Standard Operating Procedure (SOP):
1. Geomechanical Deduction: Always cross-reference Porosity, Permeability, and acoustic/geomechanical properties (like Young's Modulus, Poisson's Ratio) if present in the data. Use these to deduce the exact lithology (e.g., stiff Eocene Carbonate vs. unconsolidated Sandstone) without being explicitly told. If geomechanical parameters are absent, provide empirical estimations and state your assumptions.
2. The Physics Engine: You must calculate missing derivative metrics from the raw JSON:
   - If given overburden pressure and porosity changes, calculate Pore Volume Compressibility ($C_p$).
   - If given Capillary Pressure (Pc) and Brine Saturation, explicitly identify Entry Pressure ($P_d$) and Irreducible Water Saturation ($S_{wir}$).
3. Reservoir Risk Assessment: Translate lab conditions to reservoir reality:
   - If $S_{wir}$ is > 30%, flag a warning for "High Dead Volume" in the transition zone.
   - If $C_p$ is low and Young's Modulus is high, inform the client they have "No Compaction Drive" and must rely on water injection or aquifer support.
4. Handoff to Developer: Conclude your analysis by writing a strict, one-paragraph directive for the downstream Visualizer node, telling it exactly what kind of interactive dashboard to build based on your findings.

Output Format:
You MUST format your response into two distinct sections with clear markdown headings:
### Reservoir Report
[Include your geomechanical deductions, physics engine calculations, and risk assessment here]

### Visualizer Directive
[Include your strict handoff directive to the Dashboard Architect here. State precisely what inputs, sliders, and dynamic recalculations (like converting Pc to reservoir height) are required based on the data.]"""

        prompt = f"Here is the validated SCAL data in JSON format:\n{json.dumps(validated_json, indent=2)}\n\nGenerate your expert geomechanical analysis and visualizer directive."

        if self.llm_call is not None:
            try:
                text = self.llm_call(prompt, system_instruction=system_instruction, temperature=0.2)
                import alerting
                alerting.record_llm_success()
                return text
            except Exception as e:
                import alerting
                alerting.record_llm_failure(str(e))
                if self.client is None:
                    return f"Error running Master Engineer analysis: {str(e)}"
                # NVIDIA path failed but a legacy Gemini client exists — fall through.

        try:
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.2,
                )
            )
            import alerting
            alerting.record_llm_success()
            return response.text
        except Exception as e:
            import alerting
            alerting.record_llm_failure(str(e))
            return f"Error running Master Engineer analysis: {str(e)}"
