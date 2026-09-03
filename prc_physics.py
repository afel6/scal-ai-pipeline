# -*- coding: utf-8 -*-
"""
PRC Standalone Physics Engine - Special Core Analysis (SCAL) Calculations
This module provides deterministic, unit-safe petrophysical calculations to prevent LLM mathematical hallucinations.
"""

import math
from typing import List, Dict, Any, Optional, Tuple

# Module-top (D3.1): a lazy `except ImportError: pass` skipped the Cp physics
# audit silently whenever the validator could not be imported.
from physics_validator import PhysicsGuard

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
    if initial_porosity <= 0 or initial_porosity > 100:
        raise ValueError("Initial porosity must be strictly greater than zero and less than or equal to 100.")
    if final_porosity <= 0 or final_porosity > 100:
        raise ValueError("Final porosity must be strictly greater than zero and less than or equal to 100.")
    if final_porosity > initial_porosity:
        raise ValueError("Final porosity under elevated pressure cannot exceed initial porosity.")
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
            except ValueError as exc:
                # Non-physical sweep row (porosity rose under stress, >100 %, ...):
                # keep the reason, and do not deduce a lithology from cp=0 as if
                # this were a baseline row.
                row["Pore_Volume_Compressibility_psi_inv"] = None
                row["Cp_error"] = str(exc)
                row["Deduced_Lithology"] = "Unknown Matrix"
                continue

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

    return json_data

def calculate_washburn_radius(pressure_psia: float, contact_angle_deg: float = 140.0, interfacial_tension: float = 480.0) -> float:
    """
    Converts capillary pressure to pore throat radius using the Washburn Equation.
    r = (2 * gamma * |cos(theta)|) / Pc
    
    Inputs:
        pressure_psia (float): Capillary pressure in psia.
        contact_angle_deg (float): Contact angle in degrees (default: 140).
        interfacial_tension (float): Interfacial tension in dynes/cm (default: 480).
        
    Returns:
        float: Pore throat radius in microns, rounded to 4 decimal places.
    """
    if pressure_psia <= 0:
        raise ValueError("Capillary pressure must be positive: the Washburn radius is undefined at Pc <= 0.")
    if contact_angle_deg < 0 or contact_angle_deg > 180:
        raise ValueError("Contact angle must be between 0 and 180 degrees.")
    if interfacial_tension <= 0:
        raise ValueError("Interfacial tension must be strictly greater than zero.")

    # 1 psi = 68947.6 dynes/cm2
    pc_dynes = pressure_psia * 68947.6
    theta_rad = math.radians(contact_angle_deg)
    # Washburn: r in cm, then cm -> microns
    radius_cm = (2.0 * interfacial_tension * abs(math.cos(theta_rad))) / pc_dynes
    return round(radius_cm * 10000.0, 4)
    


class EndpointProvenanceError(ValueError):
    """A Brooks-Corey endpoint had to be substituted on a path that forbids it.

    Raised by the report path so a substituted Swi/Sor can never reach a .docx
    or an LLM prompt disguised as a laboratory measurement.
    """


# Placeholders used ONLY when an endpoint cannot be measured or derived. They are
# always reported with source "substituted"; they are never returned bare.
_SUBSTITUTED_SWI = 0.1
_SUBSTITUTED_SOR = 0.1


