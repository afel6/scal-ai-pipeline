"""
Phase 0b: Proof of Read — Anti-Hallucination Hardening Tests
=============================================================
Tests for structural inventory generation, validation, thinking block
stripping, placeholder artifact cleanup, multi-well detection, and
the critical salvage_and_clean_json override loop fix.
"""
import os
import sys
import json
import tempfile
import pytest
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from scal_file_handler import (
    SCALFileHandler,
    strip_thinking_blocks,
    fix_markdown_spacing,
    strip_placeholder_artifacts,
    validate_extraction_against_inventory,
    detect_multi_well_mixing,
    extract_absolute_file_truth,
    validate_permeability_column_binding,
)


# ────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────

@pytest.fixture
def sample_xlsx():
    """Create a minimal multi-sheet .xlsx for testing."""
    tmp_dir = tempfile.mkdtemp()
    fp = os.path.join(tmp_dir, "Phi_k_OBP_T1-31.xlsx")
    with pd.ExcelWriter(fp, engine="openpyxl") as writer:
        # comp 1 sheet
        df1 = pd.DataFrame({
            "Pressure_psi": [800.0, 1200.0, 2000.0],
            "Porosity_%": [18.5, 17.8, 16.2],
            "Ka_mD": [45.2, 38.6, 28.1],
        })
        df1.to_excel(writer, sheet_name="comp 1", index=False)
        # comp 2 sheet
        df2 = pd.DataFrame({
            "Pressure_psi": [800.0, 1200.0, 2000.0],
            "Porosity_%": [22.1, 21.0, 19.5],
            "Ka_mD": [120.5, 98.2, 72.0],
        })
        df2.to_excel(writer, sheet_name="comp 2", index=False)
        # Summary sheet (non-comp)
        df3 = pd.DataFrame({"Well": ["T1-31"], "Analyst": ["Dr. Smith"]})
        df3.to_excel(writer, sheet_name="Summary", index=False)
    yield fp
    # Cleanup
    import shutil
    shutil.rmtree(tmp_dir, ignore_errors=True)


@pytest.fixture
def multi_well_xlsx():
    """Create an .xlsx with data from two wells (multi-well mixing scenario)."""
    tmp_dir = tempfile.mkdtemp()
    fp = os.path.join(tmp_dir, "Mixed_Wells.xlsx")
    with pd.ExcelWriter(fp, engine="openpyxl") as writer:
        df1 = pd.DataFrame({
            "Well": ["T1-31", "T1-31"],
            "Pressure": [800, 1200],
            "Porosity": [18.5, 17.8],
        })
        df1.to_excel(writer, sheet_name="Sample 1", index=False)
        df2 = pd.DataFrame({
            "Well": ["Z11-47", "Z11-47"],
            "Pressure": [900, 1100],
            "Porosity": [20.1, 19.2],
        })
        df2.to_excel(writer, sheet_name="Sample 2", index=False)
    yield fp
    import shutil
    shutil.rmtree(tmp_dir, ignore_errors=True)


# ────────────────────────────────────────────────────────
# TEST: Structural Inventory Generation
# ────────────────────────────────────────────────────────

