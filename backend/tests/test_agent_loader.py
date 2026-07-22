import pytest

from app.agents.loader import AgentConfigError, load_agent_config, load_all_agent_configs


def _write(path, content):
    path.write_text(content, encoding="utf-8")
    return path


def test_loads_minimal_valid_config(tmp_path):
    path = _write(
        tmp_path / "scout.yaml",
        "name: scout\nrole: finds stuff\nsystem_prompt: scout_system.md\n",
    )
    cfg = load_agent_config(path)
    assert cfg.name == "scout"
    assert cfg.max_steps == 5  # default
    assert cfg.tools == []


def test_missing_required_field_raises(tmp_path):
    path = _write(tmp_path / "broken.yaml", "role: no name here\n")
    with pytest.raises(AgentConfigError):
        load_agent_config(path)


def test_non_mapping_yaml_raises(tmp_path):
    path = _write(tmp_path / "broken.yaml", "- just\n- a\n- list\n")
    with pytest.raises(AgentConfigError):
        load_agent_config(path)


def test_load_all_discovers_every_yaml_and_rejects_duplicates(tmp_path):
    _write(tmp_path / "a.yaml", "name: a\nrole: r\nsystem_prompt: a.md\n")
    _write(tmp_path / "b.yaml", "name: b\nrole: r\nsystem_prompt: b.md\n")
    configs = load_all_agent_configs(tmp_path)
    assert set(configs) == {"a", "b"}

    _write(tmp_path / "c.yaml", "name: a\nrole: dup\nsystem_prompt: c.md\n")
    with pytest.raises(AgentConfigError):
        load_all_agent_configs(tmp_path)


def test_real_shipped_configs_all_load(tmp_path):
    """The actual agents/configs/*.yaml checked into this repo must always
    be loadable — this is the test that would catch a typo'd YAML field
    before it reaches production."""
    from pathlib import Path

    config_dir = Path(__file__).resolve().parents[2] / "agents" / "configs"
    configs = load_all_agent_configs(config_dir)
    expected = {"ceo", "scout", "research", "product", "builder", "tester", "marketing", "finance"}
    assert expected <= set(configs)
    for name, cfg in configs.items():
        prompt_path = Path(__file__).resolve().parents[2] / "agents" / "prompts" / cfg.system_prompt_path
        assert prompt_path.exists(), f"{name}: missing prompt file {prompt_path}"
