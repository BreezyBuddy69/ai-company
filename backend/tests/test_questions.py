"""No Postgres fixture exists in this suite, and HumanQuestion uses
postgres-only column types (UUID, TIMESTAMPTZ) that SQLite can't stand in for.
So this covers the parts that fail *silently and expensively* and need no
database: the schema that decides whether secrets leak, and the validators
that decide what an agent ends up acting on."""

import pytest
from pydantic import ValidationError

from app.api.routes.questions import AnswerIn, AskIn, QuestionOut


def test_answer_is_not_exposed_by_the_read_schema():
    """The whole point of `kind: secret`. If someone adds `answer` to
    QuestionOut for convenience, every credential the operator ever typed
    starts being served to the dashboard — and this test is the tripwire."""
    assert "answer" not in QuestionOut.model_fields


def test_blank_answers_are_rejected():
    # Whitespace would otherwise flip status to "answered" and the agent would
    # proceed on an empty string as though the human had decided something.
    for blank in ("", "   ", "\n\t"):
        with pytest.raises(ValidationError):
            AnswerIn(answer=blank)


def test_real_answer_survives_validation():
    assert AnswerIn(answer="  hello@example.com  ").answer.strip() == "hello@example.com"


def test_kind_is_restricted_to_known_values():
    assert AskIn(agent="scout", question="q", kind="text").kind == "text"
    assert AskIn(agent="scout", question="q", kind="secret").kind == "secret"
    # A typo'd kind must not silently degrade a secret into a plain-text
    # question that the dashboard then renders in the clear.
    with pytest.raises(ValidationError):
        AskIn(agent="scout", question="q", kind="secrets")


def test_kind_defaults_to_text():
    assert AskIn(agent="scout", question="q").kind == "text"
