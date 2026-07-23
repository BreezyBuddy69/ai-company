"""Tool registry available to agents. Every agent config lists which of these
it's permitted to call (`tools:` in its YAML) — the agent runner refuses to
execute anything not on that list.

Three tools hit real, free, keyless public APIs:
  - search_hackernews: Algolia HN Search API (no key required)
  - search_github_issues: GitHub REST search API (works unauthenticated at a
    lower rate limit; set GITHUB_TOKEN in .env for the higher limit)
  - search_reddit: Reddit's public search.json endpoint (no key, no auth —
    just needs a real User-Agent or Reddit 429s the request)

The rest read/write our own database.
"""

from __future__ import annotations

import re
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
REDDIT_SEARCH_URL = "https://www.reddit.com/search.json"


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


def search_reddit(keyword: str, *, limit: int = 10) -> list[dict[str, Any]]:
    params = {"q": keyword, "sort": "relevance", "limit": limit, "t": "month"}
    headers = {"User-Agent": "ai-company-scout/1.0 (opportunity research bot)"}
    with httpx.Client(timeout=15) as client:
        resp = client.get(REDDIT_SEARCH_URL, params=params, headers=headers)
    resp.raise_for_status()
    children = resp.json().get("data", {}).get("children", [])
    return [
        {
            "title": c["data"].get("title"),
            "url": f"https://reddit.com{c['data'].get('permalink', '')}",
            "score": c["data"].get("score", 0),
            "num_comments": c["data"].get("num_comments", 0),
            "subreddit": c["data"].get("subreddit"),
            "created_at": c["data"].get("created_utc"),
            "source": "reddit",
        }
        for c in children
        if c.get("data", {}).get("title")
    ]


def scrape_url(url: str, *, max_chars: int = 4000) -> dict[str, Any]:
    """Fully-rendered page text via self-hosted Browserless — for JS-only or
    bot-walled pages plain httpx can't read (search_hackernews/github/reddit
    above all hit plain JSON APIs and never need this). Requires
    BROWSERLESS_URL/BROWSERLESS_TOKEN configured (docker-compose.yml's
    browserless service) — raises clearly rather than silently no-op'ing if
    it isn't."""
    settings = get_settings()
    if not settings.browserless_token:
        raise ValueError("BROWSERLESS_TOKEN not configured — scrape_url needs a running browserless instance")
    with httpx.Client(timeout=30) as client:
        resp = client.post(
            f"{settings.browserless_url}/content",
            params={"token": settings.browserless_token},
            json={"url": url, "gotoOptions": {"waitUntil": "networkidle2"}},
        )
    resp.raise_for_status()
    text = re.sub(r"<[^>]+>", " ", resp.text)
    text = re.sub(r"\s+", " ", text).strip()
    return {"url": url, "text": text[:max_chars], "truncated": len(text) > max_chars}


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
    "search_reddit": search_reddit,
    "scrape_url": scrape_url,
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
    "search_reddit": {
        "description": "Search Reddit (last month, all subreddits) for a keyword. Returns posts with score/comment counts.",
        "args": {"keyword": "string"},
    },
    "scrape_url": {
        "description": "Fetch the fully-rendered text of a JS-heavy or bot-walled page via self-hosted headless Chrome. Only use this when a plain search result URL is worth reading in full and the other tools can't reach it.",
        "args": {"url": "string"},
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
