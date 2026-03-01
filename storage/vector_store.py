"""
YukiShadow - Vector Store (ChromaDB)

Used for:
  - File memory / RAG (FileManagerSkill)
  - Conversation memory
  - Any semantic search use case

Collections are created on-demand. Each skill/feature uses its own collection.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)

# Well-known collection names
COLLECTION_FILES = "files"
COLLECTION_CONVERSATIONS = "conversations"
COLLECTION_NOTES = "notes"


class VectorStore:

    def __init__(self) -> None:
        self._client: Any = None
        self._collections: dict[str, Any] = {}

    async def connect(self) -> None:
        from core.config import settings
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        self._client = await chromadb.AsyncHttpClient(
            host=settings.chroma_host,
            port=settings.chroma_port,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        logger.info(f"VectorStore connected to ChromaDB at {settings.chroma_host}:{settings.chroma_port}")

    async def _get_collection(self, name: str):
        if name not in self._collections:
            self._collections[name] = await self._client.get_or_create_collection(name)
        return self._collections[name]

    async def add(
        self,
        collection: str,
        documents: list[str],
        metadatas: list[dict] | None = None,
        ids: list[str] | None = None,
    ) -> list[str]:
        col = await self._get_collection(collection)
        if ids is None:
            ids = [str(uuid.uuid4()) for _ in documents]
        await col.add(
            documents=documents,
            metadatas=metadatas or [{} for _ in documents],
            ids=ids,
        )
        return ids

    async def query(
        self,
        collection: str,
        text: str,
        n_results: int = 5,
        where: dict | None = None,
    ) -> list[dict]:
        """Returns list of {text, metadata, distance, id}."""
        col = await self._get_collection(collection)
        results = await col.query(
            query_texts=[text],
            n_results=n_results,
            where=where,
        )
        output = []
        for i, doc in enumerate(results["documents"][0]):
            output.append({
                "text": doc,
                "metadata": results["metadatas"][0][i],
                "distance": results["distances"][0][i] if results.get("distances") else None,
                "id": results["ids"][0][i],
            })
        return output

    async def delete(self, collection: str, doc_id: str) -> None:
        col = await self._get_collection(collection)
        await col.delete(ids=[doc_id])

    async def update(
        self,
        collection: str,
        doc_id: str,
        document: str,
        metadata: dict | None = None,
    ) -> None:
        col = await self._get_collection(collection)
        await col.update(
            ids=[doc_id],
            documents=[document],
            metadatas=[metadata or {}],
        )


# Singleton – optional; ChromaDB is not always needed at startup
vector_store = VectorStore()
