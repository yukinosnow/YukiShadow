"""
YukiShadow - Orchestrator API (FastAPI)

Endpoints:
  GET  /health                  – liveness check
  POST /chat                    – send a natural-language message to the agent
  POST /skills/execute          – directly invoke a skill action (no LLM)
  GET  /skills                  – list all loaded skills
  GET  /skills/{name}           – describe a single skill
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from core.message_bus import message_bus
from orchestrator.agent_runner import AgentRunner
from orchestrator.skill_registry import SkillRegistry
from storage.database import init_db

logger = logging.getLogger(__name__)

# Module-level singletons (accessible by tests and other services)
skill_registry = SkillRegistry()
agent_runner = AgentRunner(skill_registry)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────────────────────────
    await message_bus.connect()
    await init_db()
    await skill_registry.load_all()
    queue_task = asyncio.create_task(agent_runner.run_queue())
    logger.info("Orchestrator ready")

    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    queue_task.cancel()
    try:
        await queue_task
    except asyncio.CancelledError:
        pass
    await skill_registry.unload_all()
    await message_bus.disconnect()
    logger.info("Orchestrator shut down")


app = FastAPI(
    title="YukiShadow",
    description="Personal AI assistant orchestrator",
    version="0.1.0",
    lifespan=lifespan,
)


# ── Request / Response models ─────────────────────────────────────────────────

class ChatRequest(BaseModel):
    content: str
    context: dict | None = None


class SkillExecuteRequest(BaseModel):
    skill: str
    action: str
    params: dict = {}


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "orchestrator"}


@app.post("/chat")
async def chat(req: ChatRequest):
    result = await agent_runner.process(req.content, req.context)
    return result


@app.post("/skills/execute")
async def execute_skill(req: SkillExecuteRequest):
    result = await skill_registry.execute(req.skill, req.action, req.params)
    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)
    return result.as_dict()


@app.get("/skills")
async def list_skills():
    return {"skills": skill_registry.summary()}


@app.get("/skills/{name}")
async def describe_skill(name: str):
    loaded = skill_registry.get(name)
    if loaded is None:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")
    md = loaded.markdown
    return {
        "name": md.name,
        "description": md.description,
        "version": md.version,
        "llm_provider": md.llm_provider,
        "tools": md.mcp_tools(),
    }
