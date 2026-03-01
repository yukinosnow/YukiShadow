"""
YukiShadow - MCP Server

Exposes all registered skills as MCP tools so Claude Desktop (or any MCP client)
can invoke them directly.

Transport: stdio (for Claude Desktop integration)
Tool names use the format:  <skill_name>__<action_name>
  e.g. reminder__create_reminder, discord__send_message

Usage in claude_desktop_config.json:
  {
    "mcpServers": {
      "yukishadow": {
        "command": "python",
        "args": ["main.py", "mcp"],
        "cwd": "C:/Project/YukiShadow"
      }
    }
  }
"""

from __future__ import annotations

import logging

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

logger = logging.getLogger(__name__)

app = Server("yukishadow")

_ORCHESTRATOR_URL: str | None = None


def _base_url() -> str:
    global _ORCHESTRATOR_URL
    if _ORCHESTRATOR_URL is None:
        from core.config import settings
        _ORCHESTRATOR_URL = settings.orchestrator_base_url
    return _ORCHESTRATOR_URL


# ── Tool listing ──────────────────────────────────────────────────────────────

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    """Fetch skill tool definitions from the running orchestrator."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{_base_url()}/skills")
            resp.raise_for_status()
            skills = resp.json().get("skills", [])

            tools: list[types.Tool] = []
            for skill_info in skills:
                # Fetch full tool schemas for this skill
                detail_resp = await client.get(f"{_base_url()}/skills/{skill_info['name']}")
                if detail_resp.status_code != 200:
                    continue
                detail = detail_resp.json()
                for tool in detail.get("tools", []):
                    # MCP tool name: skill__action  (double underscore separator)
                    mcp_name = f"{skill_info['name']}__{tool['name']}"
                    tools.append(types.Tool(
                        name=mcp_name,
                        description=f"[{skill_info['name']}] {tool['description']}",
                        inputSchema=tool.get("inputSchema", {"type": "object", "properties": {}}),
                    ))
            return tools
    except Exception as e:
        logger.error(f"Failed to list tools from orchestrator: {e}")
        return []


# ── Tool execution ────────────────────────────────────────────────────────────

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    """Route a tool call to the orchestrator's /skills/execute endpoint."""
    # Parse skill and action from "skill__action"
    parts = name.split("__", 1)
    if len(parts) != 2:
        return [types.TextContent(type="text", text=f"Invalid tool name format: '{name}'")]

    skill_name, action = parts

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{_base_url()}/skills/execute",
                json={"skill": skill_name, "action": action, "params": arguments},
            )
            result = resp.json()

        if resp.status_code >= 400:
            return [types.TextContent(type="text", text=f"Error: {result.get('detail', resp.text)}")]

        message = result.get("message") or str(result.get("data", "Done"))
        return [types.TextContent(type="text", text=message)]

    except Exception as e:
        logger.exception(f"MCP tool call failed: {name}")
        return [types.TextContent(type="text", text=f"Error calling {name}: {e}")]


# ── Entry point ───────────────────────────────────────────────────────────────

async def run_mcp_server() -> None:
    """Start the MCP server in stdio mode (for Claude Desktop)."""
    logger.info("Starting MCP server (stdio transport)")
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )
