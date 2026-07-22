"""Token optimization: builds the minimal context an agent needs for one call.

Three layers, exactly as specified in the project brief:
  - short-term: last N agent_runs for the active task, kept in Redis
  - long-term: pgvector similarity search over `memories`
  - compressed summaries: once the short-term buffer exceeds
    `short_term_buffer_max_runs`, it's summarized by a free model and stored
    as a new `summary` memory; the raw buffer is then cleared.

Nothing here ever sends a full unbounded history to a model — that's the
whole point.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field

import redis
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.memory import search_memories, write_memory
from app.core.model_router import ModelRouter

_SHORT_TERM_KEY = "shortterm:{task_id}"


@dataclass
class AgentContext:
    relevant_memories: list[str] = field(default_factory=list)
    recent_activity: list[dict] = field(default_factory=list)
    skills_text: str = ""

    def as_prompt_block(self) -> str:
        parts = []
        if self.skills_text:
            parts.append(f"## Relevant skills\n{self.skills_text}")
        if self.relevant_memories:
            joined = "\n".join(f"- {m}" for m in self.relevant_memories)
            parts.append(f"## Relevant long-term memory\n{joined}")
        if self.recent_activity:
            joined = "\n".join(f"- {json.dumps(a, default=str)}" for a in self.recent_activity)
            parts.append(f"## Recent activity on this task\n{joined}")
        return "\n\n".join(parts)


class ContextManager:
    def __init__(self, redis_client: redis.Redis | None = None, router: ModelRouter | None = None):
        self.settings = get_settings()
        self.redis = redis_client or redis.from_url(self.settings.redis_url, decode_responses=True)
        self._router = router  # lazily created if needed for compression

    def _router_or_create(self) -> ModelRouter:
        if self._router is None:
            self._router = ModelRouter()
        return self._router

    def build_context(self, db: Session, *, task_id: uuid.UUID | str, query: str, skills_text: str = "") -> AgentContext:
        memories = search_memories(db, query, top_k=self.settings.memory_top_k)
        recent = self._read_short_term(task_id)
        return AgentContext(
            relevant_memories=[m.content for m in memories],
            recent_activity=recent,
            skills_text=skills_text,
        )

    def record_activity(self, db: Session, *, task_id: uuid.UUID | str, agent_name: str, summary: dict) -> None:
        key = _SHORT_TERM_KEY.format(task_id=task_id)
        self.redis.rpush(key, json.dumps({"agent": agent_name, **summary}, default=str))
        self.redis.expire(key, 60 * 60 * 24)  # 24h TTL — short-term really means short-term

        if self.redis.llen(key) > self.settings.short_term_buffer_max_runs:
            self._compress(db, task_id=task_id, key=key)

    def _read_short_term(self, task_id: uuid.UUID | str) -> list[dict]:
        key = _SHORT_TERM_KEY.format(task_id=task_id)
        return [json.loads(item) for item in self.redis.lrange(key, 0, -1)]

    def _compress(self, db: Session, *, task_id: uuid.UUID | str, key: str) -> None:
        items = [json.loads(item) for item in self.redis.lrange(key, 0, -1)]
        if not items:
            return
        raw = "\n".join(f"- {json.dumps(i, default=str)}" for i in items)
        try:
            result = self._router_or_create().complete(
                system_prompt="You compress agent activity logs into a single dense, factual summary paragraph. "
                              "Keep concrete numbers, decisions, and outcomes. Drop filler.",
                user_prompt=f"Summarize this activity log for task {task_id} in under 120 words:\n{raw}",
            )
            summary_text = result.content.strip()
        except Exception:
            # No model available (e.g. no API key yet) — fall back to a
            # truncated raw join rather than losing the buffer silently.
            summary_text = raw[:800]

        write_memory(
            db,
            content=summary_text,
            memory_type="summary",
            metadata={"task_id": str(task_id), "compressed_from_runs": len(items)},
        )
        db.commit()
        self.redis.delete(key)
