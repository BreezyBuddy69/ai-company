import pytest

from app.agents.base import AgentExecutionError, _extract_json


def test_extracts_plain_json():
    assert _extract_json('{"tool": "finish", "args": {}}') == {"tool": "finish", "args": {}}


def test_extracts_json_from_markdown_fence():
    text = '```json\n{"tool": "finish", "args": {"summary": "done"}}\n```'
    assert _extract_json(text) == {"tool": "finish", "args": {"summary": "done"}}


def test_extracts_json_with_leading_commentary():
    text = 'Sure, here is my decision:\n{"tool": "finish", "args": {}}\nHope that helps!'
    assert _extract_json(text) == {"tool": "finish", "args": {}}


def test_no_json_raises():
    with pytest.raises(AgentExecutionError):
        _extract_json("I refuse to output JSON today.")
