from typing import List, Dict, Any

import json
import os

import chromadb
from chromadb.config import Settings
from chromadb.utils import embedding_functions


CATALOG_COLLECTION_NAME = "munich_data_catalog"
EMBEDDING_MODEL_NAME = "text-embedding-3-small"


def get_chroma_client(persist_directory: str = ".chroma") -> chromadb.ClientAPI:
    """
    Create or return a Chroma client.

    The default is a local persistent client in a `.chroma` directory.
    """
    client = chromadb.PersistentClient(
        path=persist_directory,
        settings=Settings(anonymized_telemetry=False),
    )
    return client


def _get_embedding_function():
    """
    Return a client-side embedding function backed by OpenAI embeddings.

    We use `text-embedding-3-small`, which is multilingual and suitable for
    both German dataset metadata and English user queries.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Please configure it in your environment or .env file."
        )

    return embedding_functions.OpenAIEmbeddingFunction(
        api_key=api_key,
        model_name=EMBEDDING_MODEL_NAME,
    )


def get_or_create_catalog_collection(
    client: chromadb.ClientAPI, collection_name: str = CATALOG_COLLECTION_NAME
):
    """
    Return the catalog collection, creating it if necessary.

    IMPORTANT: We do not persist any embedding function configuration in Chroma.
    The collection remains "dumb", and we handle embeddings entirely client-side.
    This avoids embedding-function configuration conflicts.
    """
    try:
        collection = client.get_collection(collection_name)
    except Exception:
        collection = client.create_collection(collection_name)
    return collection


def upsert_datasets(
    client: chromadb.ClientAPI,
    items: List[Dict[str, Any]],
    collection_name: str = CATALOG_COLLECTION_NAME,
) -> None:
    """
    Upsert a list of dataset metadata dicts into Chroma.

    Each item must contain:
    - id: CKAN package id
    - title: dataset title
    - description: dataset description/notes
    - resources: list of resource dicts (url, format, name)
    - summary: text used for embedding/search

    We compute embeddings client-side using OpenAI and pass them explicitly to
    Chroma to avoid any server-side embedding function configuration.
    """
    collection = get_or_create_catalog_collection(client, collection_name)
    ef = _get_embedding_function()

    ids: List[str] = []
    documents: List[str] = []
    metadatas: List[Dict[str, Any]] = []

    for item in items:
        pkg_id = item.get("id")
        if not pkg_id:
            continue

        ids.append(pkg_id)

        title = item.get("title", "")
        notes = item.get("description", "")
        summary = item.get("summary") or f"{title}\n\n{notes}"
        documents.append(summary)

        # store full metadata (but keep it reasonably small and Chroma-compatible)
        resources = item.get("resources", [])
        # Chroma metadata values must be scalar (str, int, float, bool, None, or SparseVector).
        # We therefore serialize the list of resource dicts into JSON.
        resources_json = json.dumps(resources, ensure_ascii=False)
        metadatas.append(
            {
                "id": pkg_id,
                "title": title,
                "description": notes,
                "resources": resources_json,
            }
        )

    if not ids:
        return

    # Compute embeddings client-side.
    # `OpenAIEmbeddingFunction` expects a list of texts and returns a list
    # of embedding vectors, so we pass all documents at once.
    embeddings = ef(documents)

    collection.upsert(
        ids=ids,
        embeddings=embeddings,
        metadatas=metadatas,
        documents=documents,
    )


def search_datasets(
    client: chromadb.ClientAPI,
    query: str,
    n_results: int = 5,
    collection_name: str = CATALOG_COLLECTION_NAME,
) -> List[Dict[str, Any]]:
    """
    Semantic search over the dataset catalog.

    Returns a list of metadatas sorted by relevance.
    """
    collection = get_or_create_catalog_collection(client, collection_name)
    ef = _get_embedding_function()
    # `OpenAIEmbeddingFunction` returns a list of vectors; take the first.
    query_embedding = ef([query])[0]

    result = collection.query(query_embeddings=[query_embedding], n_results=n_results)

    metadatas = result.get("metadatas", [[]])[0] or []
    return metadatas



