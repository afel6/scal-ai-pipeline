import os
import shutil

import pytest

# ──────────────────────────────────────────────────────────────────────────────
# CI-safe embedding: ChromaDB's DefaultEmbeddingFunction downloads the
# all-MiniLM-L6-v2 ONNX model (~80 MB) from chroma-onnx-models.s3.amazonaws.com
# on first use. A fresh CI runner has no cache, so the real embedder turns this
# unit test into a network-dependent (and slow/flaky) test.
#
# We replace it with a deterministic, dependency-free embedding function so the
# RAGDatabase ingest/query logic is exercised entirely offline. The numeric
# content of the vectors is irrelevant here — the test asserts on metadata
# filtering and result shaping, not on semantic similarity.
# ──────────────────────────────────────────────────────────────────────────────


class _FakeEmbeddingFunction:
    """A tiny, deterministic embedding function (no model download, no network)."""

    def __call__(self, input):
        # chromadb passes a list of documents (strings); return one vector each.
        if isinstance(input, str):
            input = [input]
        vectors = []
        for text in input:
            # Deterministic 8-dim vector derived from the text — stable across runs.
            base = float(sum(ord(c) for c in text) % 97) + 1.0
            vectors.append([base + i for i in range(8)])
        return vectors

    # Newer chromadb versions call these on EmbeddingFunction instances.
    def name(self):
        return "fake-deterministic"

    @staticmethod
    def build_from_config(config):
        return _FakeEmbeddingFunction()

    def get_config(self):
        return {}


@pytest.fixture
def patch_default_embedding(monkeypatch):
    """Force chromadb to use the offline fake embedder instead of downloading a model."""
    import chromadb.utils.embedding_functions as ef

    monkeypatch.setattr(ef, "DefaultEmbeddingFunction", _FakeEmbeddingFunction)
    # chromadb also resolves the default via api.types in some versions.
    try:
        import chromadb.api.types as types

        monkeypatch.setattr(types, "DefaultEmbeddingFunction", _FakeEmbeddingFunction, raising=False)
    except Exception:
        pass
    yield


def test_rag_database_ingest_and_query(patch_default_embedding, tmp_path):
    # Import after the default embedder is patched so the collection picks it up.
    from rag_database import RAGDatabase

    test_db_path = str(tmp_path / "test_chroma_db")
    if os.path.exists(test_db_path):
        shutil.rmtree(test_db_path)

    db = RAGDatabase(persist_directory=test_db_path)

    # Ingest test data
    well_id = "test_well_01"
    scal_data = {"Porosity": 0.25, "Permeability": 150.0}
    report_text = "This is a test report for a carbonate well with 25% porosity."

    db.ingest_report(well_id, scal_data, report_text)

    # Query test data
    results = db.query_analog_wells(current_porosity=0.25, current_perm=150.0, n_results=1)

    assert len(results) == 1
    assert "test_well_01" in results[0]["id"]
    assert results[0]["historical_data"]["porosity"] == 0.25
    assert "test report" in results[0]["context"]

    # Cleanup
    if os.path.exists(test_db_path):
        shutil.rmtree(test_db_path, ignore_errors=True)
