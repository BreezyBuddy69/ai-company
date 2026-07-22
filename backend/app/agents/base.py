"""Generic agent execution loop.

Every agent — CEO, Scout, Research, and any future one — runs through this
same code path. Behavior differs only through the YAML config + prompt file,
which is the whole point: "adding 100 agents should require only adding
configuration files."

Loop, per step (bounded by config.max_steps):
  1. context_manager builds a compact prompt (relevant memories + recent
     activity + injected skills)
  2. model_router.complete() asks the model to respond with one JSON action:
     {"thought": "...", "tool": "<name or 'finish'>", "args": {...}}
  3. the chosen tool is executed (only if it's on the agent's allow-list)
  4. the step is logged to agent_runs and model_usage_log
  5. "finish" ends the loop and returns its args as the run's result
"""

from __future__ import annotations

import inspect
import json
import logging
import re
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.agents.loader import AgentConfig
from app.config import Settings
from app.core.context_manager import ContextManager
from app.core.model_router import AllModelsFailedError, ModelRouter
from app.core.tools import TOOL_DESCRIPTIONS, TOOL_REGISTRY
from app.db.models import Agent as AgentRow
from app.db.models import AgentRun, ModelUsageLog

logger = logging.getLogger("agent")

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


class ToolNotAllowedError(RuntimeError):
    pass


class AgentExecutionError(RuntimeError):
    pass


def _extract_json(text: str) -> dict:
    match = _JSON_BLOCK.search(text)
    if not match:
        raise AgentExecutionError(f"model response did not contain a JSON object: {text[:200]!r}")
    return json.loads(match.group(0))


class Agent:
    def __init__(
        self,
        config: AgentConfig,
        *,
        settings: Settings,
        router: ModelRouter,
        context_manager: ContextManager,
    ):
        self.config = config
        self.settings = settings
        self.router = router
        self.context_manager = context_manager

    # -- prompt assembly -----------------------------------------------------

    def _load_text(self, relative_or_absolute: str, base_dir: Path) -> str:
        path = Path(relative_or_absolute)
        if not path.is_absolute():
            path = base_dir / relative_or_absolute
        return path.read_text(encoding="utf-8")

    def _system_prompt(self, prompts_dir: Path) -> str:
        return self._load_text(self.config.system_prompt_path, prompts_dir)

    def _skills_text(self, skills_dir: Path) -> str:
        blocks = []
        for skill in self.config.skills:
            skill_path = Path(skills_dir) / skill / "SKILL.md"
            if skill_path.exists():
                blocks.append(f"### Skill: {skill}\n{skill_path.read_text(encoding='utf-8')}")
        return "\n\n".join(blocks)

    def _tool_docs(self) -> str:
        lines = []
        for name in self.config.tools:
            spec = TOOL_DESCRIPTIONS.get(name)
            if not spec:
                continue
            lines.append(f"- {name}({spec['args']}): {spec['description']}")
        lines.append('- finish({"summary": "..."}): call this when the goal is accomplished.')
        return "\n".join(lines)

    # -- execution -------------------------------------------------------------

    def run(
        self,
        db: Session,
        *,
        agent_row: AgentRow,
        task_id: uuid.UUID | str,
        goal: str,
        prompts_dir: Path,
        skills_dir: Path,
    ) -> dict:
        system_prompt = self._system_prompt(prompts_dir)
        skills_text = self._skills_text(skills_dir)
        tool_docs = self._tool_docs()

        for step in range(1, self.config.max_steps + 1):
            context = self.context_manager.build_context(db, task_id=task_id, query=goal, skills_text=skills_text)
            user_prompt = (
                f"{context.as_prompt_block()}\n\n"
                f"## Goal\n{goal}\n\n"
                f"## Available tools\n{tool_docs}\n\n"
                "Respond with EXACTLY one JSON object, nothing else:\n"
                '{"thought": "<brief reasoning>", "tool": "<tool name or finish>", "args": {<tool arguments>}}'
            )

            usage_rows: list[ModelUsageLog] = []

            def on_attempt(*, model_name, success, tokens_in, tokens_out, latency_ms, error, _agent_id=agent_row.id):
                usage_rows.append(
                    ModelUsageLog(
                        model_name=model_name, agent_id=_agent_id, tokens_in=tokens_in, tokens_out=tokens_out,
                        latency_ms=latency_ms, success=success, error=error,
                    )
                )

            try:
                result = self.router.complete(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    capability=self.config.model_capability,
                    on_attempt=on_attempt,
                )
            except AllModelsFailedError as exc:
                db.add_all(usage_rows)
                db.add(AgentRun(
                    agent_id=agent_row.id, task_id=task_id, input={"goal": goal, "step": step},
                    output=None, success=False, error=str(exc),
                ))
                db.commit()
                raise

            db.add_all(usage_rows)

            try:
                action = _extract_json(result.content)
            except AgentExecutionError as exc:
                db.add(AgentRun(
                    agent_id=agent_row.id, task_id=task_id, input={"goal": goal, "step": step},
                    output={"raw": result.content}, model_used=result.model_used,
                    tokens_in=result.tokens_in, tokens_out=result.tokens_out,
                    latency_ms=result.latency_ms, success=False, error=str(exc),
                ))
                db.commit()
                raise

            tool_name = action.get("tool")
            args = action.get("args", {}) or {}

            db.add(AgentRun(
                agent_id=agent_row.id, task_id=task_id, input={"goal": goal, "step": step},
                output=action, model_used=result.model_used, tokens_in=result.tokens_in,
                tokens_out=result.tokens_out, latency_ms=result.latency_ms, success=True,
            ))
            self.context_manager.record_activity(
                db, task_id=task_id, agent_name=self.config.name,
                summary={"step": step, "tool": tool_name, "thought": action.get("thought", "")},
            )
            db.commit()

            if tool_name == "finish":
                return args

            if tool_name not in self.config.tools:
                raise ToolNotAllowedError(f"agent '{self.config.name}' is not permitted to call tool '{tool_name}'")

            self._execute_tool(db, tool_name, args, agent_row=agent_row)

        raise AgentExecutionError(f"agent '{self.config.name}' did not finish within {self.config.max_steps} steps")

    def _execute_tool(self, db: Session, tool_name: str, args: dict, *, agent_row: AgentRow):
        func = TOOL_REGISTRY[tool_name]
        sig = inspect.signature(func)
        call_kwargs = dict(args)
        if "db" in sig.parameters:
            call_kwargs["db"] = db
        if "discovered_by_agent_id" in sig.parameters and "discovered_by_agent_id" not in args:
            call_kwargs["discovered_by_agent_id"] = agent_row.id
        if "source_agent_id" in sig.parameters and "source_agent_id" not in args:
            call_kwargs["source_agent_id"] = agent_row.id
        output = func(**call_kwargs)
        db.commit()
        return output