def provenance_notice(fit: dict) -> str:
    """Human-readable provenance line for a fit, for prompts and documents.

    Returned text is embedded verbatim in the session transcript, so it reaches
    the LLM context and the generated .docx rather than sitting in a field a
    reader can miss.
    """
    parameters = fit.get("parameters") or {}
    if not parameters:
        return "BROOKS-COREY PROVENANCE: no fit was produced."
    substituted = fit.get("substituted") or []
    defaulted = fit.get("defaulted") or []
    clamped = fit.get("clamped") or []
    warnings = fit.get("warnings") or []
    lines = ["BROOKS-COREY PARAMETER PROVENANCE:"]
    for name, entry in parameters.items():
        lines.append(f"  - {name} = {entry['value']} [{entry['source']}]")
    for w in warnings:
        lines.append("  WARNING: " + w)
    if clamped:
        lines.append(
            "  NOTE: " + ", ".join(clamped) + " were CLAMPED to the physical floor — the "
            "regression slope was non-physical, so these are bounds, not fitted values."
        )
    if substituted:
        lines.append(
            "  WARNING: " + ", ".join(substituted) + " were SUBSTITUTED, not measured "
            "or fitted. Normalised saturation Se is built from Swi and Sor, so every "
            "parameter above inherits any substituted endpoint. Treat the recovery "
            "implications as unverified until the laboratory endpoints are supplied."
        )
    if defaulted:
        lines.append(
            "  NOTE: " + ", ".join(defaulted) + " fell back to textbook defaults "
            "because this dataset had fewer than two usable fit points."
        )
    return "\n".join(lines)


