import json
from typing import List, Dict, Any

def validate_scal_data(json_data: List[Dict[str, Any]]) -> dict:
    """
    Validates a list of SCAL data extracted into JSON format by checking physical bounds and sequence logic.
    
    Validation Checks:
    1. Porosity Bounds: Porosity_percent must be between 0 and 100.
    2. Air Permeability Bounds: Air_Permeability_md must be >= 0.
    3. Pressure Sequence: Pressure_psi must be strictly increasing.
    4. Null Handling: Flags any missing (null) data points (Required keys vs Optional keys).
    
    Returns:
        {"status": "success", "data": json_data, "warnings": warnings} if valid.
        {"status": "error", "errors": errors, "warnings": warnings} if invalid.
    """
    errors = []
    warnings = []
    
    if not isinstance(json_data, list):
        return {"status": "error", "errors": ["Input must be a JSON array (list of objects)."], "warnings": []}
        
    previous_pressure = None
    
    # Core keys that we *prefer* for SCAL plotting, but will only warn if missing to prevent data loss
    PREFERRED_KEYS = {"Pressure_psi", "Porosity_percent", "Air_Permeability_md"}
    
    for idx, row in enumerate(json_data):
        sample_num = idx + 1
        pressure = row.get("Pressure_psi")
        porosity = row.get("Porosity_percent")
        perm = row.get("Air_Permeability_md")
        
        pressure_label = f"{pressure} psi" if pressure is not None else "Unknown psi"
        prefix = f"Sample {sample_num}, {pressure_label}"
        
        # 1. Null checking (Required keys are errors, optional keys are warnings)
        for key in ["Pressure_psi", "Porosity_percent"]:
            if row.get(key) is None:
                errors.append(f"{prefix}: Missing data (null) found for required key '{key}'.")
        if row.get("Air_Permeability_md") is None and row.get("Pressure_psi") != 0.0:
            warnings.append(f"{prefix}: Missing data (null) found for key 'Air_Permeability_md'.")
            
        for key, value in row.items():
            if value is None and key not in PREFERRED_KEYS:
                warnings.append(f"{prefix}: Missing data (null) found for key '{key}'.")
                
        # 2. Porosity Bounds (Physical impossibility -> hard error)
        if porosity is not None:
            if not isinstance(porosity, (int, float)) or porosity < 0 or porosity > 100:
                errors.append(f"{prefix}: Porosity value out of bounds (must be 0-100%, got {porosity}).")
                
        # 3. Permeability Bounds (Physical impossibility -> hard error)
        if perm is not None:
            if not isinstance(perm, (int, float)) or perm < 0:
                errors.append(f"{prefix}: Air_Permeability_md cannot be negative (got {perm}).")
                
        # 4. Pressure Sequence (must be strictly increasing within each sweep)
        if pressure is not None:
            if not isinstance(pressure, (int, float)):
                errors.append(f"{prefix}: Pressure_psi must be a number.")
            else:
                if previous_pressure is not None and pressure <= previous_pressure:
                    errors.append(f"{prefix}: Pressure_psi must be strictly increasing (previous={previous_pressure}, current={pressure}).")
                previous_pressure = pressure

    if errors:
        return {
            "status": "error",
            "errors": errors,
            "warnings": warnings
        }

    # ── PHASE 2: CROSS-FIELD PHYSICS DOMAIN BOUNDARIES ──────────────────────
    # These hardcoded checks catch hallucinated values BEFORE the Expert Insight
    # node can write its summary. No LLM prompt — pure Python logic gates.

    for idx, row in enumerate(json_data):
        sample_num = idx + 1
        pressure = row.get("Pressure_psi")
        pressure_label = f"{pressure} psi" if pressure is not None else "Unknown psi"
        prefix = f"Sample {sample_num}, {pressure_label}"

        # 5. Formation Factor must be >= 1.0 (by definition: FF = Ro/Rw >= 1)
        ff = row.get("Formation_Factor")
        if ff is not None and isinstance(ff, (int, float)):
            if ff < 1.0:
                errors.append(f"{prefix}: Formation Factor = {ff} < 1.0 — physically impossible (FF = Ro/Rw ≥ 1.0 by definition).")

        # 6. Water Saturation must be in [0, 1] (fraction) or [0, 100] (percent)
        sw = row.get("Water_Saturation_fraction")
        if sw is not None and isinstance(sw, (int, float)):
            if sw < 0 or sw > 1.0:
                # Check if it's in percent
                if sw > 1.0 and sw <= 100.0:
                    warnings.append(f"{prefix}: Water_Saturation_fraction = {sw} appears to be in percent, not fraction.")
                elif sw > 100.0 or sw < 0:
                    errors.append(f"{prefix}: Water_Saturation_fraction = {sw} outside valid range [0, 1].")

        # 7. Klinkenberg Permeability should be <= Air Permeability (gas slippage correction)
        kl = row.get("Klinkenberg_Permeability_md")
        ka = row.get("Air_Permeability_md")
        if kl is not None and ka is not None and isinstance(kl, (int, float)) and isinstance(ka, (int, float)):
            if kl > ka * 1.05:  # 5% tolerance for measurement uncertainty
                warnings.append(f"{prefix}: Klinkenberg Perm ({kl} mD) > Air Perm ({ka} mD) — Klinkenberg correction should reduce permeability, not increase it.")

        # 8. Pore Volume Compressibility bounds (if present)
        cp = row.get("Pore_Volume_Compressibility_psi_inv")
        if cp is not None and isinstance(cp, (int, float)):
            if cp < 0:
                errors.append(f"{prefix}: Cp = {cp:.2e} psi⁻¹ is negative — pore volume cannot expand under compression.")
            elif cp > 50.0e-6:
                errors.append(f"{prefix}: Cp = {cp:.2e} psi⁻¹ exceeds 50×10⁻⁶ — physically implausible for any reservoir rock.")
            elif cp > 30.0e-6:
                warnings.append(f"{prefix}: Cp = {cp:.2e} psi⁻¹ is very high (>30×10⁻⁶) — only valid for unconsolidated chalk/diatomite.")

        # 9. Resistivity Index must be >= 1.0 (by definition)
        ri = row.get("Resistivity_Index")
        if ri is not None and isinstance(ri, (int, float)):
            if ri < 1.0:
                errors.append(f"{prefix}: Resistivity Index = {ri} < 1.0 — physically impossible (RI = Rt/Ro ≥ 1.0 by definition).")

    # 10. Drainage Physics Validation: Water saturation must not increase as capillary pressure increases
    previous_sw = None
    previous_pc = None
    for idx, row in enumerate(json_data):
        sample_num = idx + 1
        pc = row.get("Capillary_Pressure_psi") or row.get("Pc_psi") or row.get("Pressure_psi")
        sw = row.get("Water_Saturation_fraction") or row.get("Water_Saturation_percent") or row.get("Water_Saturation")
        
        if pc is not None and sw is not None and isinstance(pc, (int, float)) and isinstance(sw, (int, float)):
            sw_frac = sw / 100.0 if sw > 1.0 else sw
            # Reset tracking if a new sweep starts (e.g. pressure drops)
            if previous_pc is not None and pc < previous_pc:
                previous_sw = None
                previous_pc = None
                
            if previous_sw is not None and previous_pc is not None:
                if pc > previous_pc and sw_frac > previous_sw + 0.001:
                    errors.append(
                        f"Sample {sample_num}: Drainage physics violation — water saturation increased "
                        f"({previous_sw:.4f} -> {sw_frac:.4f}) as capillary pressure increased ({previous_pc} -> {pc} psi)."
                    )
            previous_sw = sw_frac
            previous_pc = pc

    if errors:
        return {
            "status": "error",
            "errors": errors,
            "warnings": warnings
        }
        
    return {
        "status": "success",
        "data": json_data,
        "warnings": warnings
    }

