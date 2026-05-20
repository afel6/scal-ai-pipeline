# -*- coding: utf-8 -*-
"""
================================================================================
 PRC AI Hub — Universal SCAL & RCA Dashboard Architect
 Deterministic Streamlit/Plotly Dashboard Generator
================================================================================

 This module is the FINAL rendering engine for the PRC AI Hub pipeline.
 It receives validated JSON payloads from the PhysicsGuard router and
 generates fully executable, error-free Streamlit dashboard scripts.

 PRIME DIRECTIVE: Dynamically adapt visualization strategy based on the
 SHAPE of the data. NEVER attempt a line chart with scalar data.

 Data Shape Routing:
   - Arrays/Lists  → Plotly line/scatter charts (Pc, Kr, Overburden)
   - Scalars       → st.metric() KPI cards + Plotly indicator gauges
   - Mixed         → Combined layout with both strategies

 Anti-Crash Guardrails:
   - Every plot wrapped in try/except
   - Missing/null data → st.warning() instead of crash
   - [NOT IN DATA] sentinel handled gracefully
================================================================================
"""

import json
import os
import textwrap
from typing import Any, Dict, List, Optional, Tuple

# ── SCAL Test Type Detection ─────────────────────────────────────────────────

# Mapping of column signatures to test types for auto-detection
_TEST_TYPE_SIGNATURES = {
    "capillary_pressure": [
        {"Water_Saturation_fraction", "Capillary_Pressure_psi"},
        {"Sw", "Pc"},
        {"Sw_fraction", "Pc_psi"},
        {"Hg_Saturation_fraction", "Pc_psia"},
    ],
    "relative_permeability": [
        {"Water_Saturation_fraction", "Krw", "Kro"},
        {"Sw", "Krw", "Kro"},
        {"Sw_fraction", "Krw_fraction", "Kro_fraction"},
    ],
    "overburden_compaction": [
        {"Pressure_psi", "Porosity_percent"},
        {"Pressure_psi", "Porosity_percent", "Air_Permeability_md"},
    ],
    "formation_factor": [
        {"Porosity_percent", "Formation_Factor"},
        {"Porosity_fraction", "FF"},
    ],
    "resistivity_index": [
        {"Water_Saturation_fraction", "Resistivity_Index"},
        {"Sw", "RI"},
    ],
    "geomechanics": [
        {"Youngs_Modulus_gpa", "Poissons_Ratio"},
        {"Youngs_Modulus_psi", "Poissons_Ratio"},
        {"UCS_psi"},
    ],
}


def detect_test_type(data: List[Dict[str, Any]]) -> str:
    """
    Auto-detect the SCAL/RCA test type from JSON column signatures.
    Returns a string key matching _TEST_TYPE_SIGNATURES, or 'generic'.
    """
    if not data:
        return "generic"
    all_keys = set()
    for row in data:
        all_keys.update(row.keys())

    # Score each test type by how many signature columns match
    best_type = "generic"
    best_score = 0
    for test_type, signatures in _TEST_TYPE_SIGNATURES.items():
        for sig in signatures:
            overlap = len(sig & all_keys)
            if overlap >= len(sig) and overlap > best_score:
                best_score = overlap
                best_type = test_type
    return best_type


def classify_data_shape(data: List[Dict[str, Any]]) -> Dict[str, str]:
    """
    Inspect each column in the JSON payload and classify as 'array' (multi-point)
    or 'scalar' (single-point / constant across all rows).

    Returns: {column_name: 'array' | 'scalar' | 'null'}
    """
    if not data:
        return {}

    classification = {}
    all_keys = set()
    for row in data:
        all_keys.update(row.keys())

    for key in all_keys:
        values = [row.get(key) for row in data]
        # Filter out None / [NOT IN DATA]
        valid = [v for v in values if v is not None and v != "[NOT IN DATA]"]

        if len(valid) == 0:
            classification[key] = "null"
        elif len(valid) == 1:
            classification[key] = "scalar"
        else:
            # Check if all values are identical → scalar
            if all(v == valid[0] for v in valid):
                classification[key] = "scalar"
            else:
                classification[key] = "array"

    return classification


# ── COLUMN METADATA (Units, Labels, Physical Bounds for Gauges) ──────────────

