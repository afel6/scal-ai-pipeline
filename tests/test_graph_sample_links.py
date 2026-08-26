"""Well -[HAS_SAMPLE]-> Sample linkage in the geological graph.

Unit tests run in-memory; the integration tests run the real extraction on a
lab fixture and assert the samples land in the graph.
"""

from pathlib import Path

import pytest

from geological_graph import GeologicalGraph, NodeType, RelationType


@pytest.fixture
def graph():
    g = GeologicalGraph(db_path=":memory:", seed=False)
    yield g
    g.close()


def test_link_samples_creates_well_sample_edges(graph):
    n = graph.link_samples(
        "T1-31",
        {"MICP_TestA": {"pressure": [1, 2]}, "MICP_TestB": {"pressure": [3]}},
        data_type="MICP",
        source_file="micp_t1-31.xls",
    )
    assert n == 2

    sub = graph.query_connections("T1-31", depth_limit=1)
    names = {node["name"] for node in sub["nodes"]}
    assert {"T1-31/micp_t1-31/MICP_TestA", "T1-31/micp_t1-31/MICP_TestB"} <= names
    assert {e["relation"] for e in sub["edges"]} == {"HAS_SAMPLE"}
    meta = sub["edges"][0]["metadata"]
    assert meta["data_type"] == "MICP"
    assert meta["source_file"] == "micp_t1-31.xls"


def test_same_sheet_name_across_files_and_wells_does_not_collide(graph):
    # Two different lab files for the SAME well, both with the generic CSV
    # sheet name — both samples and both provenances must survive.
    graph.link_samples("T1-31", {"Sheet1": {}}, "MICP", "t1-31_micp.csv")
    graph.link_samples("T1-31", {"Sheet1": {}}, "KR", "t1-31_kr.csv")
    # And the same sheet on a different well.
    graph.link_samples("B2-59", {"Sheet1": {}}, "KR", "b2-59_kr.csv")

    sub = graph.query_connections("T1-31", depth_limit=1)
    t1_samples = {n["name"] for n in sub["nodes"] if n["type"] == "Sample"}
    assert t1_samples == {"T1-31/t1-31_micp/Sheet1", "T1-31/t1-31_kr/Sheet1"}
    data_types = {e["metadata"]["data_type"] for e in sub["edges"]}
    assert data_types == {"MICP", "KR"}


def test_relink_same_file_is_idempotent(graph):
    graph.link_samples("T1-31", {"Sheet1": {}}, "KR", "t1-31_kr.csv")
    graph.link_samples("T1-31", {"Sheet1": {}}, "KR", "t1-31_kr.csv")
    samples = [n for n in graph.all_nodes() if n["type"] == "Sample"]
    assert len(samples) == 1
    sub = graph.query_connections("T1-31", depth_limit=1)
    assert len(sub["edges"]) == 1


def test_provisional_or_empty_well_is_skipped(graph):
    assert graph.link_samples("PROVISIONAL WELL", {"S1": {}}, "KR") == 0
    assert graph.link_samples("", {"S1": {}}, "KR") == 0
    assert graph.all_nodes() == []


def test_sample_type_valid_in_vocabulary():
    assert NodeType.SAMPLE.value == "Sample"
    assert RelationType.HAS_SAMPLE.value == "HAS_SAMPLE"


@pytest.fixture
def fixture_path():
    p = Path(__file__).parent / "fixtures" / "Mercury Injection Well T1-31.xls"
    if not p.exists():
        pytest.skip("MICP fixture not present")
    return p


@pytest.fixture
def graph_db(tmp_path, monkeypatch):
    from config import settings
    db = tmp_path / "graph.sqlite"
    monkeypatch.setattr(settings, "GRAPH_DB_PATH", str(db))
    return db


def test_extraction_registers_samples_in_graph(fixture_path, graph_db):
    """extract_file_data on a real lab fixture links samples to well T1-31."""
    from scal_file_handler import extract_file_data
    result = extract_file_data(str(fixture_path))
    assert result.get("row_count", 0) > 0

    g = GeologicalGraph(db_path=str(graph_db), seed=False)
    try:
        # Assert on the specific extracted well — the graph is seeded with
        # default wells (Well-A1, ...) so a bare "any well exists" is vacuous.
        sub = g.query_connections("T1-31", depth_limit=1)
        has_sample_edges = [e for e in sub["edges"] if e["relation"] == "HAS_SAMPLE"]
        assert has_sample_edges, "no HAS_SAMPLE edge registered for well T1-31"
        assert all(
            e["metadata"]["source_file"] == fixture_path.name for e in has_sample_edges
        )
    finally:
        g.close()


def test_extraction_reupload_is_idempotent(fixture_path, graph_db):
    """Processing the same lab file twice must not duplicate graph entries."""
    from scal_file_handler import extract_file_data
    extract_file_data(str(fixture_path))

    g = GeologicalGraph(db_path=str(graph_db), seed=False)
    try:
        first = len(g.query_connections("T1-31", depth_limit=1)["edges"])
    finally:
        g.close()

    extract_file_data(str(fixture_path))
    g = GeologicalGraph(db_path=str(graph_db), seed=False)
    try:
        assert len(g.query_connections("T1-31", depth_limit=1)["edges"]) == first
    finally:
        g.close()


def test_temp_path_upload_uses_original_filename(fixture_path, graph_db, tmp_path):
    """Uploads reach extraction as temp paths; the well and provenance must
    come from the original filename, never the random temp stem."""
    import shutil
    from scal_file_handler import extract_file_data

    tmp_copy = tmp_path / "tmpxaws8hw4.xls"  # simulates NamedTemporaryFile
    shutil.copy(fixture_path, tmp_copy)
    extract_file_data(str(tmp_copy), original_filename=fixture_path.name)

    g = GeologicalGraph(db_path=str(graph_db), seed=False)
    try:
        wells = {n["name"] for n in g.all_nodes() if n["type"] == "Well"}
        assert "T1-31" in wells
        assert not any(w.upper().startswith("TMP") for w in wells)
        sub = g.query_connections("T1-31", depth_limit=1)
        assert all(
            e["metadata"]["source_file"] == fixture_path.name
            for e in sub["edges"] if e["relation"] == "HAS_SAMPLE"
        )
    finally:
        g.close()
