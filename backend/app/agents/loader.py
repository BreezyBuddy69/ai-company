"""Discovers agent configs from agents/configs/*.yaml.

Adding a new agent to the company = dropping a new YAML file (+ a prompt
file it points to) in that directory. No Python code changes needed — this
loader is the only thing that has to know the directory exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

REQUIRED_FIELDS = {"name", "role", "system_prompt"}


class AgentConfigError(ValueError):
    pass


@dataclass
class AgentConfig:
    name: str
    role: str
    system_prompt_path: str
    skills: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    permissions: dict[str, bool] = field(default_factory=dict)
    memory_scope: list[str] = field(default_factory=list)
    model_capability: str | None = None
    max_steps: int = 5
    schedule: str | None = None  # informational; Celery beat schedule wires the actual cron


def _validate(raw: dict, path: Path) -> None:
    missing = REQUIRED_FIELDS - raw.keys()
    if missing:
        raise AgentConfigError(f"{path}: missing required field(s) {sorted(missing)}")


def load_agent_config(path: Path) -> AgentConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise AgentConfigError(f"{path}: expected a YAML mapping at the top level")
    _validate(raw, path)
    return AgentConfig(
        name=raw["name"],
        role=raw["role"],
        system_prompt_path=raw["system_prompt"],
        skills=raw.get("skills", []),
        tools=raw.get("tools", []),
        permissions=raw.get("permissions", {}),
        memory_scope=raw.get("memory_scope", []),
        model_capability=raw.get("model_capability"),
        max_steps=raw.get("max_steps", 5),
        schedule=raw.get("schedule"),
    )


def load_all_agent_configs(config_dir: str | Path) -> dict[str, AgentConfig]:
    config_dir = Path(config_dir)
    if not config_dir.exists():
        raise AgentConfigError(f"agents config directory not found: {config_dir}")

    configs: dict[str, AgentConfig] = {}
    for path in sorted(config_dir.glob("*.yaml")):
        cfg = load_agent_config(path)
        if cfg.name in configs:
            raise AgentConfigError(f"duplicate agent name '{cfg.name}' in {path}")
        configs[cfg.name] = cfg
    return configs
