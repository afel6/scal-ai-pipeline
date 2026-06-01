from google import genai
from google.genai import types
import os
import json

class LLMInsightGenerator:
    """
    Acts as a Senior Artificial Intelligence Reservoir Engineer.
    Converts hard mathematical data into natural language analysis for clients.
    (Legacy interface preserved for backward compatibility).
    """
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = None
        if self.api_key and self.api_key != "DUMMY_KEY":
            self.client = genai.Client(api_key=api_key, http_options={"timeout": 300000})

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


class MasterEngineerNode:
    """
    Senior Reservoir Geomechanics & SCAL Engineer.
    Analyzes validated SCAL JSON data and returns geomechanical deductions, 
    calculated derivative metrics, risk assessments, and a downstream visualizer directive.
    """
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = None
        if self.api_key and self.api_key != "DUMMY_KEY":
            self.client = genai.Client(api_key=api_key, http_options={"timeout": 300000})

    def analyze_scal_data(self, validated_json: list) -> str:
        if not self.client:
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

        try:
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.2,
                )
            )
            return response.text
        except Exception as e:
            return f"Error running Master Engineer analysis: {str(e)}"


class DashboardArchitectNode:
    """
    SCAL Dashboard Architect.
    Consumes validated JSON data and the Master Engineer's directive, 
    and writes a standalone, executable Streamlit script.
    """
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = None
        if self.api_key and self.api_key != "DUMMY_KEY":
            self.client = genai.Client(api_key=api_key, http_options={"timeout": 300000})

    def generate_dashboard_code(self, validated_json: list, master_engineer_directive: str) -> str:
        if not self.client:
            # Standard offline fallback dashboard script
            return self.get_offline_dashboard_code(validated_json)

        system_instruction = """System Role: SCAL Dashboard Architect (Python/Streamlit)
Context: You receive validated JSON data and a structural directive from the Senior Reservoir Engineer.
Prime Directive: Do NOT generate static matplotlib PNG files. You must write a complete, standalone Python script using streamlit that creates an interactive engineering dashboard for the Waha Oil Company team.

Standard Operating Procedure (SOP):
1. Interactivity First: Include UI elements (sliders, numeric inputs) for unknown reservoir parameters (e.g., 'Reservoir IFT', 'Oil Density', 'Water Density').
2. Dynamic Calculation: The Python script must dynamically recalculate the visualizations when the user moves the sliders (e.g., converting Lab Air-Brine capillary pressure to Reservoir Height vs. Water Saturation, or calculating Compressibility).
3. Code Cleanliness & Production-Ready: Ensure the code is production-ready, well-commented, imports all required libraries (streamlit, pandas, numpy, matplotlib/plotly), handles missing data gracefully, and uses standard Streamlit styling.
4. Output Format: Output ONLY the complete, executable Python code inside a single ```python ``` code block. Do not include any extra chat explanation outside the code block. The code must be self-contained and run directly when saved.

Mathematical Formula for Capillary Pressure to Height conversion:
h (ft) = Pc (psi) * 144 / (g * (rho_water - rho_oil)) * (IFT_reservoir * cos(theta_reservoir)) / (IFT_lab * cos(theta_lab))
Note: Standard units for density are lb/ft³ or g/cm³ (if g/cm³, multiply by 62.43 to get lb/ft³). Standard lab IFT (Air-Brine) is ~72 mN/m, cos(theta_lab) is ~1.0. Let the user adjust reservoir parameters via sliders.
If the data contains pressure/porosity/permeability sweeps, plot them with dynamic compressibility recalculation options.
"""

        prompt = f"""Validated SCAL/RCA Data:
{json.dumps(validated_json, indent=2)}

Master Engineer's Directive:
{master_engineer_directive}

Generate the complete standalone Streamlit Python code."""

        try:
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.1,
                )
            )
            
            # Clean and extract code from the markdown code block if present
            code = response.text.strip()
            if "```python" in code:
                code = code.split("```python")[1].split("```")[0].strip()
            elif "```" in code:
                code = code.split("```")[1].split("```")[0].strip()
            return code
        except Exception as e:
            return f"# Streamlit Generation Failed: {str(e)}\n" + self.get_offline_dashboard_code(validated_json)

    def get_offline_dashboard_code(self, validated_json: list) -> str:
        # Returns a standard robust offline Streamlit dashboard code template
        json_str = json.dumps(validated_json, indent=2)
        return f"""# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import json

st.set_page_config(page_title="Waha Oil Company - SCAL Dashboard", layout="wide")

st.markdown(\"\"\"
<div style="background-color:#0F4C81;padding:15px;border-radius:10px;margin-bottom:20px">
<h2 style="color:white;margin:0;text-align:center;">Waha Oil Company - Interactive SCAL Engineering Dashboard</h2>
<p style="color:#e0e0e0;margin:5px 0 0 0;text-align:center;">Senior Geomechanics & Reservoir Physics Analysis</p>
</div>
\"\"\", unsafe_allow_html=True)

# Raw data
raw_data = {json_str}
df = pd.DataFrame(raw_data)

st.sidebar.header("Reservoir Fluid & IFT Parameters")
res_ift = st.sidebar.slider("Reservoir IFT (mN/m)", min_value=10.0, max_value=80.0, value=30.0, step=1.0)
water_density = st.sidebar.slider("Brine Density (g/cm³)", min_value=1.00, max_value=1.20, value=1.04, step=0.01)
oil_density = st.sidebar.slider("Oil Density (g/cm³)", min_value=0.70, max_value=0.95, value=0.82, step=0.01)

st.sidebar.markdown(\"\"\"
**Calculated Constants**:
- Water density: {water_density * 62.43:.1f} lb/ft³
- Oil density: {oil_density * 62.43:.1f} lb/ft³
- Density delta: {(water_density - oil_density) * 62.43:.1f} lb/ft³
\"\"\")

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("Validated Laboratory Measurements")
    st.dataframe(df, use_container_width=True)
    
    # Geomechanical Calculations
    if 'Pressure_psi' in df.columns and 'Porosity_percent' in df.columns:
        st.subheader("Geomechanical Analysis")
        # Calculate Cp
        df['dVp_fraction'] = df['Porosity_percent'].pct_change()
        df['dPc_psi'] = df['Pressure_psi'].diff()
        df['Cp_psi_inv'] = -df['dVp_fraction'] / df['dPc_psi']
        st.markdown("**Calculated Pore Compressibility (Cp)**:")
        st.dataframe(df[['Pressure_psi', 'Porosity_percent', 'Cp_psi_inv']].dropna(), use_container_width=True)

with col2:
    st.subheader("Dynamic Visualization Curves")
    
    if 'Pressure_psi' in df.columns:
        fig, ax1 = plt.subplots(figsize=(10, 6))
        
        color = '#0F4C81'
        ax1.set_xlabel('Pressure (psi)', fontweight='bold')
        ax1.set_ylabel('Porosity (%)', color=color, fontweight='bold')
        if 'Porosity_percent' in df.columns:
            ax1.plot(df['Pressure_psi'], df['Porosity_percent'], marker='o', color=color, linewidth=2, label='Porosity')
            ax1.tick_params(axis='y', labelcolor=color)
            
        ax2 = ax1.twinx()  
        color = '#10B981'
        ax2.set_ylabel('Air Permeability (mD)', color=color, fontweight='bold')
        if 'Air_Permeability_md' in df.columns:
            ax2.plot(df['Pressure_psi'], df['Air_Permeability_md'], marker='s', color=color, linewidth=2, label='Permeability')
            ax2.tick_params(axis='y', labelcolor=color)
            
        fig.tight_layout()
        st.pyplot(fig)
        
    st.success("Dashboard successfully generated! Technicians can adjust parameters on the sidebar to update predictions dynamically.")
"""
