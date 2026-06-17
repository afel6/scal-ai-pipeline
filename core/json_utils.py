import json as _json
import logging

_logger = logging.getLogger(__name__)

def salvage_and_clean_json(text_to_parse: str, phase0b_inventory: dict = None) -> list:
    parsed = None
    try:
        parsed = _json.loads(text_to_parse)
    except Exception:
        clean_t = text_to_parse.strip()
        last_brace = clean_t.rfind('}')
        if last_brace != -1:
            if clean_t.startswith("{"):
                for suffix in ["}", "]}", "]} }", "] }"]:
                    try:
                        parsed = _json.loads(clean_t[:last_brace + 1] + suffix)
                        break
                    except Exception:
                        continue
            else:
                try:
                    parsed = _json.loads(clean_t[:last_brace + 1] + ']')
                except Exception:
                    pass

    if parsed is None:
        raise ValueError("Could not parse or salvage valid JSON from LLM extraction response.")

    # Phase 0b: Check for STRUCTURAL_HALT from LLM
    if isinstance(parsed, dict) and "STRUCTURAL_HALT" in parsed:
        halt_msg = parsed["STRUCTURAL_HALT"]
        _logger.error(f"[Phase 0b] STRUCTURAL HALT in background task: {halt_msg}")
        raise ValueError(f"STRUCTURAL_HALT: LLM detected hallucinated reference — {halt_msg}")

    # Phase 0b: Python-side structural validation against ground truth
    if isinstance(parsed, dict) and phase0b_inventory:
        from scal_file_handler import validate_extraction_against_inventory
        violations = validate_extraction_against_inventory(parsed, phase0b_inventory)
        if violations:
            for v in violations:
                _logger.error(f"[Phase 0b BG] {v}")
            raise ValueError(
                f"STRUCTURAL_HALT: Python-side validation caught {len(violations)} "
                f"hallucinated reference(s): {'; '.join(violations[:3])}"
            )

    # Permeability column binding validation
    if isinstance(parsed, dict):
        from scal_file_handler import validate_permeability_column_binding
        perm_violations = validate_permeability_column_binding(parsed)
        if perm_violations:
            for pv in perm_violations:
                _logger.error(f"[Phase 0b BG] {pv}")
            raise ValueError(
                f"PERM_COLUMN_HALT: {len(perm_violations)} permeability "
                f"data-shuffling error(s): {'; '.join(perm_violations[:3])}"
            )

    if isinstance(parsed, dict) and "extracted_data" in parsed:
        _logger.info("[Pipeline] Successfully parsed Phase 0b + mandatory protocols and structured data in background task.")
        overrides = parsed.get("protocol_3_labeled_value_absolute_priority", {}).get("overridden_endpoints", {})
        data_list = parsed.get("extracted_data", [])
        if isinstance(data_list, list) and isinstance(overrides, dict):
            for row in data_list:
                if isinstance(row, dict):
                    for ok, ov in overrides.items():
                        if ov is not None:
                            if ok.lower() == "swi":
                                row["explicit_Swi"] = float(ov)
                            elif ok.lower() == "sor":
                                row["explicit_Sor"] = float(ov)
        return data_list
    return parsed if isinstance(parsed, list) else []

def merge_and_deduplicate_sweeps(samples):
    if not samples or not isinstance(samples, list): return []
    samples = [s for s in samples if isinstance(s, dict)]
    if not samples: return []
    sweeps = []
    current_sweep = []
    last_p = None
    for s in samples:
        p = s.get("Pressure_psi")
        if p is not None:
            if last_p is not None and p <= last_p:
                if current_sweep: sweeps.append(current_sweep)
                current_sweep = []
        current_sweep.append(s)
        last_p = p
    if current_sweep: sweeps.append(current_sweep)

    merged_sweeps = []
    for sweep in sweeps:
        matched = False
        for ms in merged_sweeps:
            if len(sweep) == len(ms):
                match = True
                for i in range(len(sweep)):
                    if sweep[i].get("Pressure_psi") != ms[i].get("Pressure_psi") or sweep[i].get("Porosity_percent") != ms[i].get("Porosity_percent"):
                        match = False
                        break
                if match:
                    for i in range(len(sweep)):
                        for k, v in sweep[i].items():
                            if v is not None and ms[i].get(k) is None:
                                ms[i][k] = v
                    matched = True
                    break
        if not matched:
            merged_sweeps.append(sweep)

    result = []
    for ms in merged_sweeps:
        result.extend(ms)
    return result
