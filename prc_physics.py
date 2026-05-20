# -*- coding: utf-8 -*-
"""
PRC Standalone Physics Engine - Special Core Analysis (SCAL) Calculations
This module provides deterministic, unit-safe petrophysical calculations to prevent LLM mathematical hallucinations.
"""

from typing import List, Dict, Any

def calculate_pore_compressibility(initial_porosity: float, final_porosity: float, pressure_delta: float) -> float:
    """
    Calculate the Pore Volume Compressibility (Cp) of a rock sample.

    Inputs:
        initial_porosity (float): Rock porosity at initial pressure (fraction or percentage).
        final_porosity (float): Rock porosity at elevated pressure (same units as initial_porosity).
        pressure_delta (float): Difference in net confining pressure (psi).

    Formula:
        Cp = (1 / Initial Porosity) * (Porosity Delta / Pressure Delta)
        where Porosity Delta = Initial Porosity - Final Porosity.

    Returns:
        float: Pore volume compressibility in psi^-1.
    """
    if initial_porosity <= 0:
        raise ValueError("Initial porosity must be strictly greater than zero.")
    if pressure_delta <= 0:
        raise ValueError("Pressure delta must be strictly greater than zero.")

    porosity_delta = initial_porosity - final_porosity
    
    # Unit safety check: since both initial_porosity and porosity_delta are in the same unit
    # (either fraction or percentage), the factor of 100 cancels out completely.
    # Cp = (1 / (phi_init/100)) * ((phi_init - phi_final)/100 / dp) = (1 / phi_init) * (dphi / dp)
    cp = (1.0 / initial_porosity) * (porosity_delta / pressure_delta)
    return cp

def calculate_compressibility_sweep(json_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Sequentially processes a list of SCAL measurements representing a pressure sweep,
    calculates Pore Volume Compressibility (Cp) relative to the initial baseline state,
    and deduces the lithology.

    Inputs:
        json_data (list): A list of dictionaries representing SCAL sweep data.

    Returns:
        list: The same list of dictionaries enriched with:
            - 'Pore_Volume_Compressibility_psi_inv' (float or null)
            - 'Deduced_Lithology' (string)
    """
    if not json_data or not isinstance(json_data, list):
        return json_data

    # Active baseline state and previous pressure to detect sweep boundaries
    p0 = None
    phi0 = None
    prev_p = None

    for row in json_data:
        p = row.get("Pressure_psi")
        phi = row.get("Porosity_percent")
        k = row.get("Air_Permeability_md")

        if p is None or phi is None:
            row["Pore_Volume_Compressibility_psi_inv"] = None
            row["Deduced_Lithology"] = "Unknown Matrix"
            continue

        p_val = float(p)
        phi_val = float(phi)

        # Detect start of a new sample sweep:
        # 1. We don't have a baseline yet.
        # 2. Pressure is 0.0 (customary baseline pressure).
        # 3. Pressure decreases compared to the previous row (indicating boundary of next sample sweep).
        if p0 is None or p_val == 0.0 or (prev_p is not None and p_val < prev_p):
            p0 = p_val
            phi0 = phi_val

        prev_p = p_val

        # 1. Compressibility Calculation
        if phi0 <= 0:
            row["Pore_Volume_Compressibility_psi_inv"] = None
            row["Deduced_Lithology"] = "Unknown Matrix"
            continue

        dp = p_val - p0

        if dp <= 0:
            # Baseline or invalid stress delta
            cp = 0.0
            row["Pore_Volume_Compressibility_psi_inv"] = 0.0
        else:
            try:
                cp = calculate_pore_compressibility(phi0, phi_val, dp)
                row["Pore_Volume_Compressibility_psi_inv"] = round(cp, 10)
            except Exception:
                cp = 0.0
                row["Pore_Volume_Compressibility_psi_inv"] = None

        # 2. Lithology Heuristic Deduction
        # Heuristics correlate compressibility (Cp), porosity, and permeability:
        # - Very low compressibility (< 4.0e-6 psi^-1) -> Rigid Carbonate / dense Paleocene matrix
        # - High compressibility (>= 10.0e-6 psi^-1) -> Loose Unconsolidated Sandstone
        # - Intermediate compressibility -> Consolidated Sandstone or moderately rigid matrix
        
        # Check if there is any explicit geomechanics data in the row (e.g. Young's Modulus E)
        youngs_modulus = row.get("Youngs_Modulus_psi") or row.get("Youngs_Modulus_gpa")
        
        if youngs_modulus is not None:
            e_gpa = youngs_modulus if "gpa" in str(row.keys()).lower() else youngs_modulus / 145037.7
            if e_gpa > 25.0:
                lith = "Rigid Carbonate"
            elif e_gpa < 10.0:
                lith = "Unconsolidated Sandstone"
            else:
                lith = "Consolidated Sandstone"
        else:
            # Heuristics using Cp, Porosity, and Permeability
            if cp > 0:
                if cp < 4.0e-6:
                    lith = "Rigid Carbonate"
                elif cp >= 10.0e-6:
                    lith = "Unconsolidated Sandstone"
                else:
                    lith = "Consolidated Sandstone"
            else:
                # Fallback heuristics for the initial baseline row (since Cp is 0.0)
                if phi_val < 15.0 and (k is not None and k < 10.0):
                    lith = "Rigid Carbonate"
                elif phi_val > 25.0 and (k is not None and k > 100.0):
                    lith = "Unconsolidated Sandstone"
                else:
                    lith = "Consolidated Sandstone"

        row["Deduced_Lithology"] = lith

    # ── Physics Guard: validate all computed Cp values ────────────────────
    try:
        from physics_validator import PhysicsGuard
        cp_values = [
            row.get("Pore_Volume_Compressibility_psi_inv")
            for row in json_data
            if row.get("Pore_Volume_Compressibility_psi_inv") is not None
        ]
        if cp_values:
            audit = PhysicsGuard().validate_compressibility(cp_values).generate_health_score()
            if audit["violations"]:
                import logging
                _logger = logging.getLogger("PRC-Hub")
                for v in audit["violations"]:
                    _logger.warning(f"[PhysicsGuard/Cp] {v['severity']}: {v['detail']}")
                # Attach audit to the last row for downstream visibility
                json_data[-1]["_cp_physics_audit"] = audit
    except ImportError:
        pass  # PhysicsGuard not available — skip validation

    return json_data
