"""Free-first OpenRouter model router.

Tries models from model_registry.yaml strictly in priority order. Any kind of
failure (HTTP error, timeout, rate limit, model retired) is treated the same
way: log it, move to the next model. A model that fails repeatedly is put on
a cooldown so a broken/rate-limited model doesn't slow down every single call
for the whole cooldown window.

This module has no DB dependency by design — callers pass an optional
`on_attempt` callback to persist usage/failure rows however they see fit
(keeps this file testable with zero infrastructure).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml

from app.config import get_settings

logger = logging.getLogger("model_router")

AttemptCallback = Callable[..., None]


@dataclass
class ModelSpec:
    name: str
    provider: str
    priority: int
    cost: float = 0.0
    capability: str = "general"
    display_name: str = ""


@dataclass
class CompletionResult:
    content: str
    model_used: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    cost_usd: float = 0.0


class AllModelsFailedError(RuntimeError):
    """Raised when every candidate model failed or is in cooldown."""


def _default_registry_path(configured: str) -> Path:
    path = Path(configured)
    if path.exists():
        return path
    # Fallback for local/dev runs outside Docker where /model_registry.yaml
    # doesn't exist as an absolute mount. model_router.py lives at
    # ai-company/backend/app/core/model_router.py, so parents[3] is ai-company/.
    return Path(__file__).resolve().parents[3] / "model_registry.yaml"


class ModelRouter:
    def __init__(self, registry_path: str | Path | None = None):
        self.settings = get_settings()
        path = Path(registry_path) if registry_path else _default_registry_path(self.settings.model_registry_path)
        registry: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))

        self.router_cfg: dict[str, Any] = registry.get("router", {})
        self.models: list[ModelSpec] = sorted(
            (
                ModelSpec(
                    name=m["name"],
                    provider=m.get("provider", "openrouter"),
                    priority=m.get("priority", 999),
                    cost=m.get("cost", 0.0),
                    capability=m.get("capability", "general"),
                    display_name=m.get("display_name", m["name"]),
                )
                for m in registry.get("models", [])
            ),
            key=lambda m: m.priority,
        )
        self._cooldown_until: dict[str, float] = {}
        self._consecutive_failures: dict[str, int] = {}

    # -- internal bookkeeping -------------------------------------------------

    def _is_cooling_down(self, name: str) -> bool:
        until = self._cooldown_until.get(name)
        return until is not None and time.monotonic() < until

    def _note_failure(self, name: str) -> None:
        count = self._consecutive_failures.get(name, 0) + 1
        self._consecutive_failures[name] = count
        threshold = self.router_cfg.get("consecutive_failures_before_cooldown", 3)
        if count >= threshold:
            cooldown = self.router_cfg.get("failure_cooldown_seconds", 300)
            self._cooldown_until[name] = time.monotonic() + cooldown
            logger.warning("model %s: %s consecutive failures, cooling down %ss", name, count, cooldown)

    def _note_success(self, name: str) -> None:
        self._consecutive_failures[name] = 0

    # -- public API -------------------------------------------------------------

    def candidates(self, capability: str | None = None) -> list[ModelSpec]:
        max_cost = self.router_cfg.get("max_cost_per_1k_tokens_usd", 0.0)
        pool = [m for m in self.models if m.cost <= max_cost]
        if capability:
            scoped = [m for m in pool if m.capability == capability]
            if scoped:
                return scoped
        return pool

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        capability: str | None = None,
        on_attempt: AttemptCallback | None = None,
    ) -> CompletionResult:
        if not self.settings.openrouter_api_key:
            raise AllModelsFailedError("OPENROUTER_API_KEY is not set — cannot call any model.")

        timeout = self.router_cfg.get("request_timeout_seconds", 60)
        max_retries = self.router_cfg.get("max_retries_per_model", 2)
        errors: list[str] = []

        for model in self.candidates(capability):
            if self._is_cooling_down(model.name):
                continue

            for attempt in range(1, max_retries + 1):
                start = time.monotonic()
                try:
                    result = self._call_openrouter(model, system_prompt, user_prompt, timeout)
                except Exception as exc:  # any failure => try next attempt/model
                    latency_ms = int((time.monotonic() - start) * 1000)
                    errors.append(f"{model.name} attempt {attempt}: {exc}")
                    logger.info("model %s attempt %s failed: %s", model.name, attempt, exc)
                    if on_attempt:
                        on_attempt(model_name=model.name, success=False, tokens_in=0, tokens_out=0,
                                   latency_ms=latency_ms, error=str(exc))
                    continue

                self._note_success(model.name)
                if on_attempt:
                    on_attempt(model_name=model.name, success=True, tokens_in=result.tokens_in,
                               tokens_out=result.tokens_out, latency_ms=result.latency_ms, error=None)
                return result

            self._note_failure(model.name)

        raise AllModelsFailedError("All free models failed or are cooling down:\n" + "\n".join(errors))

    def _call_openrouter(self, model: ModelSpec, system_prompt: str, user_prompt: str, timeout: float) -> CompletionResult:
        start = time.monotonic()
        with httpx.Client(base_url=self.settings.openrouter_base_url, timeout=timeout) as client:
            resp = client.post(
                "/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.settings.openrouter_api_key}",
                    "HTTP-Referer": "https://localhost",
                    "X-Title": "Autonomous AI Software Factory",
                },
                json={
                    "model": model.name,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                },
            )
        resp.raise_for_status()
        data = resp.json()
        latency_ms = int((time.monotonic() - start) * 1000)
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return CompletionResult(
            content=content,
            model_used=model.name,
            tokens_in=usage.get("prompt_tokens", 0),
            tokens_out=usage.get("completion_tokens", 0),
            latency_ms=latency_ms,
            cost_usd=0.0,
        )
