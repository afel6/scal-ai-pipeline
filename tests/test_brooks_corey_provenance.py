"""Brooks-Corey endpoints must carry provenance (audit finding A3).

`prc_physics.fit_brooks_corey` silently replaced an undeterminable Swi/Sor with
0.1, and returned eight bare floats. Those endpoints build the normalised
saturation Se, so every other returned parameter inherits the substitution, and
the result reached an LLM prompt and a .docx deliverable unmarked. Real
sandstone Swi runs 0.15-0.35 and Sor 0.20-0.35, so 0.1/0.1 widens the movable
window at both ends and overstates recovery.

These tests pin: every parameter carries a source, the report path refuses
rather than substitutes, and the refusal text reaches the generated .docx.
"""

import sqlite3
from pathlib import Path
from typing import Dict, List

import pytest

import prc_physics


def _rows_with_explicit_endpoints() -> List[Dict[str, object]]:
    """A dataset whose Swi and Sor were reported by the laboratory."""
    return [
        {"Water_Saturation_fraction": sw, "Capillary_Pressure_psi": pc,
         "Relative_Permeability_Water": krw, "Relative_Permeability_Oil": kro,
         "explicit_Swi": 0.22, "explicit_Sor": 0.30}
        for sw, pc, krw, kro in [
            (0.25, 120.0, 0.005, 0.85), (0.35, 44.0, 0.030, 0.55),
            (0.45, 22.0, 0.080, 0.32), (0.55, 12.0, 0.160, 0.15),
            (0.65, 7.0, 0.280, 0.05),
        ]
    ]


def _rows_without_endpoints() -> List[Dict[str, object]]:
    """Saturations that cannot yield a usable endpoint pair.

    Every Sw is >= 1.0, so the derived Swi lands outside [0, 1) and the old
    code silently replaced it with 0.1.
    """
    return [
        {"Water_Saturation_fraction": 1.0, "Capillary_Pressure_psi": 10.0,
         "Relative_Permeability_Water": 0.10, "Relative_Permeability_Oil": 0.20},
        {"Water_Saturation_fraction": 1.0, "Capillary_Pressure_psi": 20.0,
         "Relative_Permeability_Water": 0.20, "Relative_Permeability_Oil": 0.10},
    ]


def test_measured_endpoints_are_reported_as_measured() -> None:
    fit = prc_physics.fit_brooks_corey(_rows_with_explicit_endpoints())
    assert fit["parameters"]["Swi"]["source"] == "measured"
    assert fit["parameters"]["Sor"]["source"] == "measured"
    assert fit["parameters"]["Swi"]["value"] == pytest.approx(0.22)
    assert fit["parameters"]["Sor"]["value"] == pytest.approx(0.30)


def test_every_parameter_carries_a_declared_source() -> None:
    fit = prc_physics.fit_brooks_corey(_rows_with_explicit_endpoints())
    expected = {"Swi", "Sor", "Pd_psi", "lambda", "nw", "no", "krw_max", "krnw_max"}
    assert set(fit["parameters"]) == expected
    for name, entry in fit["parameters"].items():
        assert "value" in entry, name
        assert entry["source"] in {"measured", "fitted", "substituted", "default"}, name


def test_endpoints_actually_used_are_reported() -> None:
    fit = prc_physics.fit_brooks_corey(_rows_with_explicit_endpoints())
    assert fit["endpoints_used"]["Swi"] == pytest.approx(0.22)
    assert fit["endpoints_used"]["Sor"] == pytest.approx(0.30)


def test_undeterminable_endpoints_are_marked_substituted_not_silent() -> None:
    fit = prc_physics.fit_brooks_corey(_rows_without_endpoints())
    assert fit["parameters"]["Swi"]["source"] == "substituted"
    assert "Swi" in fit["substituted"]


def test_report_path_refuses_rather_than_substituting() -> None:
    """enrich_json_with_brooks_corey is the report path — it must refuse."""
    with pytest.raises(prc_physics.EndpointProvenanceError, match="(?i)substitut"):
        prc_physics.enrich_json_with_brooks_corey(_rows_without_endpoints())


def test_enrichment_marks_rows_when_substitution_is_explicitly_allowed() -> None:
    rows = prc_physics.enrich_json_with_brooks_corey(
        _rows_without_endpoints(), allow_substitution=True)
    assert rows[0]["brooks_corey_Swi_source"] == "substituted"
    notice = rows[0]["brooks_corey_provenance_notice"]
    assert "substituted" in notice.lower()
    assert "Swi" in notice


def test_measured_enrichment_carries_measured_sources() -> None:
    rows = prc_physics.enrich_json_with_brooks_corey(_rows_with_explicit_endpoints())
    assert rows[0]["brooks_corey_Swi_source"] == "measured"
    assert rows[0]["brooks_corey_Swi"] == pytest.approx(0.22)


def test_substitution_notice_reaches_the_generated_docx(tmp_path: Path) -> None:
    """The .docx is built from the `m` transcript, so the notice must land there."""
    from docx import Document
    from report_generator import PRCReportEngine

    db_path = tmp_path / "chat_history.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE m (id INTEGER PRIMARY KEY AUTOINCREMENT, sid TEXT, "
                 "role TEXT, text TEXT, ts REAL, user_email TEXT, fname TEXT, "
                 "file_hash TEXT, url TEXT)")
    notice = prc_physics.provenance_notice(
        prc_physics.fit_brooks_corey(_rows_without_endpoints()))
    conn.execute("INSERT INTO m (sid, role, text, ts) VALUES (?,?,?,?)",
                 ("a3-docx", "model", notice, 1.0))
    conn.commit()
    conn.close()

    engine = PRCReportEngine(db_path=str(db_path))
    filename = engine.generate("a3-docx", "Well-A3", output_dir=str(tmp_path))
    text = "\n".join(p.text for p in Document(str(tmp_path / filename)).paragraphs)
    assert "substituted" in text.lower(), "the .docx carries no substitution notice"
