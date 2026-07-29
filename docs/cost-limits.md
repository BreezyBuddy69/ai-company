# Cost limits

Anvil has **no budget guard in application code**. The only enforcement is:

1. `model_registry.yaml` → `router.max_cost_per_1k_tokens_usd: 0.0` — the router
   refuses any model priced above zero. This is the in-code ceiling.
2. Per-key spend limits set in the OpenRouter dashboard. This is the only hard
   stop, because it survives a stale container image running old routing code.

Point 2 is not optional. The incident below happened because point 1 did not
yet exist and no key limit was set.

## Incident 2026-07-27 — `openrouter/auto` burned real money

`openrouter/auto` was listed as priority-1 "free". It is a meta-model:
OpenRouter picks the backing model per request and can pick a paid one. It
always "succeeded", so every genuinely-free model below it was never tried.

Fixed in `ac10896` — the entry is removed and only explicit `:free` slugs are
listed. **A deployed container running an image built before `ac10896` still
has the bug.** The fix is in the image, not in config, so it needs a fresh
image pull, not a restart.

Signature of the spend, for recognising a recurrence:
- App header `https://localhost/` (set in `backend/app/core/model_router.py:170`)
- Key label used on the VPS deploy: `autobus`
- ~$0.01/call against a paid model, at the celery_beat tick cadence

## Required limits per key

Set in https://openrouter.ai/settings/keys → key → Edit → Limit.

| Key | Used by | Limit | Reset |
|---|---|---|---|
| `autobus` | Hostinger VPS deploy | **revoke** — pre-`ac10896` spend, see above | — |
| Anvil VPS (replacement) | backend + celery on VPS | $5 | weekly |
| Buchhaltung-KI | n8n Buchhaltung workflow | $3 | weekly (already set, usage $0) |

A key with no limit set is treated as a production incident, not a todo.

## Verifying a key from the CLI

Returns the label, the limit and actual usage without exposing the key:

```bash
curl -s -H "Authorization: Bearer $OPENROUTER_API_KEY" \
  https://openrouter.ai/api/v1/key
```

`"limit": null` means unlimited — fix it before deploying anything that uses it.