def fit_brooks_corey(json_data: list[dict]) -> dict:
    """
    Fits Brooks-Corey optimization parameters for Pc and Kr data from extracted json data.
    Ensures 100% thread safety by using purely local variables.

    Returns a provenance-carrying structure, never bare floats:
        {"parameters": {name: {"value": float, "source": str}},
         "endpoints_used": {"Swi": float, "Sor": float},
         "substituted": [...], "defaulted": [...], "clamped": [...],
         "warnings": [...]}
    where source is one of measured / fitted / substituted / default / clamped.
    ``warnings`` names lab endpoints that were present but unparsable (a fitted
    stand-in shadows a laboratory value there — the report path refuses them).
    
    Pc = Pd * (Se) ^ (-1/lambda)
    Krw = Krw_max * (Se) ^ nw
    Krnw = Krnw_max * (1 - Se) ^ no
    
    where Se = (Sw - Swi) / (1 - Swi - Sor)
    """
    
    # 1. Filter rows with valid Sw, Pc, or Kr
    valid_rows = []
    for row in json_data:
        # Saturation
        sw = row.get("Water_Saturation_fraction") or row.get("Water_Saturation_percent") or row.get("Water_Saturation")
        if sw is None:
            continue
        sw_frac = float(sw) / 100.0 if float(sw) > 1.0 else float(sw)
        
        row_data = {
            "Sw": sw_frac,
            "Pc": row.get("Capillary_Pressure_psi") or row.get("Pc_psi") or row.get("Pressure_psi"),
            "Krw": row.get("Relative_Permeability_Water") or row.get("Krw"),
            "Krnw": row.get("Relative_Permeability_Oil") or row.get("Kro") or row.get("Krnw") or row.get("Relative_Permeability_Non_Wetting"),
            "explicit_Swi": row.get("explicit_Swi"),
            "explicit_Sor": row.get("explicit_Sor")
        }
        valid_rows.append(row_data)
        
    if not valid_rows:
        return {}
        
    # Check for explicit overrides from Protocol 3
    explicit_swi = None
    explicit_sor = None
    warnings: list[str] = []
    for r in valid_rows:
        if r.get("explicit_Swi") is not None:
            try:
                explicit_swi = float(r["explicit_Swi"])
            except (TypeError, ValueError):
                warnings.append(f"explicit_Swi present but unparsable ({r['explicit_Swi']!r}); "
                                "Swi falls back to the dataset minimum (fitted)")
        if r.get("explicit_Sor") is not None:
            try:
                explicit_sor = float(r["explicit_Sor"])
            except (TypeError, ValueError):
                warnings.append(f"explicit_Sor present but unparsable ({r['explicit_Sor']!r}); "
                                "Sor falls back to the dataset maximum (fitted)")
    warnings = list(dict.fromkeys(warnings))

    # Endpoint Swi and Sor, each tagged with where the number came from:
    #   measured    - reported explicitly by the laboratory (Protocol 3 override)
    #   fitted      - derived from this dataset's own saturation range
    #   substituted - neither was possible; a placeholder stands in and MUST be
    #                 declared, because Se and every fitted parameter inherit it
    sw_vals = [r["Sw"] for r in valid_rows]

    if explicit_swi is not None:
        swi, swi_source = explicit_swi, "measured"
    else:
        swi, swi_source = min(sw_vals), "fitted"
    if not 0.0 <= swi < 1.0:
        swi, swi_source = _SUBSTITUTED_SWI, "substituted"

    if explicit_sor is not None:
        sor, sor_source = explicit_sor, "measured"
    else:
        # Sw_max is usually 1 - Sor
        sor, sor_source = max(0.0, 1.0 - max(sw_vals)), "fitted"
    if swi + sor >= 1.0:
        sor, sor_source = _SUBSTITUTED_SOR, "substituted"
    if swi + sor >= 1.0:
        # Even the placeholder Sor leaves no mobile range: the Swi itself is the
        # non-physical endpoint. It is substituted too (and declared), instead of
        # a silent Se denominator of 0.8 under a "measured" label.
        swi, swi_source = _SUBSTITUTED_SWI, "substituted"
    denom = 1.0 - swi - sor          # > 0 by construction (0.8 when both substituted)

    # Brooks-Corey Fitting
    pc_points = []
    krw_points = []
    krnw_points = []

    for r in valid_rows:
        sw = r["Sw"]
        # Effective saturation Se
        se = (sw - swi) / denom
        se = max(1e-5, min(0.99999, se))
        
        # Pc fit points
        if r["Pc"] is not None and float(r["Pc"]) > 0:
            pc_points.append((se, float(r["Pc"])))
            
        # Krw fit points
        if r["Krw"] is not None and float(r["Krw"]) > 0:
            krw_points.append((se, float(r["Krw"])))
            
        # Krnw fit points
        if r["Krnw"] is not None and float(r["Krnw"]) > 0:
            krnw_points.append((1 - se, float(r["Krnw"])))
            
    # Perform Least-Squares fits. Returns None when no line can be fitted (fewer
    # than two points, or all x identical) — the caller then labels the
    # parameter "default", never "fitted".
    def least_squares_fit(x_arr, y_arr) -> Optional[Tuple[float, float]]:
        n = len(x_arr)
        if n < 2:
            return None
        sum_x = sum(x_arr)
        sum_y = sum(y_arr)
        sum_xx = sum(xi * xi for xi in x_arr)
        sum_xy = sum(xi * yi for xi, yi in zip(x_arr, y_arr))
        denom = n * sum_xx - sum_x * sum_x
        if abs(denom) < 1e-9:
            return None
        slope = (n * sum_xy - sum_x * sum_y) / denom
        intercept = (sum_y - slope * sum_x) / n
        return slope, intercept

    # 1. Capillary Pressure Fit: ln(Pc) = ln(Pd) - (1/lambda) * ln(Se)
    # y = ln(Pc), x = ln(Se)
    pc_fit = least_squares_fit([math.log(p[0]) for p in pc_points],
                               [math.log(p[1]) for p in pc_points])
    if pc_fit is not None:
        slope, intercept = pc_fit
        pd_psi, pd_source = math.exp(intercept), "fitted"
        if slope < 0:
            lambda_val, lambda_source = -1.0 / slope, "fitted"
        else:
            # A non-negative slope is not a Brooks-Corey drainage curve: lambda is
            # a textbook default here, not a fit, and must say so.
            lambda_val, lambda_source = 2.0, "default"
            warnings.append(f"Pc regression slope {slope:.4f} >= 0 is non-physical; "
                            "lambda defaulted to 2.0")
    else:
        lambda_val, pd_psi = 2.0, 1.0
        lambda_source = pd_source = "default"

    # 2. Wetting Phase relative perm fit: ln(Krw) = ln(Krw_max) + nw * ln(Se)
    krw_fit = least_squares_fit([math.log(p[0]) for p in krw_points],
                                [math.log(p[1]) for p in krw_points])
    if krw_fit is not None:
        nw, intercept = krw_fit
        krw_max = math.exp(intercept)
        krw_source = "fitted"
        if nw < 0.5:
            nw, krw_source = 0.5, "clamped"
    else:
        nw = 3.0
        krw_max = 1.0
        krw_source = "default"

    # 3. Non-wetting Phase relative perm fit: ln(Krnw) = ln(Krnw_max) + no * ln(1 - Se)
    krnw_fit = least_squares_fit([math.log(p[0]) for p in krnw_points],
                                 [math.log(p[1]) for p in krnw_points])
    if krnw_fit is not None:
        no, intercept = krnw_fit
        krnw_max = math.exp(intercept)
        krnw_source = "fitted"
        if no < 0.5:
            no, krnw_source = 0.5, "clamped"
    else:
        no = 3.0
        krnw_max = 1.0
        krnw_source = "default"

    parameters = {
        "Swi":      {"value": round(swi, 4),        "source": swi_source},
        "Sor":      {"value": round(sor, 4),        "source": sor_source},
        "Pd_psi":   {"value": round(pd_psi, 4),     "source": pd_source},
        "lambda":   {"value": round(lambda_val, 4), "source": lambda_source},
        "nw":       {"value": round(nw, 4),         "source": krw_source},
        # krw_max/krnw_max come from the same regression's intercept: when the
        # exponent had to be clamped that intercept is not a fit either.
        "krw_max":  {"value": round(krw_max, 4),    "source": krw_source},
        "no":       {"value": round(no, 4),         "source": krnw_source},
        "krnw_max": {"value": round(krnw_max, 4),   "source": krnw_source},
    }
    return {
        "parameters": parameters,
        # The endpoints Se was actually built from — every other parameter above
        # is downstream of these two numbers.
        "endpoints_used": {"Swi": round(swi, 4), "Sor": round(sor, 4)},
        "substituted": sorted(n for n, p in parameters.items()
                              if p["source"] == "substituted"),
        "defaulted": sorted(n for n, p in parameters.items()
                            if p["source"] == "default"),
        "clamped": sorted(n for n, p in parameters.items()
                          if p["source"] == "clamped"),
        "warnings": warnings,
    }