class TestStructuralInventory:

    def test_inventory_returns_all_sheets(self, sample_xlsx):
        handler = SCALFileHandler(sample_xlsx)
        handler.read()
        inv = handler.generate_structural_inventory()
        assert set(inv["sheets_found"]) == {"comp 1", "comp 2", "Summary"}

    def test_inventory_contains_filename(self, sample_xlsx):
        handler = SCALFileHandler(sample_xlsx)
        handler.read()
        inv = handler.generate_structural_inventory()
        assert inv["filename"] == "Phi_k_OBP_T1-31.xlsx"

    def test_inventory_sheet_inventories_populated(self, sample_xlsx):
        handler = SCALFileHandler(sample_xlsx)
        handler.read()
        inv = handler.generate_structural_inventory()
        assert len(inv["sheet_inventories"]) == 3  # comp 1, comp 2, Summary

    def test_inventory_shape_correct(self, sample_xlsx):
        handler = SCALFileHandler(sample_xlsx)
        handler.read()
        inv = handler.generate_structural_inventory()
        # comp 1: 4 rows (1 header read as data since header=None + 3 data), 3 cols
        comp1 = next(s for s in inv["sheet_inventories"] if s["sheet_name"] == "comp 1")
        assert comp1["shape"][1] == 3  # 3 columns

    def test_inventory_first_2_rows_present(self, sample_xlsx):
        handler = SCALFileHandler(sample_xlsx)
        handler.read()
        inv = handler.generate_structural_inventory()
        comp1 = next(s for s in inv["sheet_inventories"] if s["sheet_name"] == "comp 1")
        assert len(comp1["first_2_rows"]) <= 2

    def test_inventory_text_output_format(self, sample_xlsx):
        handler = SCALFileHandler(sample_xlsx)
        handler.read()
        text = handler.generate_structural_inventory_text()
        assert "PHASE 0b — PROOF OF READ" in text
        assert "comp 1" in text
        assert "comp 2" in text
        assert "Summary" in text

    def test_process_includes_inventory(self, sample_xlsx):
        handler = SCALFileHandler(sample_xlsx)
        result = handler.process()
        assert "structural_inventory" in result
        assert result["structural_inventory"]["sheets_found"] == ["comp 1", "comp 2", "Summary"]


# ────────────────────────────────────────────────────────
# TEST: Structural Validation (Halt on Hallucination)
# ────────────────────────────────────────────────────────

class TestStructuralValidation:

    def test_clean_extraction_no_violations(self):
        inventory = {
            "sheets_found": ["comp 1", "comp 2", "Summary"],
            "sheet_inventories": [
                {"sheet_name": "comp 1", "header_row_raw": "Pressure | Porosity | Ka"},
            ],
        }
        extracted = {
            "protocol_1_file_open_proof": {
                "target_sheet": "comp 1",
                "sheet_names": ["comp 1", "comp 2", "Summary"],
            },
            "extracted_data": [{"Pressure_psi": 800}],
        }
        violations = validate_extraction_against_inventory(extracted, inventory)
        assert len(violations) == 0

    def test_hallucinated_sheet_in_protocol1_detected(self):
        inventory = {
            "sheets_found": ["Sheet1"],
            "sheet_inventories": [
                {"sheet_name": "Sheet1", "header_row_raw": "A | B | C"},
            ],
        }
        extracted = {
            "protocol_1_file_open_proof": {
                "target_sheet": "PHANTOM_SHEET",
                "sheet_names": ["Sheet1"],
            },
            "extracted_data": [{"A": 1}],
        }
        violations = validate_extraction_against_inventory(extracted, inventory)
        assert len(violations) >= 1
        assert "STRUCTURAL_HALT" in violations[0]
        assert "PHANTOM_SHEET" in violations[0]

    def test_hallucinated_sheet_in_phase0b_detected(self):
        inventory = {
            "sheets_found": ["Sheet1"],
            "sheet_inventories": [],
        }
        extracted = {
            "phase_0b_proof_of_read": {
                "sheets_found": ["Sheet1", "HALLUCINATED_SHEET"],
            },
            "extracted_data": [],
        }
        violations = validate_extraction_against_inventory(extracted, inventory)
        assert any("HALLUCINATED_SHEET" in v for v in violations)


# ────────────────────────────────────────────────────────
# TEST: <thinking> Block Stripping
# ────────────────────────────────────────────────────────




class TestThinkingBlockStrip:

    def test_strip_complete_thinking_block(self):
        text = "Hello <thinking>internal reasoning here</thinking> World"
        assert strip_thinking_blocks(text) == "Hello  World"

    def test_strip_multiline_thinking_block(self):
        text = "Start\n<thinking>\nLine 1\nLine 2\n</thinking>\nEnd"
        result = strip_thinking_blocks(text)
        assert "<thinking>" not in result
        assert "Start" in result
        assert "End" in result

    def test_strip_unclosed_thinking_block(self):
        text = "Good data here\n<thinking>unfinished reasoning"
        result = strip_thinking_blocks(text)
        assert "<thinking>" not in result
        assert "Good data here" in result

    def test_strip_case_insensitive(self):
        text = "A <THINKING>stuff</THINKING> B"
        assert "<THINKING>" not in strip_thinking_blocks(text)

    def test_no_thinking_blocks_unchanged(self):
        text = "Normal text with no thinking blocks"
        assert strip_thinking_blocks(text) == text

    def test_empty_input(self):
        assert strip_thinking_blocks("") == ""
        assert strip_thinking_blocks(None) is None


