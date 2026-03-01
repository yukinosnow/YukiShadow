"""
YukiShadow - Skill Registry

Auto-discovers skills by scanning the skills/ directory for SKILL.md files.
No manual registry dict needed — just add a skills/<name>/SKILL.md file.

Discovery rules:
  1. Scan every subdirectory of skills/ for a SKILL.md file.
  2. Parse the front-matter to get metadata + action schemas.
  3. Look for skill.py in the same directory; search for a BaseSkill subclass.
  4. If skill.py is missing, the skill is skipped (LLM-only mode not yet implemented).

Adding a new skill:
  1. Create skills/<name>/SKILL.md
  2. Create skills/<name>/skill.py with a BaseSkill subclass
  3. Restart — the skill is auto-loaded, no code change needed here.
"""

from __future__ import annotations

import importlib
import inspect
import logging
from dataclasses import dataclass
from pathlib import Path

from core.base_skill import BaseSkill, SkillMarkdown, SkillResult, parse_skill_md

logger = logging.getLogger(__name__)

SKILLS_DIR = Path(__file__).parent.parent / "skills"


@dataclass
class LoadedSkill:
    markdown: SkillMarkdown
    handler: BaseSkill


class SkillRegistry:

    def __init__(self) -> None:
        self._skills: dict[str, LoadedSkill] = {}

    # ── Loading ───────────────────────────────────────────────────────────────

    async def load_all(self) -> None:
        if not SKILLS_DIR.exists():
            logger.warning(f"Skills directory not found: {SKILLS_DIR}")
            return

        for skill_dir in sorted(SKILLS_DIR.iterdir()):
            if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
                await self._load_from_dir(skill_dir)

    async def _load_from_dir(self, skill_dir: Path) -> None:
        try:
            markdown = parse_skill_md(skill_dir / "SKILL.md")
        except Exception:
            logger.exception(f"Failed to parse SKILL.md in '{skill_dir}'")
            return

        handler = await self._find_handler(skill_dir)
        if handler is None:
            logger.info(
                f"Skill '{markdown.name}': no skill.py found — skipping "
                f"(add skill.py with a BaseSkill subclass to activate)"
            )
            return

        self._skills[markdown.name] = LoadedSkill(markdown=markdown, handler=handler)
        logger.info(
            f"Loaded skill: '{markdown.name}' v{markdown.version} "
            f"({len(markdown.actions)} actions)"
        )

    async def _find_handler(self, skill_dir: Path) -> BaseSkill | None:
        """
        Load the BaseSkill subclass from skill.py via naming convention.
        Convention: class name matches <DirName>Skill (case-insensitive).
        Fallback: any BaseSkill subclass defined in that module.
        """
        skill_py = skill_dir / "skill.py"
        if not skill_py.exists():
            return None

        module_path = f"skills.{skill_dir.name}.skill"
        try:
            module = importlib.import_module(module_path)
        except Exception:
            logger.exception(f"Failed to import {module_path}")
            return None

        # Preferred: class named <dirname>skill (case-insensitive, underscores stripped)
        target = skill_dir.name.replace("_", "").lower() + "skill"
        candidates = [
            (cls_name, cls)
            for cls_name, cls in inspect.getmembers(module, inspect.isclass)
            if issubclass(cls, BaseSkill) and cls is not BaseSkill
        ]

        chosen_cls = None
        for cls_name, cls in candidates:
            if cls_name.lower() == target:
                chosen_cls = cls
                break

        if chosen_cls is None:
            # Fallback: any BaseSkill subclass defined in this module
            for cls_name, cls in candidates:
                if cls.__module__ == module_path:
                    chosen_cls = cls
                    logger.debug(f"'{skill_dir.name}': using fallback class '{cls_name}'")
                    break

        if chosen_cls is None:
            logger.warning(f"No BaseSkill subclass found in {skill_py}")
            return None

        instance: BaseSkill = chosen_cls()
        await instance.initialize()
        return instance

    # ── Registration (programmatic / testing) ─────────────────────────────────

    async def register(self, markdown: SkillMarkdown, handler: BaseSkill) -> None:
        await handler.initialize()
        self._skills[markdown.name] = LoadedSkill(markdown=markdown, handler=handler)
        logger.info(f"Skill registered: '{markdown.name}'")

    # ── Teardown ──────────────────────────────────────────────────────────────

    async def unload_all(self) -> None:
        for loaded in self._skills.values():
            try:
                await loaded.handler.shutdown()
            except Exception:
                logger.exception(f"Error shutting down skill '{loaded.markdown.name}'")
        self._skills.clear()

    # ── Query ─────────────────────────────────────────────────────────────────

    def get(self, name: str) -> LoadedSkill | None:
        return self._skills.get(name)

    def all(self) -> dict[str, LoadedSkill]:
        return dict(self._skills)

    # ── Execution ─────────────────────────────────────────────────────────────

    async def execute(self, skill_name: str, action: str, params: dict) -> SkillResult:
        loaded = self.get(skill_name)
        if loaded is None:
            return SkillResult(success=False, error=f"Skill '{skill_name}' not found")
        return await loaded.handler.execute(action, params)

    # ── Summaries (for API + MCP) ─────────────────────────────────────────────

    def summary(self) -> list[dict]:
        return [
            {
                "name": s.markdown.name,
                "description": s.markdown.description,
                "version": s.markdown.version,
                "actions": list(s.markdown.actions.keys()),
            }
            for s in self._skills.values()
        ]

    def get_all_mcp_tools(self) -> list[dict]:
        tools = []
        for loaded in self._skills.values():
            tools.extend(loaded.markdown.mcp_tools())
        return tools