_COLUMN_META = {
    # Overburden / RCA
    "Pressure_psi":                      {"label": "Pressure",                   "unit": "psi",         "axis": "x"},
    "Porosity_percent":                  {"label": "Porosity",                   "unit": "%",           "axis": "y",  "range": (0, 40)},
    "Air_Permeability_md":               {"label": "Air Permeability",           "unit": "mD",          "axis": "y"},
    "Klinkenberg_Permeability_md":       {"label": "Klinkenberg Permeability",   "unit": "mD",          "axis": "y"},
    "Grain_Density_gcc":                 {"label": "Grain Density",              "unit": "g/cm³",       "axis": "y",  "range": (2.5, 2.9)},

    # Capillary Pressure
    "Capillary_Pressure_psi":            {"label": "Capillary Pressure",         "unit": "psi",         "axis": "y"},
    "Pc_psia":                           {"label": "Capillary Pressure",         "unit": "psia",        "axis": "y"},
    "Water_Saturation_fraction":         {"label": "Water Saturation (Sw)",      "unit": "fraction",    "axis": "x",  "range": (0, 1)},
    "Hg_Saturation_fraction":            {"label": "Mercury Saturation",         "unit": "fraction",    "axis": "x",  "range": (0, 1)},

    # Relative Permeability
    "Krw":                               {"label": "Krw (Water)",               "unit": "fraction",    "axis": "y",  "range": (0, 1)},
    "Kro":                               {"label": "Kro (Oil)",                 "unit": "fraction",    "axis": "y",  "range": (0, 1)},
    "Krw_fraction":                      {"label": "Krw (Water)",               "unit": "fraction",    "axis": "y",  "range": (0, 1)},
    "Kro_fraction":                      {"label": "Kro (Oil)",                 "unit": "fraction",    "axis": "y",  "range": (0, 1)},

    # Electrical
    "Formation_Factor":                  {"label": "Formation Factor",           "unit": "dimensionless", "axis": "y"},
    "Resistivity_Index":                 {"label": "Resistivity Index",          "unit": "dimensionless", "axis": "y"},

    # Geomechanics
    "Youngs_Modulus_gpa":                {"label": "Young's Modulus",            "unit": "GPa",         "axis": "y",  "range": (0, 80)},
    "Youngs_Modulus_psi":                {"label": "Young's Modulus",            "unit": "psi"},
    "Poissons_Ratio":                    {"label": "Poisson's Ratio",           "unit": "dimensionless","axis": "y",  "range": (0, 0.5)},
    "UCS_psi":                           {"label": "Uniaxial Compressive Strength", "unit": "psi"},
    "Shear_Modulus_gpa":                 {"label": "Shear Modulus (G)",          "unit": "GPa",         "axis": "y",  "range": (0, 40)},

    # Compressibility
    "Pore_Volume_Compressibility_psi_inv": {"label": "Pore Compressibility (Cp)", "unit": "psi⁻¹"},

    # Computed / Internal
    "Deduced_Lithology":                 {"label": "Lithology",                 "unit": "",            "type": "categorical"},
    "Sample_ID":                         {"label": "Sample",                    "unit": "",            "type": "categorical"},
    "Depth_ft":                          {"label": "Depth",                     "unit": "ft"},

    # Wettability
    "Amott_Harvey_Index":                {"label": "Amott-Harvey Index",         "unit": "dimensionless", "range": (-1, 1)},
    "USBM_Index":                        {"label": "USBM Wettability Index",    "unit": "dimensionless", "range": (-1, 1)},

    # Saturation Endpoints
    "Swi":                               {"label": "Irreducible Water Sat.",    "unit": "fraction",    "range": (0, 1)},
    "Sor":                               {"label": "Residual Oil Sat.",         "unit": "fraction",    "range": (0, 1)},
    "Sw_i":                              {"label": "Irreducible Water Sat.",    "unit": "fraction",    "range": (0, 1)},
}


def _get_meta(col: str) -> dict:
    """Return metadata for a column, with safe defaults."""
    return _COLUMN_META.get(col, {"label": col.replace("_", " ").title(), "unit": ""})


# ── CORE DASHBOARD CODE GENERATOR ────────────────────────────────────────────

