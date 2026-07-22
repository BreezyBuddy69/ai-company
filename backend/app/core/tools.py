"""Tool registry available to agents. Every agent config lists which of these
it's permitted to call (`tools:` in its YAML) — the agent runner refuses to
execute anything not on that list.

Two tools hit real, free, keyless public APIs:
  - search_hackernews: Algolia HN Search API (no key required)
  - search_github_issues: GitHub REST search API (works unauthenticated at a
    lower rate limit; set GITHUB_TOKEN in .env for the higher limit)

The rest read/write our own database.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.memory import write_memory
from app.db.models import Agent, FinanceTransaction, Opportunity, Product

HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search"
GITHUB_SEARCH_URL = "https://api.github.com/search/issues"


def search_hackernews(keyword: str, *, hits_per_page: int = 10) -> list[dict[str, Any]]:
    params = {"query": keyword, "tags": "story", "hitsPerPage": hits_per_page}
    with httpx.Client(timeout=15) as client:
        resp = client.get(HN_SEARCH_URL, params=params)
    resp.raise_for_status()
    hits = resp.json().get("hits", [])
    return [
        {
            "title": h.get("title") or h.get("story_title"),
            "url": h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}",
            "points": h.get("points", 0),
            "num_comments": h.get("num_comments", 0),
            "created_at": h.get("created_at"),
            "source": "hackernews",
        }
        for h in hits
        if h.get("title") or h.get("story_title")
    ]


def search_github_issues(keyword: str, *, per_page: int = 10) -> list[dict[str, Any]]:
    settings = get_settings()
    headers = {"Accept": "application/vnd.github+json"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    params = {"q": f"{keyword} in:title,body is:issue", "sort": "reactions", "order": "desc", "per_page": per_page}
    with httpx.Client(timeout=15) as client:
        resp = client.get(GITHUB_SEARCH_URL, params=params, headers=headers)
    resp.raise_for_status()
    items = resp.json().get("items", [])
    return [
        {
            "title": it.get("title"),
            "url": it.get("html_url"),
            "reactions": it.get("reactions", {}).get("total_count", 0),
            "comments": it.get("comments", 0),
            "created_at": it.get("created_at"),
            "source": "github_issues",
        }
        for it in items
    ]


def create_opportunity(
    db: Session,
    *,
    problem: str,
    target_customer: str | None,
    existing_solutions: list[str] | None,
    pain_level: int | None,
    possible_product: str | None,
    revenue_potential: str | None,
    source: str,
    source_url: str | None,
    discovered_by_agent_id: uuid.UUID | None,
) -> Opportunity:
    opp = Opportunity(
        problem=problem,
        target_customer=target_customer,
        existing_solutions=existing_solutions or [],
        pain_level=pain_level,
        possible_product=possible_product,
        revenue_potential=revenue_potential,
        source=source,
        source_url=source_url,
        discovered_by_agent_id=discovered_by_agent_id,
    )
    db.add(opp)
    db.flush()
    write_memory(
        db,
        content=f"Opportunity discovered: {problem} (source: {source})",
        memory_type="fact",
        source_agent_id=discovered_by_agent_id,
        metadata={"opportunity_id": str(opp.id)},
    )
    return opp


def read_opportunities(db: Session, *, status: str | None = None, limit: int = 20) -> list[Opportunity]:
    stmt = select(Opportunity).order_by(Opportunity.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(Opportunity.status == status)
    return list(db.scalars(stmt))


def score_opportunity(db: Session, opportunity_id: uuid.UUID, *, research_score: float, research_notes: str) -> Opportunity:
    opp = db.get(Opportunity, opportunity_id)
    if opp is None:
        raise ValueError(f"opportunity {opportunity_id} not found")
    opp.research_score = research_score
    opp.research_notes = research_notes
    opp.status = "researched"
    db.flush()
    return opp


DECISION_STATUSES = {"approved", "watch", "rejected"}


def decide_opportunity(db: Session, opportunity_id: uuid.UUID, *, decision: str, decision_rationale: str) -> Opportunity:
    if decision not in DECISION_STATUSES:
        raise ValueError(f"decision must be one of {sorted(DECISION_STATUSES)}, got {decision!r}")
    opp = db.get(Opportunity, opportunity_id)
    if opp is None:
        raise ValueError(f"opportunity {opportunity_id} not found")
    opp.status = decision
    opp.decision_rationale = decision_rationale
    db.flush()
    return opp


def record_revenue(db: Session, product_id: uuid.UUID, *, amount_usd: float, description: str | None = None) -> dict[str, Any]:
    """Logs a real revenue transaction and, the moment it's this product's
    first one, clones whichever agent's Product.created_by_agent_id is set —
    the "as soon as one makes money, clone it" policy from core/evolution.py.
    No-ops the clone step (but still logs the revenue) if the product has no
    recorded creator or that agent's already been retired."""
    product = db.get(Product, product_id)
    if product is None:
        raise ValueError(f"product {product_id} not found")

    is_first_revenue = not any(
        t.type == "revenue" for t in db.scalars(select(FinanceTransaction).where(FinanceTransaction.product_id == product.id))
    )
    txn = FinanceTransaction(product_id=product.id, type="revenue", amount_usd=amount_usd, description=description)
    db.add(txn)
    db.flush()

    result: dict[str, Any] = {"transaction_id": str(txn.id)}
    if is_first_revenue and product.created_by_agent_id:
        agent = db.get(Agent, product.created_by_agent_id)
        if agent and agent.status == "active":
            from pathlib import Path

            from app.agents.runner import resolve_agent_dirs
            from app.core.evolution import clone_agent

            config_dir, _, _ = resolve_agent_dirs(get_settings())
            clone = clone_agent(
                db, Path(config_dir), agent,
                mutation_notes=f"first revenue on product '{product.name}' (${amount_usd}) — auto-cloned",
            )
            result["cloned_agent"] = clone.name
    db.commit()
    return result


