"""
File Manager Skill – execution handler stub.
See SKILL.md for the full description and planned capabilities.
"""
from core.base_skill import BaseSkill, SkillResult


class FileManagerSkill(BaseSkill):

    async def execute(self, action: str, params: dict) -> SkillResult:
        return SkillResult(
            success=False,
            error=f"FileManagerSkill action '{action}' is not yet implemented. See SKILL.md.",
        )