class UniversalDashboardArchitect:
    """
    Deterministic dashboard generator. No LLM calls — pure Python code emission.
    Receives validated JSON, inspects shape, routes to correct Plotly strategy.
    """

    def __init__(self, physics_audit: Optional[dict] = None):
        """
        Args:
            physics_audit: Optional PhysicsGuard audit dict to embed in the dashboard.
        """
        self.physics_audit = physics_audit

    def generate(self, validated_json: List[Dict[str, Any]],
                 test_type: Optional[str] = None,
                 well_name: str = "PRC Well",
                 output_path: Optional[str] = None) -> str:
        """
        Generate a complete, executable Streamlit dashboard script.

        Args:
            validated_json: The validated SCAL/RCA JSON payload.
            test_type: Optional override. Auto-detected if None.
            well_name: Well name for the dashboard title.
            output_path: If provided, writes the script to this file.

        Returns:
            The complete Python source code as a string.
        """
        if test_type is None:
            test_type = detect_test_type(validated_json)

        shape = classify_data_shape(validated_json)
        json_str = json.dumps(validated_json, indent=2, default=str)

        # Separate columns into curve-plottable and scalar/KPI
        array_cols = [k for k, v in shape.items() if v == "array"]
        scalar_cols = [k for k, v in shape.items() if v == "scalar"]
        null_cols = [k for k, v in shape.items() if v == "null"]

        # Build the dashboard code sections
        code_parts = [
            self._emit_header(well_name, test_type),
            self._emit_data_block(json_str),
            self._emit_physics_audit_block(),
            self._emit_sidebar(test_type),
            self._emit_kpi_section(validated_json, scalar_cols, test_type),
            self._emit_curve_section(validated_json, array_cols, shape, test_type),
            self._emit_null_warnings(null_cols),
            self._emit_data_table(),
            self._emit_footer(),
        ]

        code = "\n\n".join(part for part in code_parts if part)

        if output_path:
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(code)

        return code

    # ── CODE EMISSION METHODS ────────────────────────────────────────────────

    def _emit_header(self, well_name: str, test_type: str) -> str:
        """Emit imports, page config, and styled header banner."""
        title_map = {
            "capillary_pressure":     "Capillary Pressure Analysis",
            "relative_permeability":  "Relative Permeability Analysis",
            "overburden_compaction":   "Overburden Compaction Analysis",
            "formation_factor":       "Formation Factor (Archie) Analysis",
            "resistivity_index":      "Resistivity Index (Archie) Analysis",
            "geomechanics":           "Geomechanical Properties Analysis",
            "generic":                "SCAL / RCA Analysis Dashboard",
        }
        title = title_map.get(test_type, "SCAL / RCA Analysis Dashboard")

        return textwrap.dedent(f'''\
            # -*- coding: utf-8 -*-
            """
            PRC AI Hub — Universal SCAL Dashboard
            Auto-generated by the Dashboard Architect Node
            Test Type: {test_type}
            Well: {well_name}
            """
            import streamlit as st
            import pandas as pd
            import numpy as np
            import plotly.graph_objects as go
            import json

            # ── Page Configuration ───────────────────────────────────────────
            st.set_page_config(
                page_title="{well_name} — {title}",
                page_icon="🛢️",
                layout="wide",
                initial_sidebar_state="expanded",
            )

            # ── Styled Header ────────────────────────────────────────────────
            st.markdown("""
            <div style="
                background: linear-gradient(135deg, #0F4C81 0%, #1a237e 100%);
                padding: 20px 30px;
                border-radius: 12px;
                margin-bottom: 24px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            ">
                <h2 style="color: white; margin: 0; font-family: 'Segoe UI', sans-serif;">
                    🛢️ {well_name} — {title}
                </h2>
                <p style="color: #b0bec5; margin: 6px 0 0 0; font-size: 0.95em;">
                    PRC AI Hub · PhysicsGuard Validated · Auto-Generated Dashboard
                </p>
            </div>
            """, unsafe_allow_html=True)
        ''')

    def _emit_data_block(self, json_str: str) -> str:
        """Emit the raw data loading block."""
        return textwrap.dedent(f'''\
            # ── Load Validated Data ──────────────────────────────────────────
            _RAW_JSON = """{json_str}"""

            try:
                raw_data = json.loads(_RAW_JSON)
                df = pd.DataFrame(raw_data)
            except Exception as e:
                st.error(f"Failed to parse validated JSON: {{e}}")
                st.stop()
        ''')

    def _emit_physics_audit_block(self) -> str:
        """Emit the PhysicsGuard audit banner if available."""
        if not self.physics_audit:
            return ""

        audit = self.physics_audit
        score = audit.get("score", 100)
        grade = audit.get("grade", "A")
        icon = audit.get("icon", "✅")
        summary = audit.get("summary", "")
        violations = audit.get("violations", [])

        # Build violation display strings
        viol_lines = ""
        for v in violations:
            sev = v.get("severity", "HIGH")
            rule = v.get("rule", "")
            detail = v.get("detail", "")
            emoji = "🚫" if sev == "HIGH" else "⚠️"
            viol_lines += f'    st.markdown("- {emoji} **[{sev}] {rule}**: {detail}")\n'

        if score >= 95:
            color = "#10B981"
            bg = "#d1fae5"
        elif score >= 80:
            color = "#f59e0b"
            bg = "#fef3c7"
        else:
            color = "#ef4444"
            bg = "#fee2e2"

        return textwrap.dedent(f'''\
            # ── PhysicsGuard Audit ───────────────────────────────────────────
            st.markdown("""
            <div style="
                background: {bg};
                border-left: 5px solid {color};
                padding: 12px 20px;
                border-radius: 8px;
                margin-bottom: 16px;
            ">
                <span style="font-size: 1.8em;">{icon}</span>
                <strong style="font-size: 1.1em; color: #1a1a2e;">
                    Physics Health Score: {score}% (Grade {grade})
                </strong>
                <br/>
                <span style="color: #555;">{summary}</span>
            </div>
            """, unsafe_allow_html=True)
        ''') + (f"\nwith st.expander('🔍 Detailed Violations ({len(violations)})'):\n{viol_lines}" if violations else "")

    def _emit_sidebar(self, test_type: str) -> str:
        """Emit sidebar with dynamic reservoir parameter sliders."""
        sidebar_code = textwrap.dedent('''\
            # ── Sidebar: Reservoir Parameters ────────────────────────────────
            st.sidebar.header("⚙️ Reservoir Parameters")
        ''')

        if test_type == "capillary_pressure":
            sidebar_code += textwrap.dedent('''\
                res_ift = st.sidebar.slider("Reservoir IFT (mN/m)", 10.0, 80.0, 30.0, 1.0)
                lab_ift = st.sidebar.slider("Lab IFT (mN/m)", 10.0, 480.0, 72.0, 1.0)
                water_density = st.sidebar.slider("Brine Density (g/cm³)", 1.00, 1.20, 1.04, 0.01)
                oil_density = st.sidebar.slider("Oil Density (g/cm³)", 0.70, 0.95, 0.82, 0.01)
                cos_theta_res = st.sidebar.slider("cos(θ) Reservoir", 0.0, 1.0, 0.87, 0.01)
                cos_theta_lab = st.sidebar.slider("cos(θ) Lab", 0.0, 1.0, 1.0, 0.01)

                # Dynamic Pc → Height conversion factor
                delta_rho_lbft3 = (water_density - oil_density) * 62.43  # g/cm³ → lb/ft³
                ift_ratio = (res_ift * cos_theta_res) / (lab_ift * cos_theta_lab) if (lab_ift * cos_theta_lab) > 0 else 1.0
                st.sidebar.markdown(f"""
                **Calculated Constants:**
                - Δρ = {delta_rho_lbft3:.1f} lb/ft³
                - IFT ratio = {ift_ratio:.3f}
                """)
            ''')
        elif test_type == "overburden_compaction":
            sidebar_code += textwrap.dedent('''\
                ref_pressure = st.sidebar.number_input("Reference Pressure (psi)", 0.0, 20000.0, 800.0, 100.0)
                st.sidebar.info("Cp is calculated relative to the baseline pressure within each sample sweep.")
            ''')
        elif test_type == "relative_permeability":
            sidebar_code += textwrap.dedent('''\
                corey_nw = st.sidebar.slider("Corey Exponent (Water)", 1.0, 6.0, 2.5, 0.1)
                corey_no = st.sidebar.slider("Corey Exponent (Oil)", 1.0, 6.0, 2.0, 0.1)
                st.sidebar.info("Adjust Corey exponents to overlay analytical fit curves on the lab data.")
            ''')
        else:
            sidebar_code += textwrap.dedent('''\
                st.sidebar.info("Dashboard auto-configured for this dataset. Physical parameters are displayed below.")
            ''')

        return sidebar_code

    def _emit_kpi_section(self, data: List[Dict[str, Any]],
                          scalar_cols: List[str], test_type: str) -> str:
        """
        THE METRIC STRATEGY: Generate st.metric() KPI cards and Plotly indicator
        gauges for scalar/single-value data.
        """
        if not scalar_cols:
            return ""

        # Filter out internal/computed columns
        skip_cols = {"Deduced_Lithology", "Sample_ID", "_cp_physics_audit"}
        display_cols = [c for c in scalar_cols if c not in skip_cols]

        if not display_cols:
            return ""

        # Build KPI card code
        lines = [
            '# ── KPI Cards (Scalar / Single-Value Data) ──────────────────────',
            'st.subheader("📊 Key Performance Indicators")',
        ]

        # Group into rows of 4 columns
        chunk_size = 4
        for i in range(0, len(display_cols), chunk_size):
            chunk = display_cols[i:i + chunk_size]
            col_names = ", ".join(f"_kpi_col{j}" for j in range(len(chunk)))
            lines.append(f"{col_names} = st.columns({len(chunk)})")

            for j, col in enumerate(chunk):
                meta = _get_meta(col)
                label = meta["label"]
                unit = meta["unit"]
                safe_range = meta.get("range")

                # Get the scalar value
                val = None
                for row in data:
                    v = row.get(col)
                    if v is not None and v != "[NOT IN DATA]":
                        val = v
                        break

                if val is None:
                    lines.append(f'with _kpi_col{j}:')
                    lines.append(f'    st.warning("**{label}**: Not available")')
                    continue

                lines.append(f'with _kpi_col{j}:')

                # If we have a range, emit a gauge
                if safe_range and isinstance(val, (int, float)):
                    lo, hi = safe_range
                    lines.append(f'    try:')
                    lines.append(f'        fig_g = go.Figure(go.Indicator(')
                    lines.append(f'            mode="gauge+number",')
                    lines.append(f'            value={val},')
                    lines.append(f'            title={{"text": "{label} ({unit})"}},')
                    lines.append(f'            gauge={{')
                    lines.append(f'                "axis": {{"range": [{lo}, {hi}]}},')
                    lines.append(f'                "bar": {{"color": "#0F4C81"}},')
                    lines.append(f'                "steps": [')
                    # Tri-color gauge segments
                    third = (hi - lo) / 3
                    lines.append(f'                    {{"range": [{lo}, {lo + third}], "color": "#d4edda"}},')
                    lines.append(f'                    {{"range": [{lo + third}, {lo + 2 * third}], "color": "#fff3cd"}},')
                    lines.append(f'                    {{"range": [{lo + 2 * third}, {hi}], "color": "#f8d7da"}},')
                    lines.append(f'                ],')
                    lines.append(f'            }},')
                    lines.append(f'        ))')
                    lines.append(f'        fig_g.update_layout(height=250, margin=dict(t=50, b=10, l=30, r=30))')
                    lines.append(f'        st.plotly_chart(fig_g, use_container_width=True)')
                    lines.append(f'    except Exception as _e:')
                    lines.append(f'        st.metric("{label}", "{val} {unit}")')
                else:
                    # Simple st.metric for non-gauge values
                    display_val = f"{val} {unit}" if unit else str(val)
                    lines.append(f'    st.metric("{label}", "{display_val}")')

        # Special: Amott-Harvey / USBM gauges with full -1 to 1 range
        for wett_col in ["Amott_Harvey_Index", "USBM_Index"]:
            if wett_col in scalar_cols:
                val = None
                for row in data:
                    v = row.get(wett_col)
                    if v is not None and isinstance(v, (int, float)):
                        val = v
                        break
                if val is not None:
                    meta = _get_meta(wett_col)
                    lines.append(f'\n# Wettability Gauge: {meta["label"]}')
                    lines.append(f'try:')
                    lines.append(f'    fig_wett = go.Figure(go.Indicator(')
                    lines.append(f'        mode="gauge+number+delta",')
                    lines.append(f'        value={val},')
                    lines.append(f'        title={{"text": "{meta["label"]}"}},')
                    lines.append(f'        gauge={{')
                    lines.append(f'            "axis": {{"range": [-1, 1]}},')
                    lines.append(f'            "bar": {{"color": "#0F4C81"}},')
                    lines.append(f'            "steps": [')
                    lines.append(f'                {{"range": [-1, -0.3], "color": "#f8d7da"}},')
                    lines.append(f'                {{"range": [-0.3, 0.3], "color": "#fff3cd"}},')
                    lines.append(f'                {{"range": [0.3, 1.0], "color": "#d4edda"}},')
                    lines.append(f'            ],')
                    lines.append(f'            "threshold": {{')
                    lines.append(f'                "line": {{"color": "red", "width": 3}},')
                    lines.append(f'                "thickness": 0.8,')
                    lines.append(f'                "value": 0,')
                    lines.append(f'            }},')
                    lines.append(f'        }},')
                    lines.append(f'    ))')
                    lines.append(f'    fig_wett.update_layout(height=300, margin=dict(t=60, b=20, l=30, r=30))')
                    lines.append(f'    st.plotly_chart(fig_wett, use_container_width=True)')
                    lines.append(f'except Exception as _e:')
                    lines.append(f'    st.warning(f"Could not render {meta["label"]} gauge: {{_e}}")')

        return "\n".join(lines)

    def _emit_curve_section(self, data: List[Dict[str, Any]],
                            array_cols: List[str], shape: Dict[str, str],
                            test_type: str) -> str:
        """
        THE CURVE STRATEGY: Generate Plotly line/scatter charts for array data.
        """
        if not array_cols:
            return '# No array/curve data detected — skipping curve plots.'

        lines = [
            '# ── Dynamic Curves (Array Data) ─────────────────────────────────',
            'st.subheader("📈 Laboratory Curves")',
        ]

        # ── SPECIALIZED PLOTS based on test type ─────────────────────────────

        if test_type == "relative_permeability":
            lines.append(self._emit_kr_plot(data, array_cols))

        elif test_type == "capillary_pressure":
            lines.append(self._emit_pc_plot(data, array_cols))

        elif test_type == "overburden_compaction":
            lines.append(self._emit_overburden_plot(data, array_cols))

        elif test_type == "formation_factor":
            lines.append(self._emit_ff_plot(data, array_cols))

        elif test_type == "resistivity_index":
            lines.append(self._emit_ri_plot(data, array_cols))

        else:
            # Generic: plot each numeric array column against the first x-axis candidate
            lines.append(self._emit_generic_plots(data, array_cols, shape))

        return "\n".join(lines)

    # ── SPECIALIZED PLOT EMITTERS ────────────────────────────────────────────

    def _emit_kr_plot(self, data: List[Dict[str, Any]], cols: List[str]) -> str:
        """Relative Permeability: Krw & Kro vs Sw on same axes."""
        return textwrap.dedent('''\
            try:
                fig_kr = go.Figure()

                # Detect column names
                sw_col = next((c for c in df.columns if c.lower().startswith("sw") or "water_saturation" in c.lower()), None)
                krw_col = next((c for c in df.columns if "krw" in c.lower()), None)
                kro_col = next((c for c in df.columns if "kro" in c.lower()), None)

                if sw_col and krw_col:
                    sw_vals = pd.to_numeric(df[sw_col], errors='coerce')
                    krw_vals = pd.to_numeric(df[krw_col], errors='coerce')
                    mask = sw_vals.notna() & krw_vals.notna()
                    fig_kr.add_trace(go.Scatter(
                        x=sw_vals[mask], y=krw_vals[mask],
                        mode='lines+markers', name='Krw (Water)',
                        line=dict(color='#2196F3', width=2),
                        marker=dict(size=6),
                    ))

                if sw_col and kro_col:
                    sw_vals = pd.to_numeric(df[sw_col], errors='coerce')
                    kro_vals = pd.to_numeric(df[kro_col], errors='coerce')
                    mask = sw_vals.notna() & kro_vals.notna()
                    fig_kr.add_trace(go.Scatter(
                        x=sw_vals[mask], y=kro_vals[mask],
                        mode='lines+markers', name='Kro (Oil)',
                        line=dict(color='#f44336', width=2),
                        marker=dict(size=6),
                    ))

                    # Overlay Corey fit curves if sliders are available
                    try:
                        sw_fit = np.linspace(float(sw_vals[mask].min()), float(sw_vals[mask].max()), 80)
                        sw_norm = (sw_fit - sw_fit.min()) / (sw_fit.max() - sw_fit.min() + 1e-9)
                        krw_corey = sw_norm ** corey_nw
                        kro_corey = (1 - sw_norm) ** corey_no
                        fig_kr.add_trace(go.Scatter(
                            x=sw_fit, y=krw_corey,
                            mode='lines', name=f'Corey Krw (nw={corey_nw})',
                            line=dict(color='#2196F3', width=1, dash='dash'),
                        ))
                        fig_kr.add_trace(go.Scatter(
                            x=sw_fit, y=kro_corey,
                            mode='lines', name=f'Corey Kro (no={corey_no})',
                            line=dict(color='#f44336', width=1, dash='dash'),
                        ))
                    except Exception:
                        pass  # Corey sliders may not exist for non-kr dashboards

                fig_kr.update_layout(
                    title="Relative Permeability — Krw & Kro vs Sw",
                    xaxis_title="Water Saturation Sw (fraction)",
                    yaxis_title="Relative Permeability (fraction)",
                    xaxis=dict(range=[0, 1]),
                    yaxis=dict(range=[0, 1]),
                    template="plotly_white",
                    height=500,
                    legend=dict(x=0.5, y=-0.15, xanchor='center', orientation='h'),
                )
                st.plotly_chart(fig_kr, use_container_width=True)

            except Exception as _e:
                st.warning(f"⚠️ Could not render Relative Permeability plot: {_e}")
        ''')

    def _emit_pc_plot(self, data: List[Dict[str, Any]], cols: List[str]) -> str:
        """Capillary Pressure: Pc vs Sw with dynamic height conversion."""
        return textwrap.dedent('''\
            try:
                sw_col = next((c for c in df.columns if c.lower().startswith("sw") or "water_saturation" in c.lower() or "hg_saturation" in c.lower()), None)
                pc_col = next((c for c in df.columns if "capillary" in c.lower() or "pc" in c.lower()), None)

                if sw_col and pc_col:
                    sw_vals = pd.to_numeric(df[sw_col], errors='coerce')
                    pc_vals = pd.to_numeric(df[pc_col], errors='coerce')
                    mask = sw_vals.notna() & pc_vals.notna()

                    col_lab, col_res = st.columns(2)

                    with col_lab:
                        fig_pc = go.Figure()
                        fig_pc.add_trace(go.Scatter(
                            x=sw_vals[mask], y=pc_vals[mask],
                            mode='lines+markers', name='Lab Pc',
                            line=dict(color='#0F4C81', width=2),
                            marker=dict(size=5),
                        ))
                        fig_pc.update_layout(
                            title="Lab Capillary Pressure vs Saturation",
                            xaxis_title="Saturation (fraction)",
                            yaxis_title="Capillary Pressure (psi)",
                            template="plotly_white",
                            height=450,
                        )
                        st.plotly_chart(fig_pc, use_container_width=True)

                    with col_res:
                        # Dynamic conversion: Pc → Reservoir Height
                        try:
                            h_ft = pc_vals[mask] * 144 / (delta_rho_lbft3 + 1e-9) * ift_ratio
                            fig_h = go.Figure()
                            fig_h.add_trace(go.Scatter(
                                x=sw_vals[mask], y=h_ft,
                                mode='lines+markers', name='Reservoir Height',
                                line=dict(color='#10B981', width=2),
                                marker=dict(size=5),
                            ))
                            fig_h.update_layout(
                                title="Reservoir Height Above Free Water Level",
                                xaxis_title="Saturation (fraction)",
                                yaxis_title="Height (ft)",
                                template="plotly_white",
                                height=450,
                            )
                            st.plotly_chart(fig_h, use_container_width=True)
                        except Exception as _he:
                            st.warning(f"Could not compute reservoir height: {_he}")
                else:
                    st.warning("⚠️ Missing Sw or Pc column — cannot plot Capillary Pressure.")

            except Exception as _e:
                st.warning(f"⚠️ Could not render Capillary Pressure plot: {_e}")
        ''')

    def _emit_overburden_plot(self, data: List[Dict[str, Any]], cols: List[str]) -> str:
        """Overburden Compaction: Porosity & Permeability vs Pressure (dual axis)."""
        return textwrap.dedent('''\
            try:
                from plotly.subplots import make_subplots

                fig_ob = make_subplots(
                    rows=1, cols=2,
                    subplot_titles=("Porosity vs Overburden Pressure", "Permeability vs Overburden Pressure"),
                    horizontal_spacing=0.12,
                )

                p_col = next((c for c in df.columns if "pressure" in c.lower()), None)
                phi_col = next((c for c in df.columns if "porosity" in c.lower()), None)
                k_col = next((c for c in df.columns if "permeability" in c.lower() and "air" in c.lower()), None)

                if p_col and phi_col:
                    p_vals = pd.to_numeric(df[p_col], errors='coerce')
                    phi_vals = pd.to_numeric(df[phi_col], errors='coerce')
                    mask = p_vals.notna() & phi_vals.notna()
                    fig_ob.add_trace(go.Scatter(
                        x=p_vals[mask], y=phi_vals[mask],
                        mode='lines+markers', name='Porosity (%)',
                        line=dict(color='#0F4C81', width=2),
                        marker=dict(size=6),
                    ), row=1, col=1)
                    fig_ob.update_xaxes(title_text="Pressure (psi)", row=1, col=1)
                    fig_ob.update_yaxes(title_text="Porosity (%)", row=1, col=1)

                if p_col and k_col:
                    p_vals = pd.to_numeric(df[p_col], errors='coerce')
                    k_vals = pd.to_numeric(df[k_col], errors='coerce')
                    mask = p_vals.notna() & k_vals.notna()
                    fig_ob.add_trace(go.Scatter(
                        x=p_vals[mask], y=k_vals[mask],
                        mode='lines+markers', name='Air Perm (mD)',
                        line=dict(color='#10B981', width=2),
                        marker=dict(size=6, symbol='square'),
                    ), row=1, col=2)
                    fig_ob.update_xaxes(title_text="Pressure (psi)", row=1, col=2)
                    fig_ob.update_yaxes(title_text="Air Permeability (mD)", row=1, col=2)

                # Compressibility overlay
                if p_col and phi_col and "Pore_Volume_Compressibility_psi_inv" in df.columns:
                    cp_vals = pd.to_numeric(df["Pore_Volume_Compressibility_psi_inv"], errors='coerce')
                    p_vals = pd.to_numeric(df[p_col], errors='coerce')
                    mask = p_vals.notna() & cp_vals.notna() & (cp_vals > 0)
                    if mask.any():
                        fig_cp = go.Figure()
                        fig_cp.add_trace(go.Scatter(
                            x=p_vals[mask], y=cp_vals[mask],
                            mode='lines+markers', name='Cp (psi⁻¹)',
                            line=dict(color='#f59e0b', width=2),
                            marker=dict(size=6, symbol='diamond'),
                        ))
                        fig_cp.update_layout(
                            title="Pore Volume Compressibility vs Pressure",
                            xaxis_title="Pressure (psi)",
                            yaxis_title="Cp (psi⁻¹)",
                            template="plotly_white",
                            height=400,
                        )
                        st.plotly_chart(fig_cp, use_container_width=True)

                fig_ob.update_layout(
                    template="plotly_white",
                    height=450,
                    showlegend=True,
                    legend=dict(x=0.5, y=-0.15, xanchor='center', orientation='h'),
                )
                st.plotly_chart(fig_ob, use_container_width=True)

            except Exception as _e:
                st.warning(f"⚠️ Could not render Overburden Compaction plot: {_e}")
        ''')

    def _emit_ff_plot(self, data: List[Dict[str, Any]], cols: List[str]) -> str:
        """Formation Factor vs Porosity (log-log)."""
        return textwrap.dedent('''\
            try:
                phi_col = next((c for c in df.columns if "porosity" in c.lower()), None)
                ff_col = next((c for c in df.columns if "formation_factor" in c.lower() or c.lower() == "ff"), None)

                if phi_col and ff_col:
                    phi_vals = pd.to_numeric(df[phi_col], errors='coerce')
                    ff_vals = pd.to_numeric(df[ff_col], errors='coerce')
                    mask = phi_vals.notna() & ff_vals.notna() & (phi_vals > 0) & (ff_vals > 0)

                    fig_ff = go.Figure()
                    fig_ff.add_trace(go.Scatter(
                        x=phi_vals[mask], y=ff_vals[mask],
                        mode='markers', name='Lab FF',
                        marker=dict(size=8, color='#673ab7'),
                    ))
                    fig_ff.update_layout(
                        title="Formation Factor vs Porosity (Log-Log)",
                        xaxis_title="Porosity (%)",
                        yaxis_title="Formation Factor",
                        xaxis_type="log",
                        yaxis_type="log",
                        template="plotly_white",
                        height=450,
                    )
                    st.plotly_chart(fig_ff, use_container_width=True)
                else:
                    st.warning("⚠️ Missing Porosity or Formation Factor columns.")

            except Exception as _e:
                st.warning(f"⚠️ Could not render Formation Factor plot: {_e}")
        ''')

    def _emit_ri_plot(self, data: List[Dict[str, Any]], cols: List[str]) -> str:
        """Resistivity Index vs Sw (log-log)."""
        return textwrap.dedent('''\
            try:
                sw_col = next((c for c in df.columns if c.lower().startswith("sw") or "water_saturation" in c.lower()), None)
                ri_col = next((c for c in df.columns if "resistivity" in c.lower() or c.lower() == "ri"), None)

                if sw_col and ri_col:
                    sw_vals = pd.to_numeric(df[sw_col], errors='coerce')
                    ri_vals = pd.to_numeric(df[ri_col], errors='coerce')
                    mask = sw_vals.notna() & ri_vals.notna() & (sw_vals > 0) & (ri_vals > 0)

                    fig_ri = go.Figure()
                    fig_ri.add_trace(go.Scatter(
                        x=sw_vals[mask], y=ri_vals[mask],
                        mode='markers', name='Lab RI',
                        marker=dict(size=8, color='#ff9800'),
                    ))
                    fig_ri.update_layout(
                        title="Resistivity Index vs Water Saturation (Log-Log)",
                        xaxis_title="Water Saturation Sw (fraction)",
                        yaxis_title="Resistivity Index RI",
                        xaxis_type="log",
                        yaxis_type="log",
                        template="plotly_white",
                        height=450,
                    )
                    st.plotly_chart(fig_ri, use_container_width=True)
                else:
                    st.warning("⚠️ Missing Sw or Resistivity Index columns.")

            except Exception as _e:
                st.warning(f"⚠️ Could not render Resistivity Index plot: {_e}")
        ''')

    def _emit_generic_plots(self, data: List[Dict[str, Any]],
                            array_cols: List[str], shape: Dict[str, str]) -> str:
        """Generic fallback: auto-detect X axis and plot all Y columns."""
        # Heuristic: pick the most likely X column
        x_candidates = ["Pressure_psi", "Water_Saturation_fraction", "Sw",
                        "Depth_ft", "Hg_Saturation_fraction"]
        x_col = None
        for xc in x_candidates:
            if xc in array_cols:
                x_col = xc
                break
        if x_col is None and array_cols:
            x_col = array_cols[0]

        y_cols = [c for c in array_cols if c != x_col]
        skip = {"Deduced_Lithology", "Sample_ID", "_cp_physics_audit"}
        y_cols = [c for c in y_cols if c not in skip]

        if not y_cols:
            return '    st.info("No plottable array data found in the dataset.")'

        x_meta = _get_meta(x_col)

        lines = []
        for yc in y_cols[:6]:  # Max 6 plots to avoid overload
            y_meta = _get_meta(yc)
            safe_yc = yc.replace('"', '\\"')
            safe_xc = x_col.replace('"', '\\"')
            lines.append(textwrap.dedent(f'''\
                try:
                    x_vals = pd.to_numeric(df["{safe_xc}"], errors='coerce')
                    y_vals = pd.to_numeric(df["{safe_yc}"], errors='coerce')
                    mask = x_vals.notna() & y_vals.notna()
                    if mask.any():
                        fig_gen = go.Figure()
                        fig_gen.add_trace(go.Scatter(
                            x=x_vals[mask], y=y_vals[mask],
                            mode='lines+markers', name='{y_meta["label"]}',
                            line=dict(width=2),
                            marker=dict(size=5),
                        ))
                        fig_gen.update_layout(
                            title="{y_meta['label']} vs {x_meta['label']}",
                            xaxis_title="{x_meta['label']} ({x_meta['unit']})",
                            yaxis_title="{y_meta['label']} ({y_meta['unit']})",
                            template="plotly_white",
                            height=400,
                        )
                        st.plotly_chart(fig_gen, use_container_width=True)
                    else:
                        st.warning("⚠️ No valid data points for {y_meta['label']}.")
                except Exception as _e:
                    st.warning(f"⚠️ Could not plot {y_meta['label']}: {{_e}}")
            '''))
        return "\n".join(lines)

    def _emit_null_warnings(self, null_cols: List[str]) -> str:
        """Emit st.warning() for any columns that are entirely null/missing."""
        if not null_cols:
            return ""

        skip = {"_cp_physics_audit"}
        display = [c for c in null_cols if c not in skip]
        if not display:
            return ""

        lines = [
            '# ── Missing Data Warnings ────────────────────────────────────────',
        ]
        for col in display:
            meta = _get_meta(col)
            lines.append(f'st.warning("⚠️ **{meta["label"]}** — No data available in this dataset. '
                         f'This parameter was not extracted from the laboratory report.")')
        return "\n".join(lines)

    def _emit_data_table(self) -> str:
        """Emit expandable raw data table."""
        return textwrap.dedent('''\
            # ── Raw Data Table ───────────────────────────────────────────────
            with st.expander("📋 View Raw Validated Data", expanded=False):
                st.dataframe(df, use_container_width=True, height=400)
                st.download_button(
                    "⬇️ Download as CSV",
                    df.to_csv(index=False).encode('utf-8'),
                    "validated_scal_data.csv",
                    "text/csv",
                )
        ''')

    def _emit_footer(self) -> str:
        """Emit footer with branding."""
        return textwrap.dedent('''\
            # ── Footer ──────────────────────────────────────────────────────
            st.markdown("---")
            st.markdown("""
            <div style="text-align: center; color: #888; font-size: 0.85em; padding: 10px;">
                🛢️ <strong>PRC AI Hub</strong> — Universal SCAL Dashboard Architect<br/>
                PhysicsGuard Validated · Deterministic Code Generation · No LLM Hallucinations
            </div>
            """, unsafe_allow_html=True)
        ''')