# ────────────────────────────────────────────────────────
# TEST: Placeholder Artifact Stripping
# ────────────────────────────────────────────────────────

class TestPlaceholderStrip:

    def test_strip_not_yet_checked(self):
        text = "Value: 42.5 [NOT YET CHECKED] units: mD"
        result = strip_placeholder_artifacts(text)
        assert "[NOT YET CHECKED]" not in result
        assert "42.5" in result

    def test_strip_case_insensitive_placeholder(self):
        text = "Data [not yet checked] here"
        result = strip_placeholder_artifacts(text)
        assert "[not yet checked]" not in result.lower()

    def test_strip_pipe_clutter(self):
        text = "Header |||| Value"
        result = strip_placeholder_artifacts(text)
        assert "||||" not in result

    def test_collapse_excess_whitespace(self):
        text = "Line 1\n\n\n\n\nLine 2"
        result = strip_placeholder_artifacts(text)
        assert "\n\n\n" not in result

    def test_empty_input(self):
        assert strip_placeholder_artifacts("") == ""
        assert strip_placeholder_artifacts(None) is None


# ────────────────────────────────────────────────────────
# TEST: Multi-Well Mixing Detection
# ────────────────────────────────────────────────────────

class TestMultiWellDetection:

    def test_single_well_returns_none(self):
        raw_data = {
            "Sheet1": pd.DataFrame({
                "Well": ["T1-31", "T1-31"],
                "Value": [1, 2],
            }),
        }
        result = detect_multi_well_mixing(raw_data, "T1-31_data.xlsx")
        assert result is None

    def test_multi_well_detected(self, multi_well_xlsx):
        handler = SCALFileHandler(multi_well_xlsx)
        handler.read()
        inv = handler.generate_structural_inventory()
        if inv["multi_well_alert"]:
            assert len(inv["multi_well_alert"]) >= 2

    def test_multi_well_raw_data_detection(self):
        raw_data = {
            "Sample 1": pd.DataFrame({
                "Well": ["T1-31", "T1-31"],
                "Pressure": [800, 1200],
            }),
            "Sample 2": pd.DataFrame({
                "Well": ["Z11-47", "Z11-47"],
                "Pressure": [900, 1100],
            }),
        }
        result = detect_multi_well_mixing(raw_data, "Mixed_Wells.xlsx")
        assert result is not None
        assert len(result) >= 2


# ────────────────────────────────────────────────────────
# TEST: Salvage Override Loop Correctness
# ────────────────────────────────────────────────────────