if __name__ == "__main__":
    # Test valid case
    test_valid = [
        {
            "Pressure_psi": 800.0,
            "Porosity_percent": 18.5,
            "Air_Permeability_md": 45.2,
            "Klinkenberg_Permeability_md": 44.0,
            "Water_Saturation_fraction": 1.0,
            "Formation_Factor": 20.0
        },
        {
            "Pressure_psi": 1200.0,
            "Porosity_percent": 18.2,
            "Air_Permeability_md": 44.8,
            "Klinkenberg_Permeability_md": 43.5,
            "Water_Saturation_fraction": 0.85,
            "Formation_Factor": 24.3
        }
    ]
    
    # Test invalid case
    test_invalid = [
        {
            "Pressure_psi": 800.0,
            "Porosity_percent": 110.0,  # Invalid: > 100
            "Air_Permeability_md": -5.0,  # Invalid: < 0
            "Klinkenberg_Permeability_md": None,  # Invalid: null
            "Water_Saturation_fraction": 1.0,
            "Formation_Factor": 20.0
        },
        {
            "Pressure_psi": 800.0,  # Invalid: not strictly increasing
            "Porosity_percent": 18.2,
            "Air_Permeability_md": 44.8,
            "Klinkenberg_Permeability_md": 43.5,
            "Water_Saturation_fraction": 0.85,
            "Formation_Factor": 24.3
        }
    ]
    
    print("--- Testing Valid Data ---")
    res_valid = validate_scal_data(test_valid)
    print(json.dumps(res_valid, indent=2))
    
    print("\n--- Testing Invalid Data ---")
    res_invalid = validate_scal_data(test_invalid)
    print(json.dumps(res_invalid, indent=2))
