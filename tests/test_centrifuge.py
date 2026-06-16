"""SCALFileHandler smoke test for a centrifuge-style spreadsheet.

Originally this file was an ad-hoc script (module-level code with a print and
no test functions), so pytest collected 0 items and it gave CI no signal. It
also wrote `test_centrifuge.xlsx` into the repo root as an import side effect.
Rewritten as a real, hermetic pytest test that builds its fixture in a tmp dir.
Needs no network or API key.
"""

import pandas as pd

from scal_file_handler import SCALFileHandler


def test_centrifuge_xlsx_processes_to_dict(tmp_path):
    xlsx_path = tmp_path / "test_centrifuge.xlsx"
    df = pd.DataFrame(
        {
            "Speed (RPM)": [1000, 2000, 3000],
            "Produced Volume (cc)": [0.5, 1.2, 1.8],
        }
    )
    df.to_excel(xlsx_path, index=False, header=False)

    handler = SCALFileHandler(str(xlsx_path))
    result = handler.process()

    assert isinstance(result, dict)
    # process() returns a structured summary of the parsed workbook.
    assert "sheet_names" in result
    assert "extracted" in result


def test_forbes_correction():
    from hermes_skills_library.petroleum.centrifuge_skill import forbes_correction, hassler_brunner_correction
    import numpy as np

    pc = np.array([5.0, 10.0, 15.0])
    avg_sw = np.array([0.9, 0.7, 0.5])
    r1 = 8.0
    r2 = 10.0

    sw_face = forbes_correction(pc, avg_sw, r1, r2)
    assert len(sw_face) == 3
    assert np.all(sw_face >= 0.0) and np.all(sw_face <= 1.0)

    # Test fallback to Hassler-Brunner when r1/r2 are invalid/missing
    sw_fallback = forbes_correction(pc, avg_sw, None, r2)
    sw_hb = hassler_brunner_correction(pc, avg_sw)
    assert np.allclose(sw_fallback, sw_hb)