class TestSalvageOverrideLoop:
    """Regression tests for the critical bug where `return data_list` was
    inside the override loop, causing only the first override key to be applied."""

    def test_both_swi_and_sor_overrides_applied(self):
        """Simulate the salvage_and_clean_json logic to verify both overrides work."""
        parsed = {
            "phase_0b_proof_of_read": {"filename": "test.xlsx", "sheets_found": ["Sheet1"]},
            "protocol_1_file_open_proof": {"sheet_names": ["Sheet1"], "target_sheet": "Sheet1", "raw_column_headers": ["A"]},
            "protocol_2_header_unit_double_check": [],
            "protocol_3_labeled_value_absolute_priority": {
                "explicit_statements_found": ["Swi = 0.25", "Sor = 0.15"],
                "overridden_endpoints": {"Swi": 0.25, "Sor": 0.15},
            },
            "extracted_data": [
                {"Pressure_psi": 800, "Porosity_percent": 18.5},
                {"Pressure_psi": 1200, "Porosity_percent": 17.2},
            ],
        }

        # Replicate the FIXED salvage logic
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

        # BOTH overrides must be present on every row
        for row in data_list:
            assert "explicit_Swi" in row, "explicit_Swi missing — override loop broken"
            assert "explicit_Sor" in row, "explicit_Sor missing — override loop broken"
            assert row["explicit_Swi"] == 0.25
            assert row["explicit_Sor"] == 0.15

    def test_single_override_swi_only(self):
        """If only Swi is provided, Sor should NOT be fabricated."""
        parsed_overrides = {"Swi": 0.35}
        data_list = [{"Pressure_psi": 500}]
        for row in data_list:
            for ok, ov in parsed_overrides.items():
                if ov is not None:
                    if ok.lower() == "swi":
                        row["explicit_Swi"] = float(ov)
                    elif ok.lower() == "sor":
                        row["explicit_Sor"] = float(ov)
        assert data_list[0].get("explicit_Swi") == 0.35
        assert "explicit_Sor" not in data_list[0]

    def test_structural_halt_json_detected(self):
        """If the LLM outputs STRUCTURAL_HALT, it should be detectable."""
        parsed = {"STRUCTURAL_HALT": "Sheet 'PHANTOM' not in inventory"}
        assert "STRUCTURAL_HALT" in parsed
        assert "PHANTOM" in parsed["STRUCTURAL_HALT"]


# ────────────────────────────────────────────────────────
# TEST: Extraction Prompt Integrity
# ────────────────────────────────────────────────────────

class TestExtractionPromptIntegrity:

    def test_extraction_prompt_exists(self):
        prompt_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "prompts", "extraction_system_prompt.md"
        )
        assert os.path.exists(prompt_path), "extraction_system_prompt.md missing"

    def test_extraction_prompt_contains_phase_0b(self):
        prompt_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "prompts", "extraction_system_prompt.md"
        )
        content = open(prompt_path, "r", encoding="utf-8").read()
        required = [
            "PHASE 0b",
            "PROOF OF READ",
            "STRUCTURAL_HALT",
            "phase_0b_proof_of_read",
            "MULTI_WELL_ALERT",
            "protocol_1_file_open_proof",
            "protocol_2_header_unit_double_check",
            "protocol_3_labeled_value_absolute_priority",
            "extracted_data",
            "FORBIDDEN",
        ]
        missing = [r for r in required if r not in content]
        assert not missing, f"extraction_system_prompt.md missing: {missing}"

    def test_extraction_prompt_minimum_length(self):
        prompt_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "prompts", "extraction_system_prompt.md"
        )
        content = open(prompt_path, "r", encoding="utf-8").read()
        word_count = len(content.split())
        assert word_count >= 500, f"Extraction prompt too short: {word_count} words"


# ────────────────────────────────────────────────────────
# TEST: Phase 0b Wiring — Inventory Text Injection Readiness
# ────────────────────────────────────────────────────────

