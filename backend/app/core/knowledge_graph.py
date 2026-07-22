"""Relationship graph between problems, markets, products, strategies, companies."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import KnowledgeEdge, KnowledgeNode


def get_or_create_node(db: Session, *, type: str, name: str, metadata: dict | None = None) -> KnowledgeNode:
    existing = db.scalar(select(KnowledgeNode).where(KnowledgeNode.type == type, KnowledgeNode.name == name))
    if existing:
        return existing
    node = KnowledgeNode(type=type, name=name, metadata_=metadata or {})
    db.add(node)
    db.flush()
    return node


def link(db: Session, *, from_node: KnowledgeNode, to_node: KnowledgeNode, relation: str, weight: float = 1.0) -> KnowledgeEdge:
    edge = KnowledgeEdge(from_node_id=from_node.id, to_node_id=to_node.id, relation=relation, weight=weight)
    db.add(edge)
    db.flush()
    return edge


def neighbors(db: Session, node: KnowledgeNode) -> list[tuple[KnowledgeEdge, KnowledgeNode]]:
    edges = db.scalars(select(KnowledgeEdge).where(KnowledgeEdge.from_node_id == node.id)).all()
    result = []
    for edge in edges:
        target = db.get(KnowledgeNode, edge.to_node_id)
        if target:
            result.append((edge, target))
    return result
