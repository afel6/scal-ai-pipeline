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
