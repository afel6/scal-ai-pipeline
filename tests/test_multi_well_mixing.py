import pytest
import pandas as pd
import numpy as np
from scal_file_handler import detect_multi_well_mixing

def test_detect_multi_well_mixing_single_well():
    df1 = pd.DataFrame({'col1': ['Well A-1', 'data'], 'col2': [1, 2]})
    df2 = pd.DataFrame({'col1': ['Well A-1', 'more data'], 'col2': [3, 4]})
    raw_data = {'sheet1': df1, 'sheet2': df2}
    result = detect_multi_well_mixing(raw_data)
    assert result is None

def test_detect_multi_well_mixing_multiple_wells_different_sheets():
    df1 = pd.DataFrame({'col1': ['Well A-1', 'data'], 'col2': [1, 2]})
    df2 = pd.DataFrame({'col1': ['Well B-2', 'more data'], 'col2': [3, 4]})
    raw_data = {'sheet1': df1, 'sheet2': df2}
    result = detect_multi_well_mixing(raw_data)
    assert result == {'A-1': ['sheet1'], 'B-2': ['sheet2']}

def test_detect_multi_well_mixing_multiple_wells_same_sheet():
    df1 = pd.DataFrame({'col1': ['Well A-1', 'Well B-2'], 'col2': [1, 2]})
    raw_data = {'sheet1': df1}
    result = detect_multi_well_mixing(raw_data)
    # the well strings can be sorted differently depending on set
    assert result is not None
    assert 'A-1' in result
    assert 'B-2' in result
    assert result['A-1'] == ['sheet1']
    assert result['B-2'] == ['sheet1']

def test_detect_multi_well_mixing_no_wells_found():
    df1 = pd.DataFrame({'col1': ['data', 'data'], 'col2': [1, 2]})
    df2 = pd.DataFrame({'col1': ['more data', 'more data'], 'col2': [3, 4]})
    raw_data = {'sheet1': df1, 'sheet2': df2}
    result = detect_multi_well_mixing(raw_data)
    assert result is None

def test_detect_multi_well_mixing_empty_and_none_dataframes():
    df1 = pd.DataFrame()
    raw_data = {'sheet1': df1, 'sheet2': None}
    result = detect_multi_well_mixing(raw_data)
    assert result is None

def test_detect_multi_well_mixing_nan_and_non_string_values():
    # Only string values are checked in text_block
    df1 = pd.DataFrame({'col1': [np.nan, 123, 'Well A-1'], 'col2': [1, 2, 3]})
    df2 = pd.DataFrame({'col1': ['Well B-2', np.nan, 456], 'col2': [4, 5, 6]})
    raw_data = {'sheet1': df1, 'sheet2': df2}
    result = detect_multi_well_mixing(raw_data)
    assert result == {'A-1': ['sheet1'], 'B-2': ['sheet2']}

def test_detect_multi_well_mixing_with_filename():
    df1 = pd.DataFrame({'col1': ['data'], 'col2': [1]})
    df2 = pd.DataFrame({'col1': ['Well B-2'], 'col2': [3]})
    raw_data = {'sheet1': df1, 'sheet2': df2}
    # filename has 'Well A-1', but the function ignores primary_well from filename
    # when determining well_sheet_map unless we fix the function, let's test current behavior.
    # Currently `primary_well` is extracted but not used to determine mixing if it doesn't appear in sheets.
    # Thus only B-2 is found -> single well -> None.
    result = detect_multi_well_mixing(raw_data, filename="C:/data/Well A-1.xlsx")
    assert result is None

def test_detect_multi_well_mixing_multiple_wells_across_many_sheets():
    df1 = pd.DataFrame({'col1': ['Well X-1']})
    df2 = pd.DataFrame({'col1': ['Well Y-2']})
    df3 = pd.DataFrame({'col1': ['Well X-1']})
    raw_data = {'s1': df1, 's2': df2, 's3': df3}
    result = detect_multi_well_mixing(raw_data)
    assert result == {'X-1': ['s1', 's3'], 'Y-2': ['s2']}

def test_detect_multi_well_mixing_only_checks_first_10_rows():
    # Data row 11 should not be checked
    data = ['data'] * 15
    data[11] = 'Well A-1'
    df1 = pd.DataFrame({'col1': data})

    data2 = ['data'] * 15
    data2[11] = 'Well B-2'
    df2 = pd.DataFrame({'col1': data2})

    raw_data = {'sheet1': df1, 'sheet2': df2}
    result = detect_multi_well_mixing(raw_data)
    # The wells are at index 11 (12th row), so they are not scanned
    assert result is None

def test_detect_multi_well_mixing_within_first_10_rows():
    data = ['data'] * 15
    data[9] = 'Well A-1'
    df1 = pd.DataFrame({'col1': data})

    data2 = ['data'] * 15
    data2[9] = 'Well B-2'
    df2 = pd.DataFrame({'col1': data2})

    raw_data = {'sheet1': df1, 'sheet2': df2}
    result = detect_multi_well_mixing(raw_data)
    # The wells are at index 9 (10th row), so they ARE scanned
    assert result == {'A-1': ['sheet1'], 'B-2': ['sheet2']}
