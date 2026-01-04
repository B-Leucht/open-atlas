"""
Vector Store for semantic search over datasets
Uses ChromaDB with OpenAI embeddings
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.config import Settings
from chromadb.utils import embedding_functions

logger = logging.getLogger(__name__)

CATALOG_COLLECTION_NAME = "munich_data_catalog"
EMBEDDING_MODEL_NAME = "text-embedding-3-small"


class VectorStore:
    """
    Semantic search over dataset catalog using ChromaDB.
    Integrates with the data layer for automatic sync.
    """

    def __init__(self, persist_directory: str = None):
        if persist_directory is None:
            # Default to backend/data/.chroma
            persist_directory = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                'data', '.chroma'
            )

        os.makedirs(persist_directory, exist_ok=True)
        self.persist_directory = persist_directory
        self._client = None
        self._embedding_fn = None

    @property
    def client(self) -> chromadb.ClientAPI:
        """Lazy-load ChromaDB client"""
        if self._client is None:
            self._client = chromadb.PersistentClient(
                path=self.persist_directory,
                settings=Settings(anonymized_telemetry=False),
            )
        return self._client

    @property
    def embedding_fn(self):
        """Get OpenAI embedding function"""
        if self._embedding_fn is None:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "OPENAI_API_KEY not set. Configure it in environment or .env file."
                )
            self._embedding_fn = embedding_functions.OpenAIEmbeddingFunction(
                api_key=api_key,
                model_name=EMBEDDING_MODEL_NAME,
            )
        return self._embedding_fn

    def get_collection(self, name: str = CATALOG_COLLECTION_NAME):
        """Get or create a collection"""
        try:
            return self.client.get_collection(name)
        except Exception:
            return self.client.create_collection(name)

    def upsert_datasets(self, datasets: List[Dict[str, Any]],
                        collection_name: str = CATALOG_COLLECTION_NAME) -> int:
        """
        Upsert dataset metadata into vector store.
        Returns count of items upserted.
        """
        collection = self.get_collection(collection_name)

        ids = []
        documents = []
        metadatas = []

        for item in datasets:
            pkg_id = item.get("id") or item.get("external_id")
            if not pkg_id:
                continue

            ids.append(str(pkg_id))

            title = item.get("title", "")
            notes = item.get("description", "")
            summary = item.get("summary") or f"{title}\n\n{notes}"
            documents.append(summary)

            # Prepare resources for storage
            resources = item.get("resources", [])
            if resources and isinstance(resources[0], dict):
                # Already dict format
                resources_json = json.dumps(resources, ensure_ascii=False)
            else:
                # Might be DatasetResource objects
                resources_json = json.dumps(
                    [r.to_dict() if hasattr(r, 'to_dict') else r for r in resources],
                    ensure_ascii=False
                )

            metadatas.append({
                "id": pkg_id,
                "title": title,
                "description": notes[:1000] if notes else "",
                "resources": resources_json,
                "has_geometry": item.get("has_geometry", False),
                "is_district_specific": item.get("is_district_specific", False),
            })

        if not ids:
            return 0

        # Compute embeddings
        embeddings = self.embedding_fn(documents)

        collection.upsert(
            ids=ids,
            embeddings=embeddings,
            metadatas=metadatas,
            documents=documents,
        )

        logger.info(f"Upserted {len(ids)} datasets to vector store")
        return len(ids)

    def search(self, query: str, n_results: int = 5,
               collection_name: str = CATALOG_COLLECTION_NAME,
               filters: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """
        Semantic search over datasets.
        Returns list of metadata dicts sorted by relevance.
        """
        collection = self.get_collection(collection_name)

        # Get query embedding
        query_embedding = self.embedding_fn([query])[0]

        # Build where clause if filters provided
        where = None
        if filters:
            where = filters

        result = collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where=where
        )

        metadatas = result.get("metadatas", [[]])[0] or []
        return metadatas

    def sync_from_database(self, db=None) -> int:
        """
        Sync vector store from the data layer database.
        Returns count of datasets synced.
        """
        if db is None:
            from data.database import Database
            db = Database()

        datasets = db.get_datasets()

        if not datasets:
            logger.warning("No datasets found in database. Run sync first.")
            return 0

        items = []
        for ds in datasets:
            # Handle resources - they might be DatasetResource objects or dicts
            resources = []
            for r in ds.resources:
                if hasattr(r, 'to_dict'):
                    resources.append(r.to_dict())
                elif isinstance(r, dict):
                    resources.append(r)
                else:
                    resources.append({'url': str(r)})

            items.append({
                "id": ds.external_id,
                "title": ds.title,
                "description": ds.description or "",
                "resources": resources,
                "has_geometry": ds.has_geometry,
                "is_district_specific": ds.is_district_specific,
            })

        return self.upsert_datasets(items)

    def clear(self, collection_name: str = CATALOG_COLLECTION_NAME):
        """Clear all data from a collection"""
        try:
            self.client.delete_collection(collection_name)
            logger.info(f"Cleared collection: {collection_name}")
        except Exception as e:
            logger.warning(f"Could not clear collection: {e}")


# Convenience functions for backward compatibility
def get_chroma_client(persist_directory: str = None) -> chromadb.ClientAPI:
    """Get a ChromaDB client (for legacy code)"""
    store = VectorStore(persist_directory)
    return store.client


def search_datasets(client: chromadb.ClientAPI, query: str, n_results: int = 5) -> List[Dict[str, Any]]:
    """Search datasets using legacy client (for backward compatibility)"""
    store = VectorStore()
    store._client = client
    return store.search(query, n_results)
