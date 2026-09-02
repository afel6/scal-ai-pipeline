"""Regression tests for cached-vector resolution (audit finding A1).

The original `find_cached_vector` matched aliases by bare substring, so the
two-character alias "ri" matched the sheet name `Archie_VariableSw` through
"Va[ri]ableSw". The RI lookup returned the Sw column, the Archie fit regressed
Sw on itself, and n collapsed to exactly -1.000 on every run.

These tests pin the three properties that prevent that class of failure:
exact matching, loud failure instead of silent fall-through, and a guard that
refuses to regress a vector on itself.
"""

from typing import Dict, List

import numpy as np
import pytest

import app


SHEET = "Archie_VariableSw"
SW_VALUES: List[float] = [1.00, 0.90, 0.80, 0.70, 0.60, 0.50, 0.40, 0.30]
RI_VALUES: List[float] = [round(sw ** -1.85, 4) for sw in SW_VALUES]


def _flat_vectors(extra: Dict[str, List[float]] | None = None) -> Dict[str, List[float]]:
    """Build a cache in the shape `cache_excel_data_vectors` actually writes.

    Every column lands under two keys: the sheet-qualified one (app.py:1386)
    and the bare lower-cased header (app.py:1387).
    """
    vectors: Dict[str, List[float]] = {
        f"{SHEET}.Water_Saturation_Sw".lower().replace(" ", "_"): SW_VALUES,
        "water_saturation_sw": SW_VALUES,
        f"{SHEET}.Resistivity_Index_RI".lower().replace(" ", "_"): RI_VALUES,
        "resistivity_index_ri": RI_VALUES,
    }
    if extra:
        vectors.update(extra)
    return vectors


@pytest.fixture()
def cached_sid(request: pytest.FixtureRequest) -> str:
    """Seed SESSION_DATA_CACHE directly so no database is touched.

    `load_session_cache_from_db` short-circuits when the sid is present with a
    non-empty ground_truth (app.py:9343), so this keeps the test offline.
    """
    sid = f"a1-{request.node.name}"
    with app.SESSION_DATA_CACHE_LOCK:
        app.SESSION_DATA_CACHE[sid] = {
            "ground_truth": "seeded by test_vector_lookup",
            "labeled_values": {},
            "flat_vectors": _flat_vectors(),
        }
    yield sid
    with app.SESSION_DATA_CACHE_LOCK:
        app.SESSION_DATA_CACHE.pop(sid, None)


def test_ri_role_does_not_return_the_sw_vector(cached_sid: str) -> None:
    """The exact bug: alias "ri" must not resolve through "Va[ri]ableSw"."""
    assert app.find_cached_vector(cached_sid, "ri") != SW_VALUES


def test_roles_resolve_to_their_own_columns(cached_sid: str) -> None:
    assert app.find_cached_vector(cached_sid, "sw") == SW_VALUES
    assert app.find_cached_vector(cached_sid, "ri") == RI_VALUES


def test_archie_n_fit_does_not_collapse_to_minus_one(cached_sid: str) -> None:
    """With the columns resolved correctly the fit recovers the true exponent."""
    sw = np.array(app.find_cached_vector(cached_sid, "sw"), dtype=float)
    ri = np.array(app.find_cached_vector(cached_sid, "ri"), dtype=float)
    n_arch = float(-np.polyfit(np.log(sw), np.log(ri), 1)[0])
    assert n_arch != pytest.approx(-1.0, abs=1e-6)
    assert n_arch == pytest.approx(1.85, abs=1e-3)


def test_unmatched_role_names_the_alias_and_the_candidates(cached_sid: str) -> None:
    """Zero matches must fail loudly, not return an empty list."""
    with app.SESSION_DATA_CACHE_LOCK:
        app.SESSION_DATA_CACHE[cached_sid]["flat_vectors"] = {"depth_ft": [1.0, 2.0]}
    with pytest.raises(app.VectorLookupError) as excinfo:
        app.find_cached_vector(cached_sid, "ri")
    message = str(excinfo.value)
    assert "ri" in message
    assert "depth_ft" in message


def test_ambiguous_match_raises_instead_of_first_match_wins(cached_sid: str) -> None:
    """Two different columns accepted for one role is an error, not a coin flip."""
    with app.SESSION_DATA_CACHE_LOCK:
        app.SESSION_DATA_CACHE[cached_sid]["flat_vectors"] = _flat_vectors(
            {"resistivity index": [9.0, 8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0]}
        )
    with pytest.raises(app.VectorLookupError, match="(?i)ambiguous|matched"):
        app.find_cached_vector(cached_sid, "ri")


def test_duplicate_keys_holding_the_same_vector_are_not_ambiguous(cached_sid: str) -> None:
    """The qualified and bare keys for one column must resolve, not collide."""
    assert app.find_cached_vector(cached_sid, "sw") == SW_VALUES


def test_unknown_role_raises(cached_sid: str) -> None:
    with pytest.raises(app.VectorLookupError, match="(?i)unknown vector role"):
        app.find_cached_vector(cached_sid, "not_a_declared_role")


def test_identical_vectors_are_rejected_before_regression() -> None:
    """Element-wise identity means one column was resolved for both axes."""
    vector = np.array(SW_VALUES, dtype=float)
    with pytest.raises(app.VectorLookupError, match="(?i)same column|itself"):
        app.assert_independent_vectors(vector, vector.copy(), "Sw", "RI")


def test_perfectly_correlated_vectors_are_rejected() -> None:
    """A scaled copy still correlates at exactly 1.0 — same measurement."""
    sw = np.array(SW_VALUES, dtype=float)
    with pytest.raises(app.VectorLookupError, match="(?i)correlate"):
        app.assert_independent_vectors(sw, sw * 3.0, "Sw", "RI")


def test_genuine_sw_ri_pair_passes_the_guard() -> None:
    """A real Archie pair is monotonic but not linearly dependent — must pass."""
    sw = np.array(SW_VALUES, dtype=float)
    ri = np.array(RI_VALUES, dtype=float)
    assert app.assert_independent_vectors(sw, ri, "Sw", "RI") is None
