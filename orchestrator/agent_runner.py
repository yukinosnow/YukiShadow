"""
YukiShadow - Agent Runner

Converts natural-language user input into skill calls using a local/remote LLM.

Flow:
  1. User text arrives (from Discord, API, MCP, etc.)
  2. LLM decides which skill + action + params to invoke
  3. SkillRegistry executes the action
  4. Result is returned + a reply is composed for the user

The LLM is given a JSON-structured system prompt listing all available skills.
It must respond in JSON format (thought / skill / action / params / reply).
"""

from __future__ import annotations

import json
import logging
import re

from core.llm_client import LLMResponse, Message, llm_router
from core.message_bus import message_bus
from orchestrator.skill_registry import SkillRegistry

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are YukiShadow, a personal AI assistant running locally. \
Help the user by invoking the right skill for their request.

Available skills and actions:
{skills_block}

Rules:
- Always respond with valid JSON only — no markdown fences, no extra text.
- Use ISO 8601 for all datetime values.
- If the user's request does not map to any skill, set "skill" to null.
- "thought" should be a brief internal reasoning step.

Response schema:
{{
  "thought": "<reasoning>",
  "skill": "<skill_name or null>",
  "action": "<action_name or null>",
  "params": {{}},
  "reply": "<friendly reply to the user>"
}}
"""


def _build_skills_block(registry: SkillRegistry) -> str:
    """
    Build the skills section of the system prompt.
    Each skill contributes its full SKILL.md body so the LLM has rich context:
    descriptions, parameter notes, usage examples, and edge-case guidance.
    """
    sections: list[str] = []
    for loaded in registry.all().values():
        md = loaded.markdown
        sections.append(f"---\n## Skill: `{md.name}`\n\n{md.body}")
    return "\n\n".join(sections)


def _extract_json(text: str) -> dict:
    """Try to parse JSON from LLM output even if it added extra text."""
    text = text.strip()
    # Strip markdown code fences if present
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


class AgentRunner:

    def __init__(self, registry: SkillRegistry) -> None:
        self._registry = registry

    async def process(
        self,
        content: str,
        context: dict | None = None,
    ) -> dict:
        """
        Process a user message.

        Returns a dict with at minimum a "reply" key.
        May also contain "skill", "action", "params", "skill_result".
        """
        skills_block = _build_skills_block(self._registry)
        system = _SYSTEM_PROMPT.format(skills_block=skills_block)

        messages = [
            Message(role="system", content=system),
            Message(role="user", content=content),
        ]

        try:
            response: LLMResponse = await llm_router.chat(
                messages, skill_name="orchestrator"
            )
            parsed = _extract_json(response.content)
        except json.JSONDecodeError:
            logger.warning(f"LLM returned non-JSON: {response.content[:200]}")
            return {"reply": response.content, "skill": None}
        except Exception as exc:
            logger.exception("LLM call failed")
            return {"reply": f"Sorry, I ran into an error: {exc}", "skill": None}

        # Execute skill if specified
        skill_name = parsed.get("skill")
        action = parsed.get("action")
        if skill_name and action:
            skill_result = await self._registry.execute(
                skill_name, action, parsed.get("params", {})
            )
            parsed["skill_result"] = skill_result.as_dict()

            if not skill_result.success:
                parsed["reply"] = f"I tried to run '{skill_name}.{action}' but got an error: {skill_result.error}"
            elif skill_result.message and not parsed.get("reply"):
                parsed["reply"] = skill_result.message

        return parsed

    async def run_queue(self) -> None:
        """
        Continuously process messages from the orchestrator queue.
        Each message may carry a reply_channel_id so we can respond via Discord.
        """
        logger.info("Agent queue processor started (queue:orchestrator)")
        while True:
            task = await message_bus.dequeue("queue:orchestrator", timeout=5)
            if task is None:
                continue

            try:
                result = await self.process(
                    content=task.get("content", ""),
                    context=task,
                )

                reply_channel_id = task.get("reply_channel_id")
                reply_text = result.get("reply", "")
                if reply_channel_id and reply_text:
                    await message_bus.publish("events:discord:send_message", {
                        "message": reply_text,
                        "channel_id": reply_channel_id,
                    })
            except Exception:
                logger.exception("Agent queue processor error")
