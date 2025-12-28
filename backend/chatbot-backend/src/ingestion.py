from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

import requests
from dotenv import load_dotenv

from .vector_store import get_chroma_client, upsert_datasets


CKAN_BASE_URL = "https://opendata.muenchen.de/api/3/action"
USABLE_FORMATS = {"CSV", "WFS", "GEOJSON", "JSON"}

# Ensure environment variables from `.env` are loaded when running ingestion
load_dotenv()


@dataclass
class DatasetResource:
    name: str
    url: str
    format: str


@dataclass
class DatasetMetadata:
    id: str
    title: str
    description: str
    resources: List[DatasetResource]
    summary: str


def _ckan_get(endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    url = f"{CKAN_BASE_URL}/{endpoint}"
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("success"):
        raise RuntimeError(f"CKAN API error for {endpoint}: {data}")
    return data["result"]


def fetch_all_package_ids() -> List[str]:
    """Fetch list of all CKAN package IDs using /package_list."""
    result = _ckan_get("package_list")
    return list(result)


def batched(iterable: Iterable[Any], batch_size: int) -> Iterable[List[Any]]:
    """Yield lists of up to batch_size elements from iterable."""
    batch: List[Any] = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def fetch_package_metadata(package_id: str) -> Optional[DatasetMetadata]:
    """
    Fetch and normalize metadata for a single CKAN package.

    Returns None if the package has no usable resources.
    """
    try:
        result = _ckan_get("package_show", params={"id": package_id})
    except Exception:
        # Skip problematic packages, but keep ingestion running
        return None

    title = (result.get("title") or "").strip()
    notes = (result.get("notes") or "").strip()
    resources_raw = result.get("resources", []) or []

    resources: List[DatasetResource] = []
    for r in resources_raw:
        fmt = (r.get("format") or "").upper()
        url = (r.get("url") or "").strip()
        name = (r.get("name") or "").strip() or url

        if not url or not fmt:
            continue
        if fmt not in USABLE_FORMATS:
            continue
        resources.append(DatasetResource(name=name, url=url, format=fmt))

    if not resources:
        return None

    # For now we rely on multilingual embeddings in Chroma/OpenAI
    # and keep the summary simple and factual.
    resource_lines = [
        f"- {r.name} ({r.format}) -> {r.url}" for r in resources
    ]
    summary_parts = [
        f"Title: {title}",
        f"Description: {notes}",
        "Resources:",
        *resource_lines,
    ]
    summary = "\n".join(summary_parts)

    return DatasetMetadata(
        id=package_id,
        title=title,
        description=notes,
        resources=resources,
        summary=summary,
    )


def ingest_catalog(
    batch_size: int = 20,
    sleep_between_batches: float = 0.2,
    max_packages: Optional[int] = None,
) -> None:
    """
    Ingest the Munich Open Data catalog metadata into ChromaDB.

    - Fetches all package IDs
    - For each ID, calls package_show
    - Filters for usable formats (CSV, WFS, GeoJSON, JSON)
    - Builds a summary string
    - Upserts into the `munich_data_catalog` Chroma collection
    """
    client = get_chroma_client()
    package_ids = fetch_all_package_ids()

    if max_packages is not None:
        package_ids = package_ids[:max_packages]

    total = len(package_ids)
    print(f"Found {total} package IDs.")

    for idx_batch, id_batch in enumerate(batched(package_ids, batch_size), start=1):
        metadatas: List[DatasetMetadata] = []
        for pkg_id in id_batch:
            meta = fetch_package_metadata(pkg_id)
            if meta is not None:
                metadatas.append(meta)

        if metadatas:
            upsert_datasets(
                client,
                [
                    {
                        "id": m.id,
                        "title": m.title,
                        "description": m.description,
                        "resources": [
                            {
                                "name": r.name,
                                "url": r.url,
                                "format": r.format,
                            }
                            for r in m.resources
                        ],
                        "summary": m.summary,
                    }
                    for m in metadatas
                ],
            )

        done = min(idx_batch * batch_size, total)
        pct = (done / total) * 100 if total else 100
        print(f"Ingested batch {idx_batch}, total {done}/{total} ({pct:.1f}%).")

        time.sleep(sleep_between_batches)


if __name__ == "__main__":
    ingest_catalog()


