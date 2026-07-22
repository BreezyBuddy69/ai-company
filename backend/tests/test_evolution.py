from app.core.evolution import agent_family


def test_agent_family_strips_generation_suffix():
    assert agent_family("scout-g3") == "scout"


def test_agent_family_leaves_bare_name_alone():
    assert agent_family("scout") == "scout"


def test_agent_family_only_strips_trailing_suffix():
    assert agent_family("scout-g2-helper") == "scout-g2-helper"
