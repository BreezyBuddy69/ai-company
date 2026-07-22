import httpx
import pytest
import respx

from app.core.model_router import AllModelsFailedError, ModelRouter


def _success_response(model: str, content: str = '{"ok": true}'):
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        },
    )


@respx.mock
def test_uses_first_priority_free_model(registry_path):
    respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=_success_response("model-a:free")
    )
    router = ModelRouter(registry_path=registry_path)
    result = router.complete("system", "user")
    assert result.model_used == "model-a:free"
    assert result.tokens_in == 10
    assert result.tokens_out == 5


@respx.mock
def test_falls_back_when_first_model_fails(registry_path):
    route = respx.post("https://openrouter.ai/api/v1/chat/completions")
    route.side_effect = [
        httpx.Response(500, json={"error": "boom"}),  # model-a fails
        _success_response("model-b:free"),  # model-b succeeds
    ]
    router = ModelRouter(registry_path=registry_path)
    result = router.complete("system", "user")
    assert result.model_used == "model-b:free"


@respx.mock
def test_paid_model_never_selected_even_though_highest_priority(registry_path):
    """model-paid has priority=0 (would go first) but cost=5.0 > the
    router's max_cost_per_1k_tokens_usd=0.0 ceiling — it must never be
    called, proving the free-first guarantee is enforced in code."""
    route = respx.post("https://openrouter.ai/api/v1/chat/completions")
    route.mock(return_value=_success_response("model-a:free"))
    router = ModelRouter(registry_path=registry_path)
    router.complete("system", "user")
    called_models = [
        __import__("json").loads(call.request.content)["model"] for call in route.calls
    ]
    assert "model-paid" not in called_models


@respx.mock
def test_all_models_failing_raises(registry_path):
    respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(500, json={"error": "boom"})
    )
    router = ModelRouter(registry_path=registry_path)
    with pytest.raises(AllModelsFailedError):
        router.complete("system", "user")


@respx.mock
def test_on_attempt_callback_records_both_failure_and_success(registry_path):
    route = respx.post("https://openrouter.ai/api/v1/chat/completions")
    route.side_effect = [httpx.Response(500, json={}), _success_response("model-b:free")]
    router = ModelRouter(registry_path=registry_path)

    attempts = []
    router.complete(
        "system", "user",
        on_attempt=lambda **kwargs: attempts.append(kwargs),
    )
    assert attempts[0]["success"] is False
    assert attempts[-1]["success"] is True
    assert attempts[-1]["model_name"] == "model-b:free"


def test_default_registry_path_falls_back_to_real_repo_file():
    """No registry_path passed and the absolute /model_registry.yaml Docker
    mount doesn't exist on this dev machine -> must resolve to the real
    ai-company/model_registry.yaml checked into the repo, not error out."""
    router = ModelRouter()
    assert router.models, "expected the real model_registry.yaml to have loaded at least one model"
    assert any(m.name == "openrouter/auto" for m in router.models)


def test_no_api_key_raises_immediately(registry_path, monkeypatch):
    from app.config import get_settings

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    get_settings.cache_clear()
    router = ModelRouter(registry_path=registry_path)
    with pytest.raises(AllModelsFailedError):
        router.complete("system", "user")
