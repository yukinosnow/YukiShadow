"""
YukiShadow - Agent Runner

Two-step LLM flow per user turn:

  Step 1 – Route
    System prompt: skill names + one-line descriptions.
    LLM decides which skill (if any) should handle the request.
    Response: {"skill": "name"} or {"skill": null, "reply": "..."}

  Step 2 – Execute  (only when a skill is chosen)
    System prompt: full SKILL.md body for the chosen skill.
    LLM decides exact action + parameters.
    Response: {"action": "...", "params": {...}, "reply": "..."}

  If no skill needed: the router's "reply" is returned directly.

History (per channel_id) stores user + assistant messages for
multi-turn context. It is fed to the router so follow-up messages
can reference earlier turns.

All turns are appended to logs/conversations.log.
"""

from __future__ import annotations

import json
import logging
import re
from collections import deque
from datetime import datetime
from pathlib import Path

from core.llm_client import Message, llm_router
from core.message_bus import message_bus
from orchestrator.skill_registry import SkillRegistry

logger = logging.getLogger(__name__)

# ── Conversation file logger ───────────────────────────────────────────────────

_LOG_DIR = Path(__file__).parent.parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)

_conv_log = logging.getLogger("yukishadow.conversation")
_conv_log.setLevel(logging.DEBUG)
_conv_log.propagate = False
_fh = logging.FileHandler(_LOG_DIR / "conversations.log", encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(message)s"))
_conv_log.addHandler(_fh)

MAX_HISTORY = 20

# ── Prompts ────────────────────────────────────────────────────────────────────

_ROUTER_PROMPT_TEMPLATE = """\
You are YukiShadow, a personal AI assistant running locally.

## Available Skills

{skills_block}

## Response Format

If a skill should handle the request, output ONLY:
{{"skill": "<skill_name>"}}

For general conversation (no skill needed), output ONLY:
{{"skill": null, "reply": "<your response>"}}

## Rules

- Output ONLY the JSON object. No text before or after it.
- Pick the skill whose description best matches the request.
- When in doubt, prefer {{"skill": null}} and answer directly.
- Dates and times must be ISO 8601 (e.g. "2026-03-15T15:00:00").
"""

_EXECUTOR_PROMPT_TEMPLATE = """\
You are the action planner for the "{skill_name}" skill.
Read the skill reference below, then output the exact action and parameters.

## Skill Reference

{skill_body}

## Response Format

Output ONLY this JSON:
{{"action": "<action_name>", "params": {{}}, "reply": "<friendly confirmation for the user>"}}

## Rules

- Output ONLY the JSON. No preamble, no explanation outside it.
- Extract all required parameters from the user's message.
- Dates and times must be ISO 8601 (e.g. "2026-03-15T15:00:00").
- Use null for optional parameters that are not mentioned.
"""


def _build_router_skills_block(registry: SkillRegistry) -> str:
    """One-line entry per skill for the routing prompt."""
    lines = []
    for loaded in registry.all().values():
        md = loaded.markdown
        lines.append(f"- **{md.name}**: {md.description}")
    return "\n".join(lines) + "\n"


# ── JSON extraction ────────────────────────────────────────────────────────────

_THINK_TAG_RE  = re.compile(r"<think>([\s\S]*?)</think>", re.IGNORECASE)
_THINK_FULL_RE = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)
_JSON_OBJ_RE   = re.compile(r"\{[\s\S]*\}", re.DOTALL)


def _split_think(raw: str) -> tuple[str, str]:
    """
    Separate Qwen3 chain-of-thought from the actual response.
    Returns (thinking, response) where thinking is "" for non-thinking models.
    """
    m = _THINK_TAG_RE.search(raw)
    thinking = m.group(1).strip() if m else ""
    response = _THINK_FULL_RE.sub("", raw).strip()
    return thinking, response


def _extract_json(text: str) -> dict:
    """
    Robustly extract a JSON object from LLM output.
    Strips Qwen3 <think>...</think> blocks before parsing.
    Handles: clean JSON, markdown-fenced JSON, JSON embedded in prose.
    Raises ValueError (not JSONDecodeError) with the offending text included.
    """
    if not text.strip():
        raise ValueError("LLM returned empty response after stripping think tags")

    m = _JSON_FENCE_RE.search(text)
    if m:
        candidate = m.group(1)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON fence found but failed to parse: {e}\n  candidate: {candidate!r}") from e

    m = _JSON_OBJ_RE.search(text)
    if m:
        candidate = m.group(0)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON object regex matched but failed to parse: {e}\n  candidate: {candidate!r}") from e

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"No JSON found in LLM output: {e}\n  raw text: {text!r}") from e


