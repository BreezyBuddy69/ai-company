"""Chat-specific logic that has no database in it: the validators that bound
cost, and the history flattening the router depends on."""

import pytest
from pydantic import ValidationError

from app.api.routes.chat import ChatIn, IdeaIn, Message, _flatten
from app.core.model_router import ModelRouter


def test_fanout_is_bounded():
    # fanout is a direct multiplier on model calls per message. Unbounded, one
    # request could burn every model in the registry.
    assert ChatIn(messages=[Message(role="user", content="hi")], fanout=4).fanout == 4
    for bad in (0, 5, 99, -1):
        with pytest.raises(ValidationError):
            ChatIn(messages=[Message(role="user", content="hi")], fanout=bad)


def test_fanout_defaults_to_one():
    assert ChatIn(messages=[Message(role="user", content="hi")]).fanout == 1


def test_empty_conversation_is_rejected():
    with pytest.raises(ValidationError):
        ChatIn(messages=[])


def test_flatten_keeps_turn_order_and_invites_a_reply():
    out = _flatten([
        Message(role="user", content="first"),
        Message(role="assistant", content="second"),
        Message(role="user", content="third"),
    ])
    assert out.index("first") < out.index("second") < out.index("third")
    assert out.rstrip().endswith("ASSISTANT:")


def test_thin_ideas_are_rejected():
    # A one-word "problem" reaches Research as an unscoreable row.
    for bad in ("", "   ", "app"):
        with pytest.raises(ValidationError):
            IdeaIn(problem=bad)
    assert IdeaIn(problem="  dentists lose no-show revenue  ").problem == "dentists lose no-show revenue"


def test_exclude_removes_models_from_the_candidate_pool(registry_path):
    """What makes fanout return different models instead of the top one twice.
    Uses the real router, since the bug this guards against would be exclude
    silently doing nothing."""
    r = ModelRouter(registry_path=registry_path)
    names = [m.name for m in r.candidates()]
    assert "model-a:free" in names

    remaining = [m.name for m in r.candidates(exclude={"model-a:free"})]
    assert "model-a:free" not in remaining
    assert "model-b:free" in remaining

    # Excluding is not permanent — the shared router must be unchanged for the
    # next request (it is shared across threads).
    assert "model-a:free" in [m.name for m in r.candidates()]
