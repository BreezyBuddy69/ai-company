#!/usr/bin/env python3
"""Check every slug in model_registry.yaml is still live and still free.

Free slugs on OpenRouter get retired without warning. When that happened
silently the router fell through every entry and Anvil quietly stopped
thinking — see docs/cost-limits.md. Run this before trusting a deploy:

    OPENROUTER_API_KEY=sk-or-... python scripts/verify_models.py

Exits non-zero if any model is dead or reports a non-zero cost, so it can
gate a deploy.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yaml

API = "https://openrouter.ai/api/v1/chat/completions"
REGISTRY = Path(__file__).resolve().parent.parent / "model_registry.yaml"


def probe(slug: str, key: str) -> tuple[bool, str]:
    """One real 8-token call. Returns (ok, detail)."""
    req = urllib.request.Request(
        API,
        data=json.dumps(
            {
                "model": slug,
                "messages": [{"role": "user", "content": "Say OK"}],
                "max_tokens": 8,
            }
        ).encode(),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            # Same headers the router sends, so spend shows up identically
            # in the OpenRouter activity log (model_router.py).
            "HTTP-Referer": "https://localhost",
            "X-Title": "Anvil",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = json.load(r)
    except urllib.error.HTTPError as e:
        detail = json.load(e).get("error", {}).get("message", str(e))
        return False, detail[:80]
    except Exception as e:  # network, timeout, malformed JSON
        return False, f"{type(e).__name__}: {e}"[:80]

    # cost is the authority, not the ":free" suffix — a slug can stay listed
    # while its free tier is withdrawn, which is exactly how money leaked.
    cost = (body.get("usage") or {}).get("cost", 0) or 0
    if cost > 0:
        return False, f"NOT FREE — cost={cost}"
    return True, "cost=0"


def main() -> int:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        print("OPENROUTER_API_KEY not set", file=sys.stderr)
        return 2

    models = yaml.safe_load(REGISTRY.read_text())["models"]
    failures = []
    for m in sorted(models, key=lambda x: x["priority"]):
        ok, detail = probe(m["name"], key)
        print(f"{'OK  ' if ok else 'FAIL'}  {m['name']:<45} {detail}")
        if not ok:
            failures.append(m["name"])

    print()
    if failures:
        print(f"{len(failures)}/{len(models)} dead or paid: {', '.join(failures)}")
        print("Replace them: https://openrouter.ai/models?max_price=0")
        return 1
    print(f"all {len(models)} models live and free")
    return 0


if __name__ == "__main__":
    sys.exit(main())
