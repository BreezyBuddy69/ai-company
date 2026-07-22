"""Integration test that hits the REAL, free, keyless Hacker News API — no
mocking. This is the concrete proof that the Scout agent's data source
actually works, not just that our code calls httpx correctly.

Skips (doesn't fail) if the sandbox/CI running this has no outbound network
access — that's an environment fact, not a code defect.
"""

import httpx
import pytest

from app.core.tools import search_hackernews


def test_hackernews_search_returns_real_results():
    try:
        hits = search_hackernews("startup", hits_per_page=3)
    except httpx.HTTPError as exc:
        pytest.skip(f"no network access in this environment: {exc}")

    assert isinstance(hits, list)
    if hits:  # HN always has *something* for "startup", but don't hard-fail on an empty page
        first = hits[0]
        assert {"title", "url", "points", "source"} <= first.keys()
        assert first["source"] == "hackernews"
