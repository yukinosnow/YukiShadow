"""
YukiShadow - Discord Service

Runs as a standalone microservice: Discord bot + FastAPI sidecar in one process.
The HTTP server lets you test and control the bot without needing the full stack.

HTTP endpoints (default port 8090):
  GET  /health          → bot status, guild count, latency, Redis connection
  POST /send            → deliver a message/embed to a channel (curl-testable)

Bot commands (prefix: !)
  !ask <text>           → send to orchestrator agent
  !remind <text>        → create a reminder via orchestrator
  !reminders            → list upcoming reminders
  !skills               → list loaded skills (fetched from orchestrator)

Redis integration is optional. If Redis is unreachable at startup, the bot
still runs and accepts HTTP /send requests. Redis subscription is retried in
the background every 10 s.
"""

from __future__ import annotations

import asyncio
import logging

import discord
import uvicorn
from discord.ext import commands
from fastapi import FastAPI
from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ── Shared message delivery ───────────────────────────────────────────────────

async def deliver(bot: "YukiBot", event: dict) -> None:
    """
    Send a message/embed to a Discord channel.
    Used by both the Redis listener and the HTTP /send endpoint.
    """
    from core.config import settings

    channel_id = event.get("channel_id") or settings.discord_notification_channel_id
    if not channel_id:
        logger.warning("deliver() called with no channel_id and DISCORD_NOTIFICATION_CHANNEL_ID not set")
        return

    channel = bot.get_channel(int(channel_id))
    if channel is None:
        logger.warning(f"Channel {channel_id} not found (bot not in that guild?)")
        return

    embed: discord.Embed | None = None
    if embed_data := event.get("embed"):
        embed = discord.Embed(
            title=embed_data.get("title", ""),
            description=embed_data.get("description", ""),
            color=embed_data.get("color", 0x5865F2),
        )
        for field in embed_data.get("fields", []):
            embed.add_field(
                name=field.get("name", ""),
                value=field.get("value", ""),
                inline=field.get("inline", False),
            )

    text = event.get("message") or None
    await channel.send(content=text, embed=embed)


# ── FastAPI sidecar ───────────────────────────────────────────────────────────

class SendRequest(BaseModel):
    message: str = ""
    channel_id: int | None = None
    embed: dict | None = None


def create_api(bot: "YukiBot") -> FastAPI:
    api = FastAPI(
        title="YukiShadow Discord Service",
        description="Sidecar HTTP server for the Discord bot.",
    )

    @api.get("/health")
    async def health():
        return {
            "status": "ready" if bot.is_ready() else "starting",
            "bot_user": str(bot.user) if bot.user else None,
            "guild_count": len(bot.guilds),
            "latency_ms": round(bot.latency * 1000, 1) if bot.is_ready() else None,
            "redis_connected": bot.redis_connected,
        }

    @api.post("/send")
    async def send(req: SendRequest):
        await deliver(bot, req.model_dump())
        return {"ok": True}

    return api


# ── Discord bot ───────────────────────────────────────────────────────────────

class YukiBot(commands.Bot):

    def __init__(self) -> None:
        from core.config import settings
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(
            command_prefix=settings.discord_command_prefix,
            intents=intents,
            help_command=commands.DefaultHelpCommand(),
        )
        self._settings = settings
        self.redis_connected: bool = False
        self._redis_task: asyncio.Task | None = None

    async def setup_hook(self) -> None:
        await self.add_cog(YukiCog(self))
        # Try to connect to Redis and start the outbound listener.
        # Retries in the background if Redis is not yet available.
        self._redis_task = asyncio.create_task(self._redis_loop())

    async def on_ready(self) -> None:
        logger.info(f"Discord bot ready: {self.user} (id={self.user.id})")
        logger.info(f"  guilds : {[g.name for g in self.guilds]}")

    async def on_message(self, message: discord.Message) -> None:
        if message.author == self.user:
            return
        # Forward plain messages (not commands) to orchestrator via Redis
        if self.redis_connected and not message.content.startswith(self._settings.discord_command_prefix):
            try:
                from core.message_bus import message_bus
                await message_bus.publish("events:discord:message_received", {
                    "content": message.content,
                    "author_id": message.author.id,
                    "author_name": str(message.author),
                    "channel_id": message.channel.id,
                    "guild_id": message.guild.id if message.guild else None,
                })
            except Exception:
                logger.debug("Could not forward message to Redis (bus down?)")
        await self.process_commands(message)

    async def close(self) -> None:
        if self._redis_task:
            self._redis_task.cancel()
        await super().close()

    # ── Redis integration (optional) ──────────────────────────────────────────

    async def _redis_loop(self) -> None:
        """
        Try to connect to Redis and subscribe to outbound message events.
        If Redis is unavailable, wait and retry. Never crashes the bot.
        """
        from core.message_bus import message_bus

        while True:
            try:
                if not self.redis_connected:
                    await message_bus.connect()
                    self.redis_connected = True
                    logger.info("Redis connected — listening for events:discord:send_message")

                async for event in message_bus.subscribe("events:discord:send_message"):
                    try:
                        await deliver(self, event)
                    except Exception:
                        logger.exception("Failed to deliver Redis event")

            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.redis_connected = False
                logger.warning(f"Redis unavailable ({exc}), retrying in 10 s…")
                await asyncio.sleep(10)


