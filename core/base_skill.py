"""
YukiShadow - Base Skill Contract

A skill now has two parts:
  1. SKILL.md  – the primary definition (metadata, action schemas, LLM context)
  2. skill.py  – the execution handler (only execute() is required)

SkillMarkdown is parsed from SKILL.md at load time.
BaseSkill is a pure execution interface with no metadata in Python.

SKILL.md front-matter format
─────────────────────────────
---
name: reminder
description: One-line description
version: "0.1.0"
llm_provider: null      # null | ollama | openai | anthropic
actions:
  create_reminder:
    description: Create a new reminder
    parameters:
      title:
        type: string
        required: true
        description: What to remind about
      scheduled_at:
        type: string
        required: true
        description: ISO 8601 datetime
      channels:
        type: array
        default: ["discord"]
---

Everything after the closing --- is the **markdown body**.
The body is injected verbatim into the LLM system prompt so the model
understands when and how to call this skill.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ── Result ────────────────────────────────────────────────────────────────────

@dataclass
class SkillResult:
    success: bool
    data: Any = None
    error: str | None = None
    message: str = ""

    def as_dict(self) -> dict:
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "message": self.message,
        }


# ── Markdown schema types ─────────────────────────────────────────────────────

@dataclass
class ParamDef:
    type: str = "string"
    description: str = ""
    required: bool = False
    default: Any = None

    def to_json_schema(self) -> dict:
        schema: dict = {"type": self.type}
        if self.description:
            schema["description"] = self.description
        if self.default is not None:
            schema["default"] = self.default
        return schema


@dataclass
class ActionDef:
    name: str
    description: str
    parameters: dict[str, ParamDef] = field(default_factory=dict)

    def to_mcp_tool(self, skill_name: str) -> dict:
        """Return an MCP-compatible tool dict."""
        required = [p for p, d in self.parameters.items() if d.required]
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": {
                "type": "object",
                "properties": {p: d.to_json_schema() for p, d in self.parameters.items()},
                **({"required": required} if required else {}),
            },
        }


@dataclass
class SkillMarkdown:
    """Parsed representation of a SKILL.md file.  This is the single source of truth
    for a skill's name, description, actions, and LLM context."""

    name: str
    description: str
    version: str = "0.1.0"
    llm_provider: str | None = None
    actions: dict[str, ActionDef] = field(default_factory=dict)
    body: str = ""   # Markdown body (after front-matter) – goes into LLM prompt

    def mcp_tools(self) -> list[dict]:
        return [a.to_mcp_tool(self.name) for a in self.actions.values()]


# ── Parser ────────────────────────────────────────────────────────────────────

def parse_skill_md(path: Path) -> SkillMarkdown:
    """Parse SKILL.md and return a SkillMarkdown.  Raises ValueError on bad YAML."""
    import yaml  # pyyaml; available as a transitive dependency

    raw = path.read_text(encoding="utf-8")

    front_matter: dict = {}
    body = raw

    match = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n", raw, re.DOTALL)
    if match:
        try:
            front_matter = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError as exc:
            raise ValueError(f"Bad YAML front-matter in {path}: {exc}") from exc
        body = raw[match.end():]

    actions: dict[str, ActionDef] = {}
    for action_name, action_data in (front_matter.get("actions") or {}).items():
        if isinstance(action_data, str):
            # Shorthand: "action_name: description string"
            actions[action_name] = ActionDef(name=action_name, description=action_data)
        else:
            params: dict[str, ParamDef] = {}
            for param_name, param_data in (action_data.get("parameters") or {}).items():
                if isinstance(param_data, str):
                    params[param_name] = ParamDef(description=param_data)
                else:
                    params[param_name] = ParamDef(
                        type=param_data.get("type", "string"),
                        description=param_data.get("description", ""),
                        required=bool(param_data.get("required", False)),
                        default=param_data.get("default"),
                    )
            actions[action_name] = ActionDef(
                name=action_name,
                description=action_data.get("description", ""),
                parameters=params,
            )

    return SkillMarkdown(
        name=front_matter.get("name", path.parent.name),
        description=front_matter.get("description", ""),
        version=str(front_matter.get("version", "0.1.0")),
        llm_provider=front_matter.get("llm_provider"),
        actions=actions,
        body=body.strip(),
    )


# ── Base execution class ──────────────────────────────────────────────────────

class BaseSkill(ABC):
    """
    Pure execution interface.  Metadata (name, description, actions) comes from
    the accompanying SKILL.md, NOT from Python code.

    Minimal skill.py:

        class MySkill(BaseSkill):
            async def execute(self, action: str, params: dict) -> SkillResult:
                if action == "do_thing":
                    return SkillResult(success=True, message="Done!")
                return SkillResult(success=False, error=f"Unknown action '{action}'")
    """

    async def initialize(self) -> None:
        """Called once after loading. Override for async setup (DB connections, etc.)."""

    async def shutdown(self) -> None:
        """Called before unloading. Override for teardown."""

    @abstractmethod
    async def execute(self, action: str, params: dict) -> SkillResult:
        """
        Execute an action with the given params.
        Action names must match those defined in SKILL.md.
        """
        ...
