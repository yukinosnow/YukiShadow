"""
YukiShadow - Main Entry Point

Usage:
  python main.py orchestrator   # Orchestrator API (FastAPI, default port 8080)
  python main.py discord        # Discord bot
  python main.py scheduler      # Reminder scheduler
  python main.py mcp            # MCP server (stdio, for Claude Desktop)
  python main.py mqtt           # MQTT bridge (requires Jetson on the network)
  python main.py all            # All services except MCP (concurrent)

Tip: In production, run each service with its own process or Docker container.
"""

import asyncio
import logging
import sys

import uvicorn

from core.config import settings

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s [%(name)-20s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger("main")


# ── Service launchers ─────────────────────────────────────────────────────────

async def start_orchestrator() -> None:
    config = uvicorn.Config(
        "orchestrator.app:app",
        host="0.0.0.0",
        port=settings.orchestrator_port,
        reload=settings.debug,
        log_level="debug" if settings.debug else "info",
    )
    server = uvicorn.Server(config)
    await server.serve()


async def start_discord() -> None:
    from integrations.discord.bot import run_discord_bot
    await run_discord_bot()


async def start_scheduler() -> None:
    from scheduler.service import run_scheduler
    await run_scheduler()


async def start_mcp() -> None:
    from mcp_server.server import run_mcp_server
    await run_mcp_server()


async def start_mqtt() -> None:
    from integrations.mqtt.client import run_mqtt_bridge
    await run_mqtt_bridge()


async def start_all() -> None:
    """Run all primary services concurrently (except MCP which uses stdio)."""
    logger.info("Starting all services...")
    tasks = [
        asyncio.create_task(start_orchestrator(), name="orchestrator"),
        asyncio.create_task(start_discord(), name="discord"),
        asyncio.create_task(start_scheduler(), name="scheduler"),
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)
    for name, result in zip(["orchestrator", "discord", "scheduler"], results):
        if isinstance(result, Exception):
            logger.error(f"Service '{name}' failed: {result}")


# ── Entry point ───────────────────────────────────────────────────────────────

RUNNERS = {
    "orchestrator": start_orchestrator,
    "discord": start_discord,
    "scheduler": start_scheduler,
    "mcp": start_mcp,
    "mqtt": start_mqtt,
    "all": start_all,
}


def main() -> None:
    service = sys.argv[1] if len(sys.argv) > 1 else "orchestrator"
    runner = RUNNERS.get(service)

    if runner is None:
        print(f"Unknown service: '{service}'")
        print(f"Available: {', '.join(RUNNERS)}")
        sys.exit(1)

    logger.info(f"Starting service: {service}")
    try:
        asyncio.run(runner())
    except KeyboardInterrupt:
        logger.info("Shutting down")


if __name__ == "__main__":
    main()
