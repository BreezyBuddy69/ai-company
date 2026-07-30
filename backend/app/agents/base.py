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


# A Hacker News or Reddit search returns far more than an agent needs to
# decide its next move, and it goes into every subsequent prompt. Truncating
# here keeps the loop affordable; the context manager compresses the buffer
# into a summary memory once it grows past short_term_buffer_max_runs anyway.
MAX_OBSERVATION_CHARS = 1500


def _summarise_observation(observation) -> str:
    """Tool output, small enough to carry forward. Lists get their length kept
    even when the items are cut, because "found 10 results" and "found 0" lead
    to completely different next steps."""
    if observation is None:
        return "(no output)"
    try:
        text = json.dumps(observation, default=str)
    except (TypeError, ValueError):
        text = str(observation)

    prefix = f"{len(observation)} items: " if isinstance(observation, (list, tuple)) else ""
    if len(text) <= MAX_OBSERVATION_CHARS:
        return prefix + text
    return prefix + text[:MAX_OBSERVATION_CHARS] + f"… (truncated from {len(text)} chars)"


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
            remaining = self.config.max_steps - step
            # Without this block an agent re-ran the same search every step and
            # ended on "did not finish within N steps" — it could see the
            # results in Recent activity but was never told they were its own,
            # that repeating was pointless, or that steps were finite.
            budget_note = (
                f"## Step {step} of {self.config.max_steps} ({remaining} left after this one)\n"
                "The observations under Recent activity are results YOU already fetched. Do not "
                "repeat a search you have already run — it will return the same thing again.\n"
                + (
                    "You are out of steps after this one. Act on what you already have: call the "
                    "tool that records your finding, or call finish.\n"
                    if remaining <= 1
                    else "As soon as you have enough to act, use the tool that records the result. "
                    "Search again only if the observations so far genuinely gave you nothing.\n"
                )
            )
            user_prompt = (
                f"{context.as_prompt_block()}\n\n"
                f"## Goal\n{goal}\n\n"
                f"{budget_note}\n"
                f"## Available tools\n{tool_docs}\n\n"
                "Respond with EXACTLY one JSON object, nothing else:\n"
                '{"thought": "<brief reasoning>", "tool": "<tool name or finish>", "args": {<tool arguments>}}'
            )

            usage_rows: list[ModelUsageLog] = []

            def on_attempt(*, model_name, success, tokens_in, tokens_out, latency_ms, error, cost_usd=0.0, _agent_id=agent_row.id):
                usage_rows.append(
                    ModelUsageLog(
                        model_name=model_name, agent_id=_agent_id, tokens_in=tokens_in, tokens_out=tokens_out,
                        latency_ms=latency_ms, success=success, error=error, cost_usd=cost_usd,
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
                    cost_usd=result.cost_usd,
                ))
                db.commit()
                raise

            tool_name = action.get("tool")
            args = action.get("args", {}) or {}

            db.add(AgentRun(
                agent_id=agent_row.id, task_id=task_id, input={"goal": goal, "step": step},
                output=action, model_used=result.model_used, tokens_in=result.tokens_in,
                tokens_out=result.tokens_out, latency_ms=result.latency_ms, success=True,
                cost_usd=result.cost_usd,
            ))
            if tool_name == "finish":
                self.context_manager.record_activity(
                    db, task_id=task_id, agent_name=self.config.name,
                    summary={"step": step, "tool": "finish", "thought": action.get("thought", "")},
                )
                db.commit()
                return args

            # A bad tool choice or a broken tool is fed back as an observation
            # rather than ending the run. Autonomy means routing around a dead
            # dependency: one unconfigured optional tool (browserless, say)
            # used to kill an otherwise fine scout run outright, and a
            # scheduled system that dies on the first unavailable service
            # spends most of its life dead.
            if tool_name not in self.config.tools:
                observation = (
                    f"ERROR: '{tool_name}' is not a tool you may call. "
                    f"Your tools are: {', '.join(self.config.tools)}. Pick one of those."
                )
            else:
                try:
                    observation = _summarise_observation(
                        self._execute_tool(db, tool_name, args, agent_row=agent_row)
                    )
                except Exception as exc:
                    # The tool may have died mid-transaction; the session has to
                    # be usable for the next step and for record_activity.
                    db.rollback()
                    logger.warning("tool %s failed: %s", tool_name, exc)
                    observation = f"ERROR from {tool_name}: {exc}. Try a different approach."

            # The observation is the whole point of taking a step, and it used
            # to be discarded: _execute_tool's return value was thrown away and
            # only the tool NAME was recorded. So an agent searched Hacker
            # News, never saw a single result, searched again, and burned every
            # step without ever having anything to call create_opportunity
            # with. 88 scout runs produced 0 opportunities that way — all
            # "successful", because each step returned valid JSON.
            self.context_manager.record_activity(
                db, task_id=task_id, agent_name=self.config.name,
                summary={
                    "step": step,
                    "tool": tool_name,
                    "thought": action.get("thought", ""),
                    "observation": observation,
                },
            )
            db.commit()

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
        if "created_by_agent_id" in sig.parameters and "created_by_agent_id" not in args:
            call_kwargs["created_by_agent_id"] = agent_row.id
        output = func(**call_kwargs)
        db.commit()
        return output
