"""
ChromaDB-backed knowledge index for disaster response RAG.

Ingests protocol documents and auto-generated schema docs,
embeds them using sentence-transformers, and exposes a query()
method for semantic retrieval.

Usage:
    index = KnowledgeIndex(config)
    index.ingest_directory(Path("data/protocols"))
    index.ingest_schema_docs()
    chunks = index.query("START triage mass casualty", top_k=3)
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from salus.rag.models import IndexStats, RetrievedChunk

if TYPE_CHECKING:
    from salus.config import RAGConfig

logger = structlog.get_logger()


def _chunk_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """Split text into overlapping chunks by character count.

    Args:
        text: The full text to split.
        chunk_size: Maximum characters per chunk.
        chunk_overlap: Characters of overlap between consecutive chunks.

    Returns:
        List of text chunks.
    """
    if not text.strip():
        return []

    # Split on paragraph boundaries first for cleaner chunks
    paragraphs = re.split(r"\n{2,}", text.strip())
    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        if len(current) + len(para) + 2 <= chunk_size:
            current = (current + "\n\n" + para).strip()
        else:
            if current:
                chunks.append(current)
            # If single paragraph exceeds chunk_size, hard-split it
            if len(para) > chunk_size:
                for i in range(0, len(para), chunk_size - chunk_overlap):
                    piece = para[i : i + chunk_size]
                    if piece.strip():
                        chunks.append(piece.strip())
                current = ""
            else:
                # Start a new chunk with overlap from previous
                if chunks:
                    overlap_text = chunks[-1][-chunk_overlap:] if chunk_overlap else ""
                    current = (overlap_text + "\n\n" + para).strip()
                else:
                    current = para

    if current:
        chunks.append(current)

    return chunks


class KnowledgeIndex:
    """ChromaDB-backed semantic search index for disaster response knowledge.

    Supports two document categories:
    - Static protocol documents (markdown files in data/protocols/, data/drugs/)
    - Dynamic schema docs (auto-generated from Pydantic models at startup)

    The index is persistent (ChromaDB WAL-backed on disk) so embeddings survive
    restarts. Documents are identified by a content hash — re-ingesting an unchanged
    file is a no-op.
    """

    COLLECTION_NAME = "salus_knowledge"

    def __init__(self, config: RAGConfig) -> None:
        self.config = config
        self._client: Any = None
        self._collection: Any = None
        self._embedding_fn: Any = None

    def _ensure_initialized(self) -> None:
        """Lazily initialize ChromaDB client and collection."""
        if self._client is not None:
            return

        try:
            import chromadb
            from chromadb.utils.embedding_functions.sentence_transformer_embedding_function import SentenceTransformerEmbeddingFunction
        except ImportError as e:
            raise RuntimeError(
                "ChromaDB is not installed. Install the AI extras: "
                "pip install 'salus[ai]'"
            ) from e

        self._client = chromadb.PersistentClient(path=self.config.chroma_persist_dir)
        self._embedding_fn = SentenceTransformerEmbeddingFunction(  
            model_name=self.config.embedding_model
        ) # fix this later cant get sentence transformer to work
        self._collection = self._client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            # pyrefly: ignore [bad-argument-type]
            embedding_function=self._embedding_fn,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(
            "knowledge_index_initialized",
            collection=self.COLLECTION_NAME,
            embedding_model=self.config.embedding_model,
            persist_dir=self.config.chroma_persist_dir,
        )

    def ingest_directory(self, path: Path) -> int:
        """Ingest all markdown files in a directory.

        Skips files that haven't changed since last ingestion (content-hash check).

        Args:
            path: Directory containing .md files to ingest.

        Returns:
            Number of new chunks added to the index.
        """
        self._ensure_initialized()
        if not path.exists():
            logger.warning("ingest_dir_not_found", path=str(path))
            return 0

        total_added = 0
        for md_file in sorted(path.glob("*.md")):
            added = self._ingest_file(md_file)
            total_added += added

        logger.info("ingest_directory_complete", path=str(path), chunks_added=total_added)
        return total_added

    def ingest_schema_docs(self) -> int:
        """Ingest auto-generated schema documentation.

        Returns:
            Number of new chunks added.
        """
        from salus.rag.schema_docs import generate_all_schema_docs

        self._ensure_initialized()
        total_added = 0
        for source_name, content in generate_all_schema_docs().items():
            added = self._ingest_text(content, source=source_name)
            total_added += added

        logger.info("schema_docs_ingested", chunks_added=total_added)
        return total_added

    def _ingest_file(self, path: Path) -> int:
        """Ingest a single markdown file. Returns number of new chunks added."""
        content = path.read_text(encoding="utf-8")
        relative = str(path)
        return self._ingest_text(content, source=relative)

    def _ingest_text(self, text: str, source: str) -> int:
        """Chunk and embed a text document. Skips unchanged documents.

        Args:
            text: Full document text.
            source: Source identifier (file path or schema: name).

        Returns:
            Number of new chunks added (0 if document unchanged).
        """
        chunks = _chunk_text(text, self.config.chunk_size, self.config.chunk_overlap)
        if not chunks:
            return 0

        collection = self._collection
        added = 0

        for i, chunk in enumerate(chunks):
            # Content-hash based deduplication
            chunk_id = hashlib.sha256(f"{source}::{i}::{chunk}".encode()).hexdigest()[:32]

            # Check if already indexed with this exact content
            existing = collection.get(ids=[chunk_id])
            if existing["ids"]:
                continue  # Already indexed, skip

            collection.add(
                ids=[chunk_id],
                documents=[chunk],
                metadatas=[{"source": source, "chunk_index": i}],
            )
            added += 1

        if added:
            logger.debug("chunks_added", source=source, count=added)

        return added

    def query(self, text: str, top_k: int | None = None) -> list[RetrievedChunk]:
        """Semantic search over the knowledge index.

        Args:
            text: Query string to search for.
            top_k: Number of top results to return (defaults to config.top_k).

        Returns:
            List of RetrievedChunk objects, ranked by relevance (highest first).
        """
        self._ensure_initialized()
        k = top_k if top_k is not None else self.config.top_k
        collection = self._collection

        try:
            result = collection.query(
                query_texts=[text],
                n_results=min(k, collection.count()),
            )
        except Exception:
            logger.exception("knowledge_query_failed", query=text[:100])
            return []

        chunks: list[RetrievedChunk] = []
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]

        for doc, meta, dist in zip(documents, metadatas, distances):
            # ChromaDB cosine distance: 0 = identical, 2 = opposite
            # Convert to similarity score in [0, 1]
            score = max(0.0, 1.0 - (dist / 2.0))
            chunks.append(
                RetrievedChunk(
                    text=doc,
                    source=meta.get("source", "unknown"),
                    score=round(score, 4),
                    chunk_index=meta.get("chunk_index", 0),
                )
            )

        return chunks

    def stats(self) -> IndexStats:
        """Return statistics about the current index state."""
        self._ensure_initialized()
        collection = self._collection
        all_meta = collection.get(include=["metadatas"])
        sources = sorted({m.get("source", "") for m in all_meta.get("metadatas", [])})
        return IndexStats(
            total_chunks=collection.count(),
            sources=sources,
            embedding_model=self.config.embedding_model,
            persist_dir=self.config.chroma_persist_dir,
        )

    def clear(self) -> None:
        """Delete all documents from the index. Use for testing only."""
        self._ensure_initialized()
        client = self._client
        client.delete_collection(self.COLLECTION_NAME)
        self._collection = None
        self._client = None
        logger.warning("knowledge_index_cleared")
