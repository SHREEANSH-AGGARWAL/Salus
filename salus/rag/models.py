"""
RAG layer data models.

Pydantic models for the retrieval-augmented generation system.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RetrievedChunk(BaseModel):
    """A single retrieved chunk from the knowledge index.

    Returned by KnowledgeIndex.query() ranked by relevance score.
    """

    text: str = Field(..., description="The retrieved text content")
    source: str = Field(..., description="Source file path (relative to data/)")
    score: float = Field(..., ge=0.0, le=1.0, description="Relevance score (1.0 = perfect match)")
    chunk_index: int = Field(0, ge=0, description="Chunk position within source document")


class IndexStats(BaseModel):
    """Statistics about the current state of the knowledge index."""

    total_chunks: int = Field(0, ge=0, description="Total chunks stored in the index")
    sources: list[str] = Field(default_factory=list, description="All indexed source files")
    embedding_model: str = Field("", description="Model used for embeddings")
    persist_dir: str = Field("", description="ChromaDB persistence directory")
