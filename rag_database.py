import hashlib
import logging
import os
import re
import uuid

import chromadb
from chromadb.api.types import EmbeddingFunction

_logger = logging.getLogger("prc-rag")


class LocalHashEmbedding(EmbeddingFunction):
    """Deterministic local embedding — no model download, no network.

    chromadb's DefaultEmbeddingFunction fetches an ONNX MiniLM model from S3 on
    first use; CI's egress guard caught that download on a fresh runner (locally
    the cached model hid it). Until the embedding migration picks a real local
    model on the Ollama machine, the store embeds with a hashed bag-of-words
    (the same construction as the hub's LocalEmbedder fallback). Cosine
    similarity is meaningful, if crude; every vector is reproducible.
    """
    DIM = 256

    def __call__(self, input):
        return [self._vec(t) for t in input]

    def _vec(self, text):
        v = [0.0] * self.DIM
        for tok in re.findall(r"[a-z0-9\+\.]+", str(text).lower()):
            v[int(hashlib.md5(tok.encode()).hexdigest(), 16) % self.DIM] += 1.0
        norm = sum(x * x for x in v) ** 0.5 or 1.0
        return [x / norm for x in v]

    def name(self):
        return "prc-local-hash-256"

    def get_config(self):
        return {}

    @classmethod
    def build_from_config(cls, config):
        return cls()

    @staticmethod
    def validate_config(config):
        return None

    def default_space(self):
        return "cosine"


def default_persist_dir() -> str:
    """The vector store the app owns.

    A CHROMA_DIR set in the environment at call time wins (tests and operators
    redirect the store that way); otherwise settings.CHROMA_DIR. A relative
    value is anchored to the repo, never to the CWD (D1).
    """
    from config import REPO_ROOT, settings
    raw = os.environ.get("CHROMA_DIR") or settings.CHROMA_DIR
    return raw if os.path.isabs(raw) else str((REPO_ROOT / raw).resolve())


class RAGDatabase:
    """
    Local Vector Database (ChromaDB) for Storing and Retrieving Historical Well Data.
    """
    def __init__(self, persist_directory: str = None, embedding_function=None):
        # When no explicit path is given, land the store on Render's persistent
        # disk (DB_DIR=/data) so vectors survive deploys/restarts. The source dir
        # on Render is ephemeral, so the old "./chroma_db" default was wiped on
        # every deploy. Falls back to ./chroma_db for local runs.
        if persist_directory is None:
            persist_directory = default_persist_dir()
        self.client = chromadb.PersistentClient(path=persist_directory)
        # Explicit, local embedder: never chromadb's downloading default.
        self.embedding_function = embedding_function or LocalHashEmbedding()
        self.collection = self.client.get_or_create_collection(
            name="historical_scal_data",
            metadata={"hnsw:space": "cosine"},
            embedding_function=self.embedding_function,
        )

    def ingest_report(self, well_id: str, scal_data: dict, report_text: str):
        doc_id = str(uuid.uuid4())
        # Standardize keys to lowercase for robust metadata filtering
        clean_scal_data = {k.lower(): v for k, v in scal_data.items()}
        
        self.collection.add(
            documents=[report_text],
            metadatas=[clean_scal_data],
            ids=[f"{well_id}_{doc_id}"]
        )
        _logger.info("Vectorized and stored well %s in ChromaDB.", well_id)

    def query_analog_wells(self, current_porosity: float, current_perm: float, n_results=3) -> list:
        # Instead of just relying on semantic text search, we use strict numerical metadata bounds
        # to filter for wells that are physically similar (+/- 20% on porosity, +/- 50% on permeability)
        query_text = "Analog carbonate well technical report and SCAL interpretation."
        
        where_filter = {
            "$and": [
                {"porosity": {"$gte": current_porosity * 0.8}},
                {"porosity": {"$lte": current_porosity * 1.2}},
                {"permeability": {"$gte": current_perm * 0.5}},
                {"permeability": {"$lte": current_perm * 1.5}}
            ]
        }
        
        # A failed filtered query raises to the caller (hybrid_search marks the
        # result ``vector_unavailable``). It used to fall back to an UNFILTERED
        # semantic query and return those hits in the same "analog well" shape —
        # a well outside the +/-20%/50% window labelled as physically similar —
        # and, when that failed too, returned [] as if nothing matched (D3.1).
        # (Missing metadata fields do not raise in chromadb: they simply do not
        # match, so the legacy-DB rationale for the fallback never applied.)
        results = self.collection.query(
            query_texts=[query_text],
            n_results=n_results,
            where=where_filter
        )
        
        analog_wells = []
        if results and results.get('documents') and len(results['documents']) > 0:
            for i in range(len(results['documents'][0])):
                analog_wells.append({
                    "id": results['ids'][0][i],
                    "context": results['documents'][0][i],
                    "historical_data": results['metadatas'][0][i]
                })
        return analog_wells
