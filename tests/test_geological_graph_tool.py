"""Integration test for the hybrid_geological_search chat tool (app.py).

Runs the real PRCChatAssistant._execute_tool path against a freshly seeded
Geological Knowledge Graph and a fresh ChromaDB store, both landed in a pytest
tmp_path (via GRAPH_DB_PATH / CHROMA_DIR), so the default Libyan seed data is
exercised hermetically without touching the repo-root stores. The ChromaDB
default embedder is replaced with a deterministic offline fake (same pattern
as tests/test_rag_database.py) so no model download is required.
"""

import json

import pytest

from app import PRCChatAssistant
from config import settings


class _FakeEmbeddingFunction:
    """A tiny, deterministic embedding function (no model download, no network)."""

    def __call__(self, input):
        if isinstance(input, str):
            input = [input]
        vectors = []
        for text in input:
            base = float(sum(ord(c) for c in text) % 97) + 1.0
            vectors.append([base + i for i in range(8)])
        return vectors

    def name(self):
        return "fake-deterministic"

    @staticmethod
    def build_from_config(config):
        return _FakeEmbeddingFunction()

    def get_config(self):
        return {}


@pytest.fixture
def hermetic_stores(tmp_path, monkeypatch):
    """Isolate the graph SQLite file and the Chroma vector store in tmp_path."""
    monkeypatch.setattr(settings, "GRAPH_DB_PATH", str(tmp_path / "geological_graph.sqlite"))
    monkeypatch.setenv("CHROMA_DIR", str(tmp_path))

    import chromadb.utils.embedding_functions as ef
    monkeypatch.setattr(ef, "DefaultEmbeddingFunction", _FakeEmbeddingFunction)
    try:
        import chromadb.api.types as types
        monkeypatch.setattr(types, "DefaultEmbeddingFunction", _FakeEmbeddingFunction, raising=False)
    except Exception:
        pass
    yield tmp_path


class DummyCall:
    def __init__(self, name, args):
        self.name = name
        self.args = args


def test_hybrid_geological_search_execution(hermetic_stores):
    # Pre-ingest one analog well whose petrophysics sit inside the query window
    # (midpoints 0.22 / 120 mD), so the vector half of the answer is populated.
    from rag_database import RAGDatabase
    rag = RAGDatabase()
    rag.ingest_report(
        "analog_well_gialo",
        {"Porosity": 0.22, "Permeability": 120.0},
        "Carbonate analog well in the Sirte Basin with SCAL interpretation.",
    )

    assistant = PRCChatAssistant(keys=["DUMMY_KEY"])
    call = DummyCall("hybrid_geological_search", {
        "query_text": "Analog study for the Gialo Formation in the Sirte Basin",
        "porous_low": 0.20,
        "porous_high": 0.24,
        "perm_low": 100.0,
        "perm_high": 140.0,
        "depth_limit": 1,
        "n_results": 3,
    })

    res_list = list(assistant._execute_tool(call))
    assert len(res_list) > 0
    is_final, result = res_list[-1]
    assert is_final is True

    payload = json.loads(result)
    assert "graph" in payload
    assert "vector" in payload

    # Graph side is anchored on the seeded default Libyan entities.
    matched = payload["graph"]["matched_nodes"]
    assert "Gialo Formation" in matched
    assert "Sirte Basin" in matched
    assert payload["graph"]["subgraphs"], "expected traversed subgraphs for matched nodes"

    # Seeded relations surface in the traversal around the formation.
    gialo_subgraph = next(
        sg for sg in payload["graph"]["subgraphs"] if sg["root"] == "Gialo Formation"
    )
    relations = {e["relation"] for e in gialo_subgraph["edges"]}
    assert {"LOCATED_IN", "HAS_LITHOLOGY", "CONTAINS_FLUID", "PENETRATES"} <= relations

    # Vector side found the pre-ingested analog well.
    assert len(payload["vector"]) >= 1
    assert any("analog_well_gialo" in w["id"] for w in payload["vector"])

    # Markdown formatting renders the matched entities and analog wells.
    fmt = assistant._format_tool_response("hybrid_geological_search", call.args, result)
    assert "Hybrid Geological Search" in fmt
    assert "Gialo Formation" in fmt
    assert "LOCATED_IN" in fmt
    assert "analog_well_gialo" in fmt
