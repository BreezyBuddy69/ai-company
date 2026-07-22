"""Long-term memory: pgvector-backed storage + similarity search.

Embeddings are computed locally via fastembed (ONNX runtime, no torch — a
deliberate choice on a resource-constrained single VPS) using the same
sentence-transformers/all-MiniLM-L6-v2 model referenced in
model_registry.yaml, so it never costs a paid API call.
"""

from __future__ import annotations

import uuid
from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Memory

EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


@lru_cache
def _embedder():
    # Imported lazily: fastembed downloads/loads the ONNX model on first use,
    # which is unnecessary overhead for code paths (like most unit tests)
    # that never touch memory.
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=EMBEDDING_MODEL_NAME)


def embed(text: str) -> list[float]:
    vectors = list(_embedder().embed([text]))
    return vectors[0].tolist()


def write_memory(
    db: Session,
    *,
    content: str,
    memory_type: str,
    source_agent_id: uuid.UUID | None = None,
    metadata: dict | None = None,
) -> Memory:
    memory = Memory(
        content=content,
        embedding=embed(content),
        memory_type=memory_type,
        source_agent_id=source_agent_id,
        metadata_=metadata or {},
    )
    db.add(memory)
    db.flush()
    return memory


def search_memories(db: Session, query: str, *, top_k: int = 5, memory_type: str | None = None) -> list[Memory]:
    query_vec = embed(query)
    stmt = select(Memory).order_by(Memory.embedding.cosine_distance(query_vec)).limit(top_k)
    if memory_type:
        stmt = stmt.where(Memory.memory_type == memory_type)
    return list(db.scalars(stmt))
