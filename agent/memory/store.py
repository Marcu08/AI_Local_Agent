"""Vector store locale (ChromaDB) — import lazy, pieno utilizzo in Fase 2."""

from __future__ import annotations

from pathlib import Path


class VectorStoreUnavailableError(RuntimeError):
    """ChromaDB non installato: il vector store non è utilizzabile."""


class VectorStore:
    """Wrappatore sottile di ChromaDB PersistentClient (import dentro i metodi)."""

    def __init__(self, persist_dir: str | Path, collection: str = "memory") -> None:
        self._persist_dir = str(persist_dir)
        self._collection_name = collection

    def _collection(self):  # type: ignore[no-untyped-def]
        try:
            import chromadb  # pyright: ignore[reportMissingImports]  # lazy: opzionale in Fase 1
        except ImportError as e:
            raise VectorStoreUnavailableError(
                "chromadb non installato: pip install chromadb (previsto in Fase 2)."
            ) from e
        client = chromadb.PersistentClient(path=self._persist_dir)
        return client.get_or_create_collection(self._collection_name)

    @staticmethod
    def chunks(text: str, size: int = 1000, overlap: int = 150) -> list[str]:
        """Splitting testuale semplice per chunk indicizzabili (pur python, testabile)."""
        if size < 1:
            raise ValueError("size deve essere >= 1")
        if overlap < 0 or overlap >= size:
            raise ValueError("overlap deve essere >= 0 e < size")
        if not text:
            return []
        step = size - overlap
        pieces: list[str] = []
        start = 0
        while start < len(text):
            pieces.append(text[start : start + size])
            if start + size >= len(text):
                break
            start += step
        return pieces

    def add(
        self,
        ids: list[str],
        documents: list[str],
        metadatas: list[dict] | None = None,  # type: ignore[type-arg]
    ) -> None:
        self._collection().add(ids=ids, documents=documents, metadatas=metadatas)

    def query(self, query_texts: list[str], n_results: int = 5) -> dict:  # type: ignore[type-arg]
        return self._collection().query(query_texts=query_texts, n_results=n_results)