# ── Commands cog ──────────────────────────────────────────────────────────────

class YukiCog(commands.Cog, name="YukiShadow"):

    def __init__(self, bot: YukiBot) -> None:
        self.bot = bot

    async def _require_redis(self, ctx: commands.Context) -> bool:
        if not self.bot.redis_connected:
            await ctx.send("⚠️ Redis is not connected — orchestrator commands unavailable.")
            return False
        return True

    @commands.command(name="ask", help="Ask the YukiShadow agent anything.")
    async def ask(self, ctx: commands.Context, *, question: str):
        if not await self._require_redis(ctx):
            return
        await ctx.message.add_reaction("⏳")
        from core.message_bus import message_bus
        await message_bus.enqueue("queue:orchestrator", {
            "type": "user_request",
            "content": question,
            "reply_channel_id": ctx.channel.id,
            "author_id": ctx.author.id,
        })

    @commands.command(name="remind", help="Create a reminder. E.g. !remind tomorrow 3pm meeting")
    async def remind(self, ctx: commands.Context, *, text: str):
        if not await self._require_redis(ctx):
            return
        await ctx.message.add_reaction("⏳")
        from core.message_bus import message_bus
        await message_bus.enqueue("queue:orchestrator", {
            "type": "user_request",
            "skill_hint": "reminder",
            "content": f"Create a reminder: {text}",
            "reply_channel_id": ctx.channel.id,
            "author_id": ctx.author.id,
        })

    @commands.command(name="reminders", help="List upcoming reminders.")
    async def reminders(self, ctx: commands.Context):
        if not await self._require_redis(ctx):
            return
        from core.message_bus import message_bus
        await message_bus.enqueue("queue:orchestrator", {
            "type": "skill_call",
            "skill": "reminder",
            "action": "list_reminders",
            "params": {"limit": 10},
            "reply_channel_id": ctx.channel.id,
            "author_id": ctx.author.id,
        })

    @commands.command(name="skills", help="List loaded YukiShadow skills.")
    async def skills(self, ctx: commands.Context):
        import httpx
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self.bot._settings.orchestrator_base_url}/skills")
                data = resp.json()
            lines = ["**YukiShadow Skills**"]
            for s in data.get("skills", []):
                lines.append(f"• **{s['name']}** – {s['description']}")
            await ctx.send("\n".join(lines))
        except Exception as e:
            await ctx.send(f"Could not reach orchestrator: {e}")

    @commands.command(name="ping", help="Check if the bot is alive.")
    async def ping(self, ctx: commands.Context):
        latency = round(self.bot.latency * 1000, 1)
        redis = "✅" if self.bot.redis_connected else "❌"
        await ctx.send(f"🏓 Pong! Latency: {latency} ms | Redis: {redis}")


# ── Entry point ───────────────────────────────────────────────────────────────

async def _stdin_loop(bot: "YukiBot") -> None:
    """
    Interactive terminal for quick Discord testing.
    Active only when running `python main.py discord` directly.

    Usage:
      <message>                  → send to DISCORD_NOTIFICATION_CHANNEL_ID
      #<channel_id> <message>   → send to a specific channel
      /quit                      → exit
    """
    from core.config import settings

    loop = asyncio.get_event_loop()

    # Wait until the bot is connected before accepting input
    while not bot.is_ready():
        await asyncio.sleep(0.5)

    default_ch = settings.discord_notification_channel_id or "not set"
    print("\n╭─ Discord Test Shell ───────────────────────────────╮")
    print(f"│  Default channel : {str(default_ch):<33}│")
    print("│  Override        : #<channel_id> <message>        │")
    print("│  Exit            : /quit or Ctrl-C                │")
    print("╰────────────────────────────────────────────────────╯\n")

    while True:
        try:
            line: str = await loop.run_in_executor(
                None, lambda: input("discord › ")
            )
        except (KeyboardInterrupt, EOFError):
            print("\nExiting Discord shell.")
            break

        text = line.strip()
        if not text:
            continue
        if text.lower() in ("/quit", "/exit", "/q"):
            print("Exiting Discord shell.")
            break

        # Parse optional channel override: "#<id> <message>"
        channel_id = None
        message = text
        if text.startswith("#"):
            parts = text[1:].split(None, 1)
            if len(parts) == 2 and parts[0].isdigit():
                channel_id = int(parts[0])
                message = parts[1]

        try:
            await deliver(bot, {"message": message, "channel_id": channel_id})
            print("  ✓ sent\n")
        except Exception as exc:
            print(f"  ✗ {exc}\n")


async def run_discord_bot() -> None:
    from core.config import settings

    if not settings.discord_bot_token:
        raise RuntimeError("DISCORD_BOT_TOKEN is not set in .env")

    bot = YukiBot()
    api = create_api(bot)

    # Run uvicorn in the same asyncio event loop as the Discord bot
    uvicorn_config = uvicorn.Config(
        api,
        host="0.0.0.0",
        port=settings.discord_service_port,
        log_level="warning",   # keep uvicorn quiet; our own logger handles the rest
    )
    http_server = uvicorn.Server(uvicorn_config)

    logger.info(f"Discord HTTP server starting on port {settings.discord_service_port}")

    await asyncio.gather(
        http_server.serve(),
        bot.start(settings.discord_bot_token),
        _stdin_loop(bot),
        return_exceptions=True,
    )
