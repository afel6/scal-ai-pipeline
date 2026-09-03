"""D3 0.4 / D3.1 — the vector store never phones home for an embedding model.

CI's egress guard caught chromadb's DEFAULT embedding function downloading an
ONNX model from S3 on a fresh runner (test_rag_database / the hybrid search
tool); locally the model was cached, so the egress was invisible for months.
RAGDatabase now takes an explicit embedding function and defaults to a local,
deterministic hashing embedder (no download, no network) until the embedding
migration picks a real local model on the Ollama machine.
"""
import pathlib

import rag_database


def test_default_embedder_is_local_and_deterministic():
    fn = rag_database.LocalHashEmbedding()
    a = fn(["porosity and permeability of a carbonate core"])
    b = fn(["porosity and permeability of a carbonate core"])
    assert len(a) == 1 and len(a[0]) == rag_database.LocalHashEmbedding.DIM
    assert list(a[0]) == list(b[0])
    assert list(fn(["a different sentence"])[0]) != list(a[0])


def test_store_is_built_with_the_local_embedder_by_default(tmp_path):
    db = rag_database.RAGDatabase(persist_directory=str(tmp_path / "chroma"))
    assert isinstance(db.embedding_function, rag_database.LocalHashEmbedding)


def test_ingest_and_query_make_no_network_call(tmp_path):
    """The autouse egress fixture fails this test if chromadb tries to fetch a model."""
    db = rag_database.RAGDatabase(persist_directory=str(tmp_path / "chroma"))
    db.ingest_report("W-1", {"porosity": 0.2, "permeability": 100.0}, "carbonate analog well, moderate porosity")
    hits = db.query_analog_wells(current_porosity=0.2, current_perm=100.0, n_results=1)
    assert hits and hits[0]["historical_data"]["porosity"] == 0.2


def test_an_explicit_embedder_is_honoured(tmp_path):
    class Fake:
        calls = 0

        def __call__(self, input):
            Fake.calls += len(input)
            return [[0.5] * 8 for _ in input]

        def name(self):
            return "fake"
    db = rag_database.RAGDatabase(persist_directory=str(tmp_path / "chroma"), embedding_function=Fake())
    db.ingest_report("W-2", {"porosity": 0.1, "permeability": 5.0}, "text")
    assert Fake.calls >= 1
