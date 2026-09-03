import os
import re
from file_reader import read_file, to_prompt_string

def grade_ai_response(filepath, ai_response_text):
    data = read_file(filepath)
    file_text, _ = to_prompt_string(data)
    ground_truth = extract_ground_truth(data)
    checks = run_checks(ai_response_text, ground_truth)
    report = build_report(checks, ground_truth, filepath)

    return {
        "score": report["score"],
        "grade": report["grade"],
        "report": report["text"],
        "checks": checks,
        "ground_truth": ground_truth
    }

def extract_ground_truth(data):
    truth = {
        "well":        None,
        "company":     None,
        "samples":     [],
        "all_values":  {},
    }
    file_type = data.get("type")
    if file_type == "excel":
        all_labeled = {}
        for sheet_name, sheet in data.get("sheets", {}).items():
            labeled = sheet.get("labeled_values", {})
            columns = sheet.get("numeric_columns", {})
            for k, v in labeled.items():
                all_labeled[f"{sheet_name}::{k}"] = v
                if any(x in k.lower() for x in ["well", "well no", "well #"]):
                    if isinstance(v, str) and len(v) < 20:
                        truth["well"] = v
                if "company" in k.lower():
                    if isinstance(v, str):
                        truth["company"] = v
            sample_data = {"sheet": sheet_name, "labeled": labeled, "columns": {}}
            for col_name, col_info in columns.items():
                sample_data["columns"][col_name] = {
                    "first": col_info["first"],
                    "last":  col_info["last"],
                    "min":   col_info["min"],
                    "max":   col_info["max"],
                    "count": col_info["count"],
                }
            truth["samples"].append(sample_data)
        truth["all_values"] = all_labeled
    return truth

def run_checks(ai_text, ground_truth):
    ai_lower = ai_text.lower()
    checks = []
    well = ground_truth.get("well")
    if well:
        found = well.lower() in ai_lower
        checks.append({
            "rule": "Well name",
            "expected": well,
            "found_in_response": found,
            "status": "PASS" if found else "FAIL",
            "note": f"AI should report well as '{well}'"
        })
    company = ground_truth.get("company")
    if company:
        found = company.lower() in ai_lower
        checks.append({
            "rule": "Company name",
            "expected": company,
            "found_in_response": found,
            "status": "PASS" if found else "FAIL",
            "note": f"AI should report company as '{company}'"
        })
    sample_sheets = [
        s["sheet"] for s in ground_truth["samples"]
        if any(kw in s["sheet"].lower() for kw in ["sample", "no.", "s-"])
    ]
    missing_samples = []
    for s in sample_sheets:
        core = s.lower().replace("sample", "").replace("-", "").replace(" ", "").replace("no.", "")
        if core and core not in ai_lower.replace(" ", "").replace("-", ""):
            missing_samples.append(s)
    checks.append({
        "rule": "All samples reported",
        "expected": sample_sheets,
        "missing": missing_samples,
        "status": "PASS" if not missing_samples else "FAIL",
        "note": f"Missing: {missing_samples}" if missing_samples else "All samples found"
    })
    numeric_checks = []
    for sample in ground_truth["samples"]:
        for k, v in sample["labeled"].items():
            if not isinstance(v, float):
                continue
            k_lower = k.lower()
            is_key = any(kw in k_lower for kw in [
                "threshold", "porosity", "permeability", "pore vol",
                "sor lab", "sor t.c", "kl", "initial kw", "entry"
            ])
            if not is_key:
                continue
            val_found = value_in_text(ai_text, v, tolerance=0.05)
            numeric_checks.append({
                "field": f"{sample['sheet']} — {k}",
                "expected": v,
                "status": "PASS" if val_found else "FAIL"
            })
    checks.append({
        "rule": "Key numeric values",
        "sub_checks": numeric_checks,
        "status": "PASS" if all(c["status"] == "PASS" for c in numeric_checks)
                  else "PARTIAL" if any(c["status"] == "PASS" for c in numeric_checks)
                  else "FAIL"
    })
    # word-boundary regexes: a bare substring check for "well a" falsely
    # matched normal prose like "as well as" / "well above" and forced the
    # system prompt to ban ordinary English. \b keeps only true name matches
    # (e.g. "Well A", "Well B") failing the check.
    hallucinated_name_patterns = [r"\bpcy4q\b", r"\bprovisional well\b",
                                  r"\bwell a\b", r"\bwell b\b",
                                  r"\bunknown well\b", r"\bsample well\b"]
    found_hallucination = [p.replace(r"\b", "") for p in hallucinated_name_patterns
                           if re.search(p, ai_lower)]
    checks.append({
        "rule": "No hallucinated well name",
        "status": "PASS" if not found_hallucination else "FAIL",
        "note": f"Hallucinated: {found_hallucination}" if found_hallucination else "Clean"
    })
    if any("imbibition" in s["sheet"].lower() or "imb" in s["sheet"].lower()
           for s in ground_truth["samples"]):
        false_violation = any(phrase in ai_lower for phrase in [
            "physics violation", "physically inconsistent",
            "non-physical", "drainage behavior", "labeling error",
            "positive slope", "anomalous"
        ])
        checks.append({
            "rule": "Sign convention — no false physics violation",
            "status": "FAIL" if false_violation else "PASS",
            "note": "AI flagged imbibition negative Pc as a violation — incorrect"
                    if false_violation else "Correct"
        })
    return checks

