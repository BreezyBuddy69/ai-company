"""Guards the fix for the bug that made the whole company produce nothing:
tool results were executed and then discarded, so an agent never saw what its
own search returned. 88 scout runs, all "successful", 0 opportunities."""

import json

from app.agents.base import MAX_OBSERVATION_CHARS, _summarise_observation


def test_short_output_is_carried_verbatim():
    out = _summarise_observation({"id": "abc", "problem": "no-shows"})
    assert "abc" in out and "no-shows" in out


def test_long_output_is_truncated_but_marked():
    huge = [{"title": "x" * 200} for _ in range(50)]
    out = _summarise_observation(huge)
    assert len(out) < len(json.dumps(huge))
    assert "truncated" in out


def test_list_length_survives_truncation():
    """"10 results" and "0 results" demand completely different next moves, so
    the count has to outlive the truncation that removes the items."""
    out = _summarise_observation([{"title": "x" * 500} for _ in range(10)])
    assert out.startswith("10 items:")

    assert _summarise_observation([]).startswith("0 items:")


def test_empty_and_none_are_distinguishable():
    # "the tool returned nothing" and "the tool found nothing" are different
    # facts, and an agent that confuses them retries the wrong thing.
    assert _summarise_observation(None) == "(no output)"
    assert _summarise_observation([]) != _summarise_observation(None)


def test_unserialisable_output_does_not_crash_the_run():
    class Weird:
        def __repr__(self):
            return "<weird>"

    out = _summarise_observation(Weird())
    assert "weird" in out


def test_truncation_bound_is_respected():
    out = _summarise_observation({"k": "v" * 10000})
    assert len(out) < MAX_OBSERVATION_CHARS + 200
