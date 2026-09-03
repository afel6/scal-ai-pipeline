# tests/test_pvt_rejection.py — dataset isolation: Hviel's SCAL pipeline must
# detect PVT fluid reports and reject them with a routing error instead of
# parsing them into SCAL formats.
import pandas as pd
import pytest

from scal_file_handler import SCALFileHandler, extract_file_data


@pytest.fixture
def pvt_xlsx(tmp_path):
    path = tmp_path / "pvt_report.xlsx"
    dl = pd.DataFrame({
        "Pressure (psia)": [3000, 2500, 2000, 1500],
        "Bo (rb/stb)": [1.45, 1.42, 1.38, 1.33],
        "Rs (scf/stb)": [800, 700, 600, 480],
    })
    meta = pd.DataFrame({"Report": [
        "Differential Liberation Study", "Bubble Point Determination", "GOR summary",
    ]})
    with pd.ExcelWriter(path) as xw:
        dl.to_excel(xw, sheet_name="DL", index=False)
        meta.to_excel(xw, sheet_name="Meta", index=False)
    return str(path)


def test_pvt_identified_but_not_parsed(pvt_xlsx):
    handler = SCALFileHandler(pvt_xlsx).read().identify()
    assert handler.data_type == "PVT"
    handler.extract()
    assert handler.extracted["samples"] == {}
    assert "Aviel" in handler.extracted["error"]


def test_extract_file_data_rejects_pvt(pvt_xlsx):
    result = extract_file_data(pvt_xlsx)
    assert result["status"] == "rejected_wrong_dataset"
    assert result["data_type"] == "PVT"
    assert result["row_count"] == 0
    assert result["extracted"] == {}
    assert any("Aviel" in e for e in result["errors"])