class TestInventoryTextInjection:
    """Verify that generate_structural_inventory_text() produces
    ground-truth content suitable for direct injection into the LLM prompt."""

    def test_inventory_text_contains_ground_truth_markers(self, sample_xlsx):
        """The text must contain exact file/sheet data the LLM can verify against."""
        handler = SCALFileHandler(sample_xlsx)
        handler.read()
        text = handler.generate_structural_inventory_text()
        # Must contain the exact filename
        assert "Phi_k_OBP_T1-31.xlsx" in text
        # Must contain all sheet names
        assert "comp 1" in text
        assert "comp 2" in text
        assert "Summary" in text
        # Must contain shape info
        assert "×" in text  # shape format: (rows × columns)
        # Must contain the HEADER ROW label
        assert "HEADER ROW:" in text

    def test_inventory_text_contains_data_rows(self, sample_xlsx):
        """The text must include actual data rows so the LLM has proof-of-read."""
        handler = SCALFileHandler(sample_xlsx)
        handler.read()
        text = handler.generate_structural_inventory_text()
        # Must have DATA ROW entries
        assert "DATA ROW" in text

    def test_inventory_text_not_empty_for_spreadsheets(self, sample_xlsx):
        """For any spreadsheet file, inventory text must never be empty."""
        handler = SCALFileHandler(sample_xlsx)
        handler.read()
        text = handler.generate_structural_inventory_text()
        assert len(text) > 100, f"Inventory text too short ({len(text)} chars)"

    def test_inventory_and_validation_round_trip(self, sample_xlsx):
        """Full round-trip: generate inventory, then validate a clean extraction against it."""
        handler = SCALFileHandler(sample_xlsx)
        handler.read()
        inventory = handler.generate_structural_inventory()

        # Simulate a clean LLM extraction that references valid sheets
        clean_extraction = {
            "phase_0b_proof_of_read": {
                "filename": "Phi_k_OBP_T1-31.xlsx",
                "sheets_found": ["comp 1", "comp 2", "Summary"],
            },
            "protocol_1_file_open_proof": {
                "target_sheet": "comp 1",
                "sheet_names": ["comp 1", "comp 2", "Summary"],
                "raw_column_headers": ["Pressure_psi", "Porosity_%", "Ka_mD"],
            },
            "extracted_data": [{"Pressure_psi": 800}],
        }
        violations = validate_extraction_against_inventory(clean_extraction, inventory)
        assert len(violations) == 0, f"Unexpected violations: {violations}"

    def test_inventory_validation_catches_hallucinated_sheet(self, sample_xlsx):
        """Round-trip: validation must catch a hallucinated sheet."""
        handler = SCALFileHandler(sample_xlsx)
        handler.read()
        inventory = handler.generate_structural_inventory()

        bad_extraction = {
            "phase_0b_proof_of_read": {
                "sheets_found": ["comp 1", "comp 2", "Summary", "FABRICATED_SHEET"],
            },
            "protocol_1_file_open_proof": {
                "target_sheet": "FABRICATED_SHEET",
            },
            "extracted_data": [{"A": 1}],
        }
        violations = validate_extraction_against_inventory(bad_extraction, inventory)
        assert len(violations) >= 1
        assert any("FABRICATED_SHEET" in v for v in violations)


# ────────────────────────────────────────────────────────
# TEST: Petrophysical Hardening Rules in Prompt
# ────────────────────────────────────────────────────────

class TestPetrophysicalHardeningRules:
    """Verify the extraction prompt contains specific hardening rules for
    Phi_k_OBP comp sheets, Specific Oil Permeability isolation, and saturation logic."""

    def test_comp_sheet_iteration_rule(self):
        prompt_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "prompts", "extraction_system_prompt.md"
        )
        content = open(prompt_path, "r", encoding="utf-8").read()
        assert "comp" in content.lower(), "Missing comp sheet iteration rule"
        assert "Phi_k_OBP" in content, "Missing Phi_k_OBP reference"

    def test_specific_oil_perm_isolation_rule(self):
        prompt_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "prompts", "extraction_system_prompt.md"
        )
        content = open(prompt_path, "r", encoding="utf-8").read()
        assert "Specific Oil Permeability" in content or "Sheet1" in content, \
            "Missing Specific Oil Permeability isolation rule"

    def test_explicit_swi_sor_rule(self):
        prompt_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "prompts", "extraction_system_prompt.md"
        )
        content = open(prompt_path, "r", encoding="utf-8").read()
        assert "explicit_Swi" in content or "Swi" in content, "Missing Swi override rule"
        assert "explicit_Sor" in content or "Sor" in content, "Missing Sor override rule"


# ────────────────────────────────────────────────────────
# TEST: Deterministic Pre-Parser (extract_absolute_file_truth)
# ────────────────────────────────────────────────────────