TOOL_REGISTRY = {
    "search_hackernews": search_hackernews,
    "search_github_issues": search_github_issues,
    "write_memory": write_memory,
    "create_opportunity": create_opportunity,
    "read_opportunities": read_opportunities,
    "score_opportunity": score_opportunity,
    "decide_opportunity": decide_opportunity,
    "record_revenue": record_revenue,
}

# Short, LLM-facing docs — kept separate from docstrings so prompts stay tiny.
TOOL_DESCRIPTIONS = {
    "search_hackernews": {
        "description": "Search Hacker News for a keyword. Returns recent stories with points/comments.",
        "args": {"keyword": "string"},
    },
    "search_github_issues": {
        "description": "Search GitHub issues for a keyword. Returns issues sorted by reaction count.",
        "args": {"keyword": "string"},
    },
    "write_memory": {
        "description": "Save a fact/decision/failure/success to long-term memory.",
        "args": {"content": "string", "memory_type": "decision|failure|success|experiment|fact"},
    },
    "create_opportunity": {
        "description": "Record a newly discovered business opportunity.",
        "args": {
            "problem": "string", "target_customer": "string", "existing_solutions": "string[]",
            "pain_level": "int 1-10", "possible_product": "string", "revenue_potential": "string",
            "source": "string", "source_url": "string",
        },
    },
    "read_opportunities": {
        "description": "List opportunities, optionally filtered by status (new|researched|watch|approved|rejected|launched).",
        "args": {"status": "string (optional)", "limit": "int (optional)"},
    },
    "score_opportunity": {
        "description": "Attach a research score (0-100) and notes to an opportunity, marking it researched.",
        "args": {"opportunity_id": "uuid", "research_score": "float 0-100", "research_notes": "string"},
    },
    "decide_opportunity": {
        "description": "Record the CEO decision on a researched opportunity.",
        "args": {"opportunity_id": "uuid", "decision": "approved|watch|rejected", "decision_rationale": "string"},
    },
    "record_revenue": {
        "description": "Log a real revenue transaction for a product. Its first-ever revenue auto-clones the agent that created it.",
        "args": {"product_id": "uuid", "amount_usd": "float", "description": "string (optional)"},
    },
}
