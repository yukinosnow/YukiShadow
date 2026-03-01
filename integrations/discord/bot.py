"""
YukiShadow - Discord Bot

The bot serves two roles:
  1. Inbound: forward user messages / commands to the orchestrator queue
  2. Outbound: listen on the message bus and deliver notifications to channels

Commands (prefix: !)
  !ask <question>       – send any request to the agent
  !remind <text>        – shortcut for creating a reminder
  !reminders            – list upcoming reminders
  !skills               – show loaded skills

The bot receives outbound messages via Redis pub/sub on 'events:discord:send_message'.
"""

from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

from core.message_bus import message_bus

logger = logging.getLogger(__name__)


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
        self._outbound_task: asyncio.Task | None = None

    async def setup_hook(self) -> None:
        # Register slash-style commands as cog
        await self.add_cog(YukiCog(self))
        # Start listening for outbound events
        self._outbound_task = asyncio.create_task(self._deliver_outbound())

    async def on_ready(self) -> None:
        logger.info(f"Discord bot ready as {self.user} (id={self.user.id})")
        await message_bus.publish("events:discord:bot_ready", {
            "user": str(self.user),
            "user_id": self.user.id,
        })

    async def on_message(self, message: discord.Message) -> None:
        if message.author == self.user:
            return
        # Forward every non-command message to orchestrator for context
        if not message.content.startswith(self._settings.discord_command_prefix):
            await message_bus.publish("events:discord:message_received", {
                "content": message.content,
                "author_id": message.author.id,
                "author_name": str(message.author),
                "channel_id": message.channel.id,
                "guild_id": message.guild.id if message.guild else None,
            })
        await self.process_commands(message)

    async def _deliver_outbound(self) -> None:
        """Listen for 'send_message' events and post them to Discord."""
        async for event in message_bus.subscribe("events:discord:send_message"):
            try:
                channel_id = (
                    event.get("channel_id") or self._settings.discord_notification_channel_id
                )
                if not channel_id:
                    logger.warning("No channel_id in event and DISCORD_NOTIFICATION_CHANNEL_ID not set")
                    continue

                channel = self.get_channel(int(channel_id))
                if channel is None:
                    logger.warning(f"Channel {channel_id} not found (bot may not be in that guild)")
                    continue

                embed = None
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
            except Exception:
                logger.exception("Failed to deliver outbound Discord message")

    async def close(self) -> None:
        if self._outbound_task:
            self._outbound_task.cancel()
        await super().close()


class YukiCog(commands.Cog, name="YukiShadow"):

    def __init__(self, bot: YukiBot) -> None:
        self.bot = bot

    @commands.command(name="ask", help="Send a request to the YukiShadow agent.")
    async def ask(self, ctx: commands.Context, *, question: str):
        await ctx.message.add_reaction("⏳")
        await message_bus.enqueue("queue:orchestrator", {
            "type": "user_request",
            "content": question,
            "reply_channel_id": ctx.channel.id,
            "author_id": ctx.author.id,
        })

    @commands.command(name="remind", help="Create a reminder. E.g. !remind tomorrow 3pm team meeting")
    async def remind(self, ctx: commands.Context, *, text: str):
        await ctx.message.add_reaction("⏳")
        await message_bus.enqueue("queue:orchestrator", {
            "type": "user_request",
            "skill_hint": "reminder",
            "content": f"Create a reminder: {text}",
            "reply_channel_id": ctx.channel.id,
            "author_id": ctx.author.id,
        })

    @commands.command(name="reminders", help="List upcoming reminders.")
    async def reminders(self, ctx: commands.Context):
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
        from core.config import settings
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{settings.orchestrator_base_url}/skills", timeout=5)
                data = resp.json()
            lines = ["**YukiShadow Skills**"]
            for s in data.get("skills", []):
                lines.append(f"• **{s['name']}** – {s['description']}")
            await ctx.send("\n".join(lines))
        except Exception as e:
            await ctx.send(f"Could not fetch skills: {e}")


async def run_discord_bot() -> None:
    """Entry point for the Discord bot service."""
    from core.config import settings

    if not settings.discord_bot_token:
        raise RuntimeError("DISCORD_BOT_TOKEN is not set in .env")

    await message_bus.connect()
    bot = YukiBot()
    try:
        await bot.start(settings.discord_bot_token)
    finally:
        await message_bus.disconnect()