def enrich_json_with_brooks_corey(json_data: list[dict],
                                  allow_substitution: bool = False) -> list[dict]:
    """
    Enriches the extracted SCAL JSON list with Brooks-Corey fits and their provenance.

    This is the report path (POST /api/v1/analyze-scal -> sync_document_generation_task).
    It REFUSES by default when an endpoint had to be substituted, because the result
    would otherwise reach a .docx and an LLM prompt indistinguishable from a
    laboratory measurement. Pass allow_substitution=True only where the caller
    surfaces the notice to the reader.
    """
    fit = fit_brooks_corey(json_data)
    if not fit:
        return json_data

    substituted = fit.get("substituted") or []
    unparsable = [w for w in (fit.get("warnings") or []) if "unparsable" in w]
    if (substituted or unparsable) and not allow_substitution:
        what = ", ".join(substituted) if substituted else "explicit laboratory endpoints"
        raise EndpointProvenanceError(
            "refusing to enrich: " + what + " could not be measured "
            "or fitted from this dataset and would have to be substituted"
            + (" (a lab endpoint was present but unparsable)" if unparsable else "") + ". "
            "Supply explicit laboratory Swi/Sor, or call with allow_substitution=True "
            "and surface the provenance notice to the reader.\n" + provenance_notice(fit)
        )

    notice = provenance_notice(fit)
    for row in json_data:
        for name, entry in fit["parameters"].items():
            row[f"brooks_corey_{name}"] = entry["value"]
            row[f"brooks_corey_{name}_source"] = entry["source"]
        row["brooks_corey_provenance_notice"] = notice

    return json_data

