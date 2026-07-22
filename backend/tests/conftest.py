import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def _reset_settings_cache(monkeypatch):
    """Every test gets a clean, isolated Settings() — get_settings() is
    lru_cached in app code (deliberately, for prod), which would otherwise
    leak state between tests."""
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    yield
    get_settings.cache_clear()


@pytest.fixture
def registry_path(tmp_path) -> Path:
    content = """
router:
  max_cost_per_1k_tokens_usd: 0.0
  request_timeout_seconds: 5
  max_retries_per_model: 1
  failure_cooldown_seconds: 300
  consecutive_failures_before_cooldown: 2

models:
  - name: "model-a:free"
    provider: openrouter
    cost: 0
    capability: general
    priority: 1
  - name: "model-b:free"
    provider: openrouter
    cost: 0
    capability: general
    priority: 2
  - name: "model-paid"
    provider: openrouter
    cost: 5.0
    capability: general
    priority: 0
"""
    path = tmp_path / "model_registry.yaml"
    path.write_text(content, encoding="utf-8")
    return path
