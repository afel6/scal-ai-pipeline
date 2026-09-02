import os
import logging
import chromadb
import uuid

_logger = logging.getLogger("prc-rag")

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
    def __init__(self, persist_directory: str = None):
        # When no explicit path is given, land the store on Render's persistent
        # disk (DB_DIR=/data) so vectors survive deploys/restarts. The source dir
        # on Render is ephemeral, so the old "./chroma_db" default was wiped on
        # every deploy. Falls back to ./chroma_db for local runs.
        if persist_directory is None:
            persist_directory = default_persist_dir()
        self.client = chromadb.PersistentClient(path=persist_directory)
        
        self.collection = self.client.get_or_create_collection(
            name="historical_scal_data",
            metadata={"hnsw:space": "cosine"} 
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
        
        try:
            results = self.collection.query(
                query_texts=[query_text],
                n_results=n_results,
                where=where_filter
            )
        except Exception as e:
            _logger.error(f"Metadata filtered query failed: {e}. Falling back to semantic search.")
            try:
                # Fallback in case metadata fields are missing in legacy DB
                results = self.collection.query(
                    query_texts=[f"Porosity near {current_porosity} and Permeability near {current_perm} mD"],
                    n_results=n_results
                )
            except Exception:
                return []
        
        analog_wells = []
        if results and results.get('documents') and len(results['documents']) > 0:
            for i in range(len(results['documents'][0])):
                analog_wells.append({
                    "id": results['ids'][0][i],
                    "context": results['documents'][0][i],
                    "historical_data": results['metadatas'][0][i]
                })
        return analog_wells
