"""robust_extract_scal smoke test against a real legacy .xls fixture.

Originally this file was an ad-hoc script that called robust_extract_scal on a
hardcoded absolute path (C:\\Users\\Asus\\Downloads\\FFCAL-OBP, T1-31.xls) that
does not exist on CI (or anywhere portable), so pytest collected 0 items and it
gave CI no signal. Rewritten as a real pytest test that uses the committed
fixture under tests/fixtures/. Needs no network or API key.
"""

from pathlib import Path

import pytest

from scal_file_handler import robust_extract_scal

FIXTURE = Path(__file__).parent / "fixtures" / "FFCAL-OBP, T1-31.xls"


@pytest.mark.skipif(not FIXTURE.exists(), reason="FFCAL-OBP fixture not present")
def test_robust_extract_scal_parses_legacy_xls():
    result = robust_extract_scal(str(FIXTURE))

    assert isinstance(result, dict)
    # A successful parse selects an engine and finds at least one data block.
    assert result.get("engine_used") is not None, f"errors: {result.get('errors')}"
    assert len(result.get("sheets", [])) > 0
    assert sum(1 for s in result["sheets"] if s.get("data_block")) > 0
