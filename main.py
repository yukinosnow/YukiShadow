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


# ── Redis bootstrap ────────────────────────────────────────────────────────────

async def _redis_reachable() -> bool:
    import redis.asyncio as aioredis
    try:
        r = await aioredis.from_url(settings.redis_url, decode_responses=True)
        await r.ping()
        await r.aclose()
        return True
    except Exception:
        return False


async def ensure_redis() -> None:
    """
    Start the Redis container via Docker Compose (idempotent) then wait up to
    15 s for it to accept connections.  Logs a warning but never raises so that
    services can still start without Redis.
    """
    if await _redis_reachable():
        logger.info("Redis already reachable, skipping docker compose")
        return

    logger.info("Starting Redis via Docker Compose...")
    proc = await asyncio.create_subprocess_exec(
        "docker", "compose", "up", "-d", "redis",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.warning(f"docker compose up redis failed: {stderr.decode().strip()}")

    for attempt in range(15):
        if await _redis_reachable():
            logger.info(f"Redis ready (waited {attempt + 1}s)")
            return
        await asyncio.sleep(1)

    logger.warning("Redis did not become available in time — running without it")

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s [%(name)-20s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger("main")


# ── Service launchers ─────────────────────────────────────────────────────────

async def start_orchestrator() -> None:
    await ensure_redis()
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
    await ensure_redis()
    from integrations.discord.bot import run_discord_bot
    await run_discord_bot()


async def start_scheduler() -> None:
    await ensure_redis()
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
    await ensure_redis()
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
