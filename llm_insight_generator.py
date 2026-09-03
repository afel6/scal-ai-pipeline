import json

# The report pipeline's LLM step goes through the injected `llm_call` callable —
# app.py passes `chat_text_generate`, which routes through the single
# provider-neutral adapter (signature: llm_call(prompt, system_instruction=None,
# temperature=0.2)) — so this module never imports app.py (no circular import)
# and stays importable standalone. With no `llm_call` the offline fallback text
# is returned. The former legacy google-genai fallback client (a second,
# Gemini-hardcoded chat path) was removed in C2: one adapter, one model name.
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
    def __init__(self, api_key: str = "", llm_call=None):
        # `api_key` is accepted for call-site compatibility only; the provider
        # credential lives in the adapter behind `llm_call`.
        self.llm_call = llm_call

    def analyze_scal_data(self, validated_json: list) -> str:
        if self.llm_call is None:
            # Offline: keep the two-section contract the pipeline parses, but carry
            # NO numbers. The former canned text quoted Cp/Pd/Swir values that were
            # placeholders unrelated to `validated_json`, "estimated from the input"
            # — and were written to reservoir_report.md as analysis (D3.1).
            return """### Reservoir Report
OFFLINE MODE: no LLM adapter was supplied, so no analysis was performed on the validated data. \
No geomechanical deductions, derivative physics values or risk assessment are available for this run.

### Visualizer Directive
OFFLINE MODE: no analysis was performed; build the standard dual-plot layout (Porosity vs. Pressure, \
Permeability vs. Pressure) from the validated data only, without derived parameters."""

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

        # Success/failure for /health is recorded by the adapter behind llm_call.
        # A provider failure raises: the pipeline's task handler marks the run
        # "error". It used to return "Error running ..." as the report string,
        # which was written to reservoir_report.md and the run reported success.
        return self.llm_call(prompt, system_instruction=system_instruction, temperature=0.2)
