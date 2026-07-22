"""Local proof that the Scout step works for real — no Docker/Postgres
required on this machine.

Always makes REAL calls to Hacker News + GitHub Issues search (free,
keyless public APIs). Additionally makes a REAL call to a free OpenRouter
model if OPENROUTER_API_KEY is set in ai-company/.env, to prove the
"structure a raw finding into a candidate opportunity" step end-to-end.

Does NOT write to the database — there isn't one running on a bare dev
machine. That path (create_opportunity, write_memory, the full agent loop)
is covered by backend/tests/ (mocked) and by the real docker-compose stack
once deployed (see DEPLOY.md).

Usage:
    cd ai-company/backend && pip install -r requirements.txt
    python ../scripts/dev_dry_run.py "expensive manual spreadsheet"
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ENV_FILE)

from app.config import get_settings  # noqa: E402
from app.core.model_router import AllModelsFailedError, ModelRouter  # noqa: E402
from app.core.tools import search_github_issues, search_hackernews  # noqa: E402


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252; fixes the em dashes below

    keyword = sys.argv[1] if len(sys.argv) > 1 else "expensive manual spreadsheet"
    print(f"== Scout dry run for keyword: {keyword!r} ==\n")

    print("-- Hacker News (real API call) --")
    hn_hits = search_hackernews(keyword, hits_per_page=5)
    for h in hn_hits:
        print(f"  [{h['points']} pts] {h['title']} -> {h['url']}")
    if not hn_hits:
        print("  (no hits)")

    print("\n-- GitHub issues (real API call) --")
    try:
        gh_hits = search_github_issues(keyword, per_page=5)
    except Exception as exc:  # e.g. unauthenticated rate limit hit
        gh_hits = []
        print(f"  (skipped: {exc})")
    else:
        for h in gh_hits:
            print(f"  [{h['reactions']} reactions] {h['title']} -> {h['url']}")
        if not gh_hits:
            print("  (no hits)")

    settings = get_settings()
    if not settings.openrouter_api_key:
        print("\nNo OPENROUTER_API_KEY set in ai-company/.env — skipping the LLM structuring step.")
        print("Get a free key at https://openrouter.ai/keys (no payment method needed for :free")
        print("models) and re-run this script to see the full Scout reasoning step live.")
        return

    top_hits = (hn_hits + gh_hits)[:5]
    if not top_hits:
        print("\nNothing to structure — no hits from either source for this keyword.")
        return

    print("\n-- Structuring the findings with a free OpenRouter model (real LLM call) --")
    router = ModelRouter()
    raw = "\n".join(f"- {h['title']} ({h['url']})" for h in top_hits)
    try:
        result = router.complete(
            system_prompt=(
                "You are a startup scout. Given raw discussion titles, decide if ANY of them "
                "point to a real, specific customer pain point. Respond with ONLY a JSON object: "
                '{"found": bool, "problem": "", "target_customer": "", "possible_product": "", '
                '"pain_level": 0}. If nothing credible, set found=false.'
            ),
            user_prompt=f"Keyword: {keyword}\n\nFindings:\n{raw}",
        )
    except AllModelsFailedError as exc:
        print(f"All free models failed or are unavailable right now: {exc}")
        return

    print(
        f"Model used: {result.model_used}  ({result.latency_ms}ms, "
        f"{result.tokens_in} in / {result.tokens_out} out tokens, cost=${result.cost_usd})"
    )
    try:
        parsed = json.loads(result.content)
        print(json.dumps(parsed, indent=2))
    except json.JSONDecodeError:
        print(result.content)
        print(
            "\n(raw model output wasn't strict JSON — that's expected sometimes with small free "
            "models; the real agent loop has a JSON-extraction fallback, see agents/base.py)"
        )


if __name__ == "__main__":
    main()