# ── Agent Runner ───────────────────────────────────────────────────────────────

class AgentRunner:

    def __init__(self, registry: SkillRegistry) -> None:
        self._registry = registry
        self._router_prompt: str = ""
        self._history: dict[str, deque[Message]] = {}

    def build_system_prompt(self) -> None:
        """
        Build the routing prompt from the current skill registry.
        Call once after skill_registry.load_all() completes.
        (Named build_system_prompt for compatibility with app.py.)
        """
        skills_block = _build_router_skills_block(self._registry)
        self._router_prompt = _ROUTER_PROMPT_TEMPLATE.format(skills_block=skills_block)
        logger.info(
            f"Router prompt built — {len(self._registry.all())} skill(s): "
            + ", ".join(self._registry.all().keys())
        )

    def clear_history(self, channel_id: str = "default") -> None:
        self._history.pop(channel_id, None)

    def _get_history(self, channel_id: str) -> deque[Message]:
        if channel_id not in self._history:
            self._history[channel_id] = deque(maxlen=MAX_HISTORY)
        return self._history[channel_id]

    def _log_sep(self, channel_id: str) -> None:
        """Open a new turn block in the conversation log."""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _conv_log.info(f"\n{'═' * 60}\n[{ts}] channel={channel_id}")

    def _log(self, label: str, content: str) -> None:
        """
        Write one labeled event line inside the current turn.
        Labels are padded to 14 chars so multi-line turns stay readable.
        Examples:
          USER            → the raw user message
          →LLM[route]     → messages sent to the routing LLM call
          ←LLM[route]     → raw response from the routing LLM (think tags intact)
          THINK[route]    → extracted chain-of-thought from routing response
          LLM[route]      → clean JSON response after stripping think tags
          →LLM[discord]   → messages sent to the skill execution LLM call
          ←LLM[discord]   → raw response from the execution LLM
          THINK[discord]  → extracted chain-of-thought from execution response
          LLM[discord]    → clean JSON response
          CALL            → skill.action(params) being invoked
          OK / ERROR      → skill execution result
          REPLY           → what was sent back to the user
        """
        _conv_log.info(f"  {label:<16}: {content}")

    def _log_messages(self, label: str, messages: list[Message]) -> None:
        """
        Log the messages array being sent to an LLM call.
        System prompts are truncated to 400 chars to keep logs manageable
        (they're long but deterministic — the full text is in the SKILL.md files).
        User and assistant messages are always logged in full.
        """
        _conv_log.info(f"  {label:<16}:")
        for msg in messages:
            content = msg.content
            if msg.role == "system" and len(content) > 400:
                content = content[:400] + f"\n    … ({len(msg.content) - 400} more chars, see SKILL.md)"
            # Indent continuation lines so they're visually nested under the role
            indented = content.replace("\n", "\n" + " " * 22)
            _conv_log.info(f"    [{msg.role:>9}]  {indented}")

    # ── Core processing ────────────────────────────────────────────────────────

    async def process(self, content: str, channel_id: str = "default") -> dict:
        """
        Process one user turn.

        Returns a dict with at minimum a "reply" key.
        When a skill is invoked it also contains: type, skill, action, params,
        skill_result.
        """
        if not self._router_prompt:
            self.build_system_prompt()

        history = self._get_history(channel_id)
        history.append(Message(role="user", content=content))

        self._log_sep(channel_id)
        self._log("USER", content)

        # ── Step 1: Route ──────────────────────────────────────────────────────
        routing: dict = {}
        route_messages = [Message(role="system", content=self._router_prompt), *history]
        try:
            self._log_messages("→LLM[route]", route_messages)
            routing_resp = await llm_router.chat(route_messages, skill_name="orchestrator")
        except Exception as exc:
            logger.exception("agent_runner.process: LLM call failed at routing step")
            self._log("←LLM[route]", f"LLM ERROR: {exc}")
            routing = {"skill": None, "reply": f"Sorry, the AI model is unavailable: {exc}"}
        else:
            raw = routing_resp.content
            self._log("←LLM[route]", raw)
            thinking, clean = _split_think(raw)
            if thinking:
                self._log("THINK[route]", thinking)
            self._log("LLM[route]", clean)
            try:
                routing = _extract_json(clean)
            except ValueError as exc:
                logger.error(f"agent_runner.process: JSON parse failed at routing step — {exc}")
                self._log("PARSE ERROR", str(exc))
                routing = {"skill": None, "reply": f"Sorry, I couldn't parse my own response: {exc}"}

        skill_name: str | None = routing.get("skill")

        # ── No skill: use router's reply directly ──────────────────────────────
        if not skill_name:
            reply = routing.get("reply", "")
            history.append(Message(role="assistant", content=reply))
            self._log("REPLY", reply)
            return {"type": "reply", "reply": reply}

        # ── Step 2: Execute with full SKILL.md ────────────────────────────────
        loaded = self._registry.get(skill_name)
        if loaded is None:
            reply = f"I chose skill '{skill_name}' but it's not loaded."
            history.append(Message(role="assistant", content=reply))
            self._log("ERROR", reply)
            self._log("REPLY", reply)
            return {"type": "reply", "reply": reply}

        executor_prompt = _EXECUTOR_PROMPT_TEMPLATE.format(
            skill_name=skill_name,
            skill_body=loaded.markdown.body,
        )
        plan: dict = {}
        exec_messages = [
            Message(role="system", content=executor_prompt),
            Message(role="user", content=content),
        ]
        try:
            self._log_messages(f"→LLM[{skill_name}]", exec_messages)
            exec_resp = await llm_router.chat(exec_messages, skill_name=skill_name)
        except Exception as exc:
            logger.exception(f"agent_runner.process: LLM call failed at execution step (skill={skill_name})")
            reply = f"I chose skill '{skill_name}' but the AI model is unavailable: {exc}"
            history.append(Message(role="assistant", content=reply))
            self._log(f"←LLM[{skill_name}]", f"LLM ERROR: {exc}")
            self._log("REPLY", reply)
            return {"type": "reply", "reply": reply}

        raw = exec_resp.content
        self._log(f"←LLM[{skill_name}]", raw)
        thinking, clean = _split_think(raw)
        if thinking:
            self._log(f"THINK[{skill_name}]", thinking)
        self._log(f"LLM[{skill_name}]", clean)
        try:
            plan = _extract_json(clean)
        except ValueError as exc:
            logger.error(f"agent_runner.process: JSON parse failed at execution step (skill={skill_name}) — {exc}")
            reply = f"I chose skill '{skill_name}' but couldn't parse the action plan: {exc}"
            history.append(Message(role="assistant", content=reply))
            self._log("PARSE ERROR", str(exc))
            self._log("REPLY", reply)
            return {"type": "reply", "reply": reply}

        action = plan.get("action", "")
        params = plan.get("params") or {}
        reply  = plan.get("reply", "")

        # ── Run the skill handler ──────────────────────────────────────────────
        self._log("CALL", f"{skill_name}.{action}  params={json.dumps(params, ensure_ascii=False)}")
        skill_result = await self._registry.execute(skill_name, action, params)

        if skill_result.success:
            self._log("OK", skill_result.message or "success")
            if skill_result.message and not reply:
                reply = skill_result.message
        else:
            self._log("ERROR", skill_result.error or "unknown error")
            reply = f"I tried `{skill_name}.{action}` but hit an error: {skill_result.error}"

        history.append(Message(role="assistant", content=reply))
        self._log("REPLY", reply)

        return {
            "type": "skill_call",
            "skill": skill_name,
            "action": action,
            "params": params,
            "reply": reply,
            "skill_result": skill_result.as_dict(),
        }

    # ── Queue processor ────────────────────────────────────────────────────────

    async def run_queue(self) -> None:
        """Drain the orchestrator task queue from Redis."""
        logger.info("Agent queue processor started (queue:orchestrator)")
        while True:
            task = await message_bus.dequeue("queue:orchestrator", timeout=5)
            if task is None:
                continue

            try:
                channel_id = str(task.get("reply_channel_id") or "queue_default")
                result = await self.process(
                    content=task.get("content", ""),
                    channel_id=channel_id,
                )
                reply_text = result.get("reply", "")
                reply_channel_id = task.get("reply_channel_id")
                if reply_channel_id and reply_text:
                    await message_bus.publish("events:discord:send_message", {
                        "message": reply_text,
                        "channel_id": reply_channel_id,
                    })
            except Exception:
                logger.exception("Agent queue processor error")
