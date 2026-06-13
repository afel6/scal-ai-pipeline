import pandas as pd
import pytest
from batch_process import detect_type, _col_set, _KR_KEYWORDS, _MICP_KEYWORDS, _RI_KEYWORDS, _FF_KEYWORDS

def test_col_set():
    """Verify column normalization."""
    df = pd.DataFrame(columns=["  krw  ", "Resistivity Index", "SOR"])
    expected = {"krw", "resistivity_index", "sor"}
    assert _col_set(df) == expected

def test_detect_type_micp():
    """Test detect_type identifies MICP data."""
    df = pd.DataFrame(columns=["hg", "mercury", "pressure_psia"])
    assert detect_type(df) == "micp"

def test_detect_type_kr():
    """Test detect_type identifies KR data."""
    df = pd.DataFrame(columns=["krw", "kro", "swi"])
    assert detect_type(df) == "kr"

    # Test bug case for keywords with spaces
    df_space = pd.DataFrame(columns=["relative permeability"])
    assert detect_type(df_space) == "kr"

def test_detect_type_ri():
    """Test detect_type identifies RI data."""
    # Test with both underscored and space-separated versions
    # to ensure bug fix works
    df1 = pd.DataFrame(columns=["resistivity index"])
    assert detect_type(df1) == "ri"

    df2 = pd.DataFrame(columns=["resistivity_index"])
    assert detect_type(df2) == "ri"

def test_detect_type_ff():
    """Test detect_type identifies FF data."""
    # Test with both underscored and space-separated versions
    df1 = pd.DataFrame(columns=["formation factor"])
    assert detect_type(df1) == "ff"

    df2 = pd.DataFrame(columns=["formation_factor"])
    assert detect_type(df2) == "ff"

def test_detect_type_unknown():
    """Test detect_type identifies unknown data."""
    df = pd.DataFrame(columns=["random_col_1", "random_col_2"])
    assert detect_type(df) == "unknown"

def test_detect_type_priority():
    """Test that MICP is prioritized over Kr."""
    df = pd.DataFrame(columns=["mercury", "krw"])
    assert detect_type(df) == "micp"
