import os
import pandas as pd
import pytest
from batch_process import read_file

def test_read_file_csv(tmp_path):
    csv_file = tmp_path / "test.csv"
    df = pd.DataFrame({"col1": [1, 2], "col2": [3, 4]})
    df.to_csv(csv_file, index=False)

    result = read_file(str(csv_file))
    assert len(result) == 1
    assert isinstance(result[0], pd.DataFrame)
    pd.testing.assert_frame_equal(result[0], df)

def test_read_file_xlsx(tmp_path):
    excel_file = tmp_path / "test.xlsx"
    df1 = pd.DataFrame({"A": [1, 2], "B": [3, 4]})
    df2 = pd.DataFrame({"C": [5, 6], "D": [7, 8]})

    with pd.ExcelWriter(excel_file) as writer:
        df1.to_excel(writer, sheet_name="Sheet1", index=False)
        df2.to_excel(writer, sheet_name="Sheet2", index=False)

    result = read_file(str(excel_file))
    assert len(result) == 2
    assert isinstance(result[0], pd.DataFrame)
    assert isinstance(result[1], pd.DataFrame)
    pd.testing.assert_frame_equal(result[0], df1)
    pd.testing.assert_frame_equal(result[1], df2)

def test_read_file_unsupported_extension(tmp_path):
    txt_file = tmp_path / "test.txt"
    txt_file.write_text("hello world")

    result = read_file(str(txt_file))
    assert result == []

def test_read_file_xls_fixture():
    fixture_path = os.path.join(os.path.dirname(__file__), "fixtures", "FFCAL-OBP, T1-31.xls")

    # Check if fixture exists
    if not os.path.exists(fixture_path):
        pytest.skip(f"Fixture not found at {fixture_path}")

    result = read_file(fixture_path)
    # The xls file should be successfully read and return at least one dataframe
    assert len(result) > 0
    assert isinstance(result[0], pd.DataFrame)
