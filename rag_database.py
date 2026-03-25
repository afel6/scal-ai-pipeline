import chromadb
import uuid

class RAGDatabase:
    """
    Local Vector Database (ChromaDB) for Storing and Retrieving Historical Well Data.
    """
    def __init__(self, persist_directory="./chroma_db"):
        self.client = chromadb.PersistentClient(path=persist_directory)
        
        self.collection = self.client.get_or_create_collection(
            name="historical_scal_data",
            metadata={"hnsw:space": "cosine"} 
        )

    def ingest_report(self, well_id: str, scal_data: dict, report_text: str):
        doc_id = str(uuid.uuid4())
        
        self.collection.add(
            documents=[report_text],
            metadatas=[scal_data],
            ids=[f"{well_id}_{doc_id}"]
        )
        print(f"✅ Successfully vectorized and stored {well_id} in ChromaDB.")

    def query_analog_wells(self, current_porosity: float, current_perm: float, n_results=3) -> list:
        query_text = f"Searching for analog carbonate wells with Porosity near {current_porosity} and Permeability near {current_perm} mD."
        
        # Basic try/catch for empty database querying
        try:
            results = self.collection.query(
                query_texts=[query_text],
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