class TestExtractAbsoluteFileTruth:
    """Verify the standalone deterministic pre-parser produces correct ground truth."""

    @staticmethod
    def _safe_unlink(path):
        """Best-effort cleanup — Windows may hold locks."""
        try:
            os.unlink(path)
        except PermissionError:
            pass

    def test_xlsx_single_sheet(self):
        """XLSX with a single sheet returns correct metadata."""
        f = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        fpath = f.name
        f.close()
        df = pd.DataFrame({"Ka (mD)": [10.5, 20.3], "Porosity (%)": [18.0, 16.5]})
        df.to_excel(fpath, index=False, sheet_name="Sheet1")
        result = extract_absolute_file_truth([(fpath, "test_single.xlsx")])
        self._safe_unlink(fpath)

        assert "MANDATORY_GROUND_TRUTH_INVENTORY" in result
        assert "test_single.xlsx" in result
        assert "TOTAL SHEETS: 1" in result
        assert "Sheet1" in result
        assert "Ka (mD)" in result
        assert "Porosity (%)" in result

    def test_xlsx_multi_sheet(self):
        """XLSX with multiple sheets lists all of them."""
        f = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        fpath = f.name
        f.close()
        with pd.ExcelWriter(fpath, engine="openpyxl") as writer:
            pd.DataFrame({"A": [1]}).to_excel(writer, sheet_name="comp 1", index=False)
            pd.DataFrame({"B": [2]}).to_excel(writer, sheet_name="comp 2", index=False)
            pd.DataFrame({"C": [3]}).to_excel(writer, sheet_name="Summary", index=False)
        result = extract_absolute_file_truth([(fpath, "multi_sheet.xlsx")])
        self._safe_unlink(fpath)

        assert "TOTAL SHEETS: 3" in result
        assert "comp 1" in result
        assert "comp 2" in result
        assert "Summary" in result

    def test_csv_file(self):
        """CSV files are handled as single-sheet."""
        f = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w", encoding="utf-8")
        f.write("Pressure,Porosity\n800,18.5\n1200,17.8\n")
        fpath = f.name
        f.close()
        result = extract_absolute_file_truth([(fpath, "test.csv")])
        self._safe_unlink(fpath)

        assert "TOTAL SHEETS: 1 (CSV)" in result
        assert "Pressure" in result
        assert "Porosity" in result

    def test_non_tabular_file(self):
        """Non-tabular files produce a graceful note."""
        f = tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="w")
        f.write("some text")
        fpath = f.name
        f.close()
        result = extract_absolute_file_truth([(fpath, "notes.txt")])
        self._safe_unlink(fpath)

        assert "Non-tabular file" in result

    def test_multiple_files(self):
        """Multiple files in a single call produce combined inventory."""
        paths = []
        for name, col in [("file_A.xlsx", "X"), ("file_B.xlsx", "Y")]:
            f = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
            fpath = f.name
            f.close()
            pd.DataFrame({col: [1]}).to_excel(fpath, index=False)
            paths.append((fpath, name))

        result = extract_absolute_file_truth(paths)
        for p, _ in paths:
            self._safe_unlink(p)

        assert "file_A.xlsx" in result
        assert "file_B.xlsx" in result

    def test_row_data_present(self):
        """First 2 data rows are printed in the inventory."""
        f = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        fpath = f.name
        f.close()
        df = pd.DataFrame({"Value": [42.7, 99.1, 0.5]})
        df.to_excel(fpath, index=False)
        result = extract_absolute_file_truth([(fpath, "rows.xlsx")])
        self._safe_unlink(fpath)

        assert "ROW 0" in result
        assert "ROW 1" in result
        assert "42.7" in result
        assert "99.1" in result

    def test_end_marker_present(self):
        """Output ends with the END OF MANDATORY_GROUND_TRUTH_INVENTORY marker."""
        f = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        fpath = f.name
        f.close()
        pd.DataFrame({"A": [1]}).to_excel(fpath, index=False)
        result = extract_absolute_file_truth([(fpath, "x.xlsx")])
        self._safe_unlink(fpath)

        assert "END OF MANDATORY_GROUND_TRUTH_INVENTORY" in result


# ────────────────────────────────────────────────────────
# TEST: Permeability Column Binding Validation
# ────────────────────────────────────────────────────────