def value_in_text(text, value, tolerance=0.05):
    import re
    numbers = re.findall(r"[-+]?\d*\.?\d+", text)
    for n in numbers:
        try:
            if abs(float(n) - value) / (abs(value) + 1e-9) <= tolerance:
                return True
        except ValueError:
            pass
    return False

def build_report(checks, ground_truth, filepath):
    total, passed = 0, 0
    lines = []
    lines.append(f"GRADING REPORT: {os.path.basename(filepath)}")
    lines.append("=" * 55)
    for check in checks:
        if "sub_checks" in check:
            sub = check["sub_checks"]
            sub_passed = sum(1 for c in sub if c["status"] == "PASS")
            sub_total  = len(sub)
            if sub_total == 0:
                continue
            pct = int(sub_passed / sub_total * 100)
            status_icon = "✅" if pct == 100 else "⚠️" if pct > 50 else "❌"
            lines.append(f"\n{status_icon} {check['rule']}: {sub_passed}/{sub_total} correct ({pct}%)")
            for sc in sub:
                icon = "  ✅" if sc["status"] == "PASS" else "  ❌"
                lines.append(f"{icon} {sc['field']} = {sc['expected']}")
            total  += sub_total
            passed += sub_passed
        else:
            status = check.get("status", "SKIP")
            icon = "✅" if status == "PASS" else "❌" if status == "FAIL" else "⚠️"
            note = check.get("note", "")
            expected = check.get("expected", "")
            missing  = check.get("missing", [])
            lines.append(f"\n{icon} {check['rule']}")
            if expected and not missing:
                lines.append(f"   Expected: {expected}")
            if missing:
                lines.append(f"   Missing samples: {missing}")
            if note:
                lines.append(f"   Note: {note}")
            total  += 1
            passed += 1 if status == "PASS" else 0
    score = int((passed / total * 100)) if total > 0 else 0
    grade = "A" if score >= 90 else "B" if score >= 80 else "C" if score >= 70 else "D" if score >= 60 else "F"
    lines.insert(2, f"Score: {score}/100  |  Grade: {grade}")
    lines.insert(3, "=" * 55)
    return {"score": score, "grade": grade, "text": "\n".join(lines)}

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python grader.py <excel_file> <ai_response.txt>")
        sys.exit(1)
    filepath     = sys.argv[1]
    ai_resp_file = sys.argv[2]
    with open(ai_resp_file, "r") as f:
        ai_text = f.read()
    result = grade_ai_response(filepath, ai_text)
    print(result["report"])