# ── CONVENIENCE ENTRY POINT ──────────────────────────────────────────────────

def generate_universal_dashboard(
    validated_json: List[Dict[str, Any]],
    well_name: str = "PRC Well",
    test_type: Optional[str] = None,
    physics_audit: Optional[dict] = None,
    output_path: Optional[str] = None,
) -> str:
    """
    One-call entry point. Generates a complete Streamlit dashboard.

    Args:
        validated_json: Validated SCAL/RCA data.
        well_name: Well name for the title.
        test_type: Override auto-detection.
        physics_audit: PhysicsGuard audit to embed.
        output_path: File path to write the script.

    Returns:
        Complete Python source code as a string.
    """
    architect = UniversalDashboardArchitect(physics_audit=physics_audit)
    return architect.generate(validated_json, test_type=test_type,
                              well_name=well_name, output_path=output_path)


# ── SELF-TEST ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Test with overburden compaction data
    test_data = [
        {"Pressure_psi": 800, "Porosity_percent": 18.5, "Air_Permeability_md": 45.2,
         "Grain_Density_gcc": 2.71, "Deduced_Lithology": "Consolidated Sandstone",
         "Pore_Volume_Compressibility_psi_inv": 0.0},
        {"Pressure_psi": 1200, "Porosity_percent": 18.2, "Air_Permeability_md": 44.8,
         "Grain_Density_gcc": 2.71, "Deduced_Lithology": "Consolidated Sandstone",
         "Pore_Volume_Compressibility_psi_inv": 4.11e-6},
        {"Pressure_psi": 2000, "Porosity_percent": 17.8, "Air_Permeability_md": 42.1,
         "Grain_Density_gcc": 2.71, "Deduced_Lithology": "Consolidated Sandstone",
         "Pore_Volume_Compressibility_psi_inv": 3.27e-6},
        {"Pressure_psi": 3500, "Porosity_percent": 17.1, "Air_Permeability_md": 38.5,
         "Grain_Density_gcc": 2.71, "Deduced_Lithology": "Consolidated Sandstone",
         "Pore_Volume_Compressibility_psi_inv": 4.53e-6},
    ]

    audit = {
        "score": 100, "grade": "A", "icon": "✅",
        "violations": [], "rules_checked": 3,
        "summary": "All values within physical bounds.",
        "footer": "✅ Physics Health Score: 100% | Audit Result: All values within physical bounds.",
    }

    code = generate_universal_dashboard(
        test_data,
        well_name="Well T1-31",
        physics_audit=audit,
        output_path="outputs/app_dashboard.py",
    )
    print(f"Generated {len(code)} characters of Streamlit code.")
    print(f"Test type detected: {detect_test_type(test_data)}")
    print(f"Data shape: {classify_data_shape(test_data)}")
    print("Dashboard saved to outputs/app_dashboard.py")