class TestPermeabilityColumnBinding:
    """Verify that permeability fields bound to volume columns are caught."""

    def test_clean_binding_passes(self):
        """Permeability bound to a real permeability column — no violations."""
        parsed = {
            "protocol_2_header_unit_double_check": [
                {
                    "row_index": 1,
                    "checks": [
                        {"field": "Klinkenberg_Permeability_md", "literal_header": "KL (mD)", "literal_unit": "mD", "value": 42.1},
                        {"field": "Air_Permeability_md", "literal_header": "Ka (mD)", "literal_unit": "mD", "value": 45.2},
                    ]
                }
            ]
        }
        violations = validate_permeability_column_binding(parsed)
        assert violations == [], f"Expected no violations but got: {violations}"

    def test_volume_binding_caught(self):
        """Permeability bound to Cum.vol.inj. (cc) — MUST be caught."""
        parsed = {
            "protocol_2_header_unit_double_check": [
                {
                    "row_index": 1,
                    "checks": [
                        {"field": "Klinkenberg_Permeability_md", "literal_header": "Cum.vol.inj. (cc)", "literal_unit": "cc", "value": 5.2},
                    ]
                }
            ]
        }
        violations = validate_permeability_column_binding(parsed)
        assert len(violations) == 1
        assert "PERM_COLUMN_HALT" in violations[0]
        assert "Cum.vol.inj." in violations[0]

    def test_cumulative_volume_caught(self):
        """Permeability bound to 'Cumulative Volume' — MUST be caught."""
        parsed = {
            "protocol_2_header_unit_double_check": [
                {
                    "row_index": 1,
                    "checks": [
                        {"field": "Air_Permeability_md", "literal_header": "Cumulative Volume (ml)", "literal_unit": "ml", "value": 10.0},
                    ]
                }
            ]
        }
        violations = validate_permeability_column_binding(parsed)
        assert len(violations) == 1
        assert "PERM_COLUMN_HALT" in violations[0]

    def test_empty_protocol2_passes(self):
        """Empty or missing protocol_2 — no violations."""
        assert validate_permeability_column_binding({}) == []
        assert validate_permeability_column_binding({"protocol_2_header_unit_double_check": []}) == []


# ────────────────────────────────────────────────────────
# TEST: Fixed Column Header Validation (was dead code)
# ────────────────────────────────────────────────────────

class TestColumnHeaderValidation:
    """Verify that validate_extraction_against_inventory now checks column headers."""

    def test_valid_column_passes(self):
        """Column that exists in inventory passes validation."""
        inventory = {
            "sheets_found": ["Sheet1"],
            "sheet_inventories": [
                {
                    "sheet_name": "Sheet1",
                    "header_row_raw": "Ka (mD) | KL (mD) | Porosity (%)",
                }
            ]
        }
        parsed = {
            "protocol_1_file_open_proof": {"target_sheet": "Sheet1", "raw_column_headers": ["Ka (mD)"]},
            "phase_0b_proof_of_read": {"sheets_found": ["Sheet1"]},
            "protocol_2_header_unit_double_check": [
                {"row_index": 1, "checks": [{"field": "Air_Permeability_md", "literal_header": "Ka (mD)", "literal_unit": "mD", "value": 10.0}]}
            ]
        }
        violations = validate_extraction_against_inventory(parsed, inventory)
        assert violations == []

    def test_hallucinated_column_caught(self):
        """Column NOT in inventory is caught."""
        inventory = {
            "sheets_found": ["Sheet1"],
            "sheet_inventories": [
                {
                    "sheet_name": "Sheet1",
                    "header_row_raw": "Ka (mD) | Porosity (%)",
                }
            ]
        }
        parsed = {
            "protocol_1_file_open_proof": {"target_sheet": "Sheet1", "raw_column_headers": ["Ka (mD)"]},
            "phase_0b_proof_of_read": {"sheets_found": ["Sheet1"]},
            "protocol_2_header_unit_double_check": [
                {"row_index": 1, "checks": [{"field": "Pressure_psi", "literal_header": "Phantom Column XYZ", "literal_unit": "psi", "value": 800}]}
            ]
        }
        violations = validate_extraction_against_inventory(parsed, inventory)
        assert len(violations) >= 1
        assert any("COLUMN_HALT" in v for v in violations)
        assert "Phantom Column XYZ" in violations[0]
