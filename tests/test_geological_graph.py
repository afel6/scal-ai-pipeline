"""Unit tests for the Geological Knowledge Graph (geological_graph.py).

All tests run against an in-memory SQLite graph (``db_path=":memory:"``) — no
disk, no network, fully deterministic.
"""

import pytest

from geological_graph import GeologicalGraph, NodeType, RelationType


@pytest.fixture
def graph():
    g = GeologicalGraph(db_path=":memory:", seed=False)
    yield g
    g.close()


@pytest.fixture
def populated_graph(graph):
    """A small Sirte-Basin slice: basin -> formations -> lithology/fluid, plus a well."""
    graph.add_relation("Gialo Formation", NodeType.FORMATION,
                       "Sirte Basin", NodeType.BASIN, RelationType.LOCATED_IN)
    graph.add_relation("Gialo Formation", NodeType.FORMATION,
                       "Carbonate", NodeType.LITHOLOGY, RelationType.HAS_LITHOLOGY)
    graph.add_relation("Gialo Formation", NodeType.FORMATION,
                       "Oil", NodeType.FLUID_TYPE, RelationType.CONTAINS_FLUID)
    graph.add_relation("Well-A1", NodeType.WELL,
                       "Gialo Formation", NodeType.FORMATION, RelationType.PENETRATES,
                       metadata={"porosity": 0.22, "permeability": 120.0})
    return graph


def test_add_relation_creates_nodes_and_edge(graph):
    graph.add_relation("Zelten Formation", "Formation",
                       "Sirte Basin", "Basin", "LOCATED_IN")
    names = {n["name"] for n in graph.all_nodes()}
    assert {"Zelten Formation", "Sirte Basin"} <= names


def test_add_relation_is_idempotent(graph):
    for _ in range(3):
        graph.add_relation("F", "Formation", "B", "Basin", "LOCATED_IN",
                           metadata={"v": 1})
    # Re-adding the same edge must not duplicate it.
    conn_result = graph.query_connections("F", depth_limit=1)
    assert len(conn_result["edges"]) == 1


def test_invalid_node_type_rejected(graph):
    with pytest.raises(ValueError):
        graph.add_relation("X", "Galaxy", "Y", "Basin", "LOCATED_IN")


def test_invalid_relation_rejected(graph):
    with pytest.raises(ValueError):
        graph.add_relation("X", "Formation", "Y", "Basin", "ORBITS")


def test_query_connections_depth_one(populated_graph):
    result = populated_graph.query_connections("Gialo Formation", depth_limit=1)
    targets = {e["target"] for e in result["edges"]}
    # 1-hop neighbours of the formation: basin, lithology, fluid (+ inbound well).
    assert "Sirte Basin" in targets
    assert "Carbonate" in targets
    assert "Oil" in targets
    node_names = {n["name"] for n in result["nodes"]}
    assert "Well-A1" in node_names  # inbound PENETRATES edge surfaces the well


def test_query_connections_depth_two_transitive(populated_graph):
    # From the basin, depth 2 reaches lithology/fluid via the formation.
    result = populated_graph.query_connections("Sirte Basin", depth_limit=2)
    reached = {n["name"] for n in result["nodes"]}
    assert {"Gialo Formation", "Carbonate", "Oil", "Well-A1"} <= reached


def test_query_connections_depth_limit_respected(populated_graph):
    shallow = populated_graph.query_connections("Sirte Basin", depth_limit=1)
    reached = {n["name"] for n in shallow["nodes"]}
    # Depth 1 from basin sees the formation, but NOT the lithology 2 hops away.
    assert "Gialo Formation" in reached
    assert "Carbonate" not in reached


def test_query_connections_unknown_node(graph):
    result = graph.query_connections("Nonexistent", depth_limit=2)
    assert result["nodes"] == []
    assert result["edges"] == []


def test_query_connections_rejects_zero_depth(graph):
    with pytest.raises(ValueError):
        graph.query_connections("anything", depth_limit=0)


def test_neighbours_by_relation_filters(populated_graph):
    formations = populated_graph.neighbours_by_relation(
        "Gialo Formation", RelationType.HAS_LITHOLOGY, NodeType.LITHOLOGY)
    assert [n["name"] for n in formations] == ["Carbonate"]


def test_metadata_roundtrip(populated_graph):
    result = populated_graph.query_connections("Well-A1", depth_limit=1)
    penetrates = [e for e in result["edges"] if e["relation"] == "PENETRATES"][0]
    assert penetrates["metadata"]["porosity"] == 0.22


def test_import_relations_bulk(graph):
    rows = [
        ("F1", "Formation", "Sirte Basin", "Basin", "LOCATED_IN"),
        ("F2", "Formation", "Sirte Basin", "Basin", "LOCATED_IN"),
        ("BAD", "NotAType", "Sirte Basin", "Basin", "LOCATED_IN"),  # skipped
    ]
    ingested = graph.import_relations(rows)
    assert ingested == 2


class _StubRetriever:
    """Minimal stand-in for RAGDatabase.query_analog_wells."""

    def __init__(self):
        self.calls = []

    def query_analog_wells(self, current_porosity, current_perm, n_results=3):
        self.calls.append((current_porosity, current_perm, n_results))
        return [{"id": "analog_well_1", "context": "carbonate analog",
                 "historical_data": {"porosity": current_porosity}}]


def test_hybrid_search_combines_graph_and_vector(populated_graph):
    retriever = _StubRetriever()
    result = populated_graph.hybrid_search(
        query_text="Tell me about the Gialo Formation reservoir",
        porous_range=(0.20, 0.24),
        perm_range=(100.0, 140.0),
        retriever=retriever,
        depth_limit=1,
    )
    # Graph side anchored on the matched node name.
    assert "Gialo Formation" in result["graph"]["matched_nodes"]
    assert result["graph"]["subgraphs"]
    # Vector side used the midpoint of each supplied range.
    assert retriever.calls == [(0.22, 120.0, 3)]
    assert result["vector"][0]["id"] == "analog_well_1"


def test_hybrid_search_without_retriever_skips_vector(populated_graph):
    result = populated_graph.hybrid_search(
        query_text="Gialo Formation", porous_range=(0.2, 0.24),
        perm_range=(100.0, 140.0), retriever=None)
    assert result["vector"] == []
    assert "Gialo Formation" in result["graph"]["matched_nodes"]
