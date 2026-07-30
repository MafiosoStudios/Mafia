from __future__ import annotations
from dotenv import load_dotenv

import asyncio
import logging

import discord
from discord.ext import commands

load_dotenv()
from config import BotConfig, get_emoji
from database.database import DatabaseManager
from game_engine import GameEngine
import roles
from game_manager import GameManager
from lobby_system import LobbyManager
from utils.message_queue import DiscordMessageQueue

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


class AnimeMafiaBot(commands.Bot):
    def __init__(self, config: BotConfig) -> None:
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True
        intents.message_content = True
        super().__init__(command_prefix=config.command_prefix, intents=intents, help_command=None)
        self.config = config
        self.db = DatabaseManager()
        self.game_manager = GameManager()
        self.game_engine = GameEngine(self.db)
        self.game_engine.bot = self
        self.lobby_manager = LobbyManager(self, self.game_manager, self.game_engine, self.db, self.config)
        self.message_queue = DiscordMessageQueue(self)

    async def setup_hook(self) -> None:
        await self.db.initialize()
        self.message_queue.start()
        await self._load_extensions()
        await self.tree.sync()

    async def close(self) -> None:
        await self.message_queue.stop()
        await super().close()
        await self.db.close()

    async def on_ready(self) -> None:
        logger.info("Logged in as %s (%s)", self.user, self.user.id if self.user else "unknown")

        # 1. Send restart confirmation message immediately
        import sys
        if "--restart-channel" in sys.argv:
            try:
                idx = sys.argv.index("--restart-channel")
                channel_id = int(sys.argv[idx + 1])
                channel = self.get_channel(channel_id)
                if not channel:
                    channel = await self.fetch_channel(channel_id)
                if channel:
                    from config import get_emoji
                    await channel.send(f"**Bot process has restarted, getcholazyassup and get to work**")
                sys.argv.pop(idx + 1)
                sys.argv.pop(idx)
            except Exception:
                logger.exception("Failed to send restart confirmation message.")

        # 2. Sync commands subsequently in the background so it doesn't block interactions
        self._track_task("command_sync", self._sync_commands_bg())

    _background_tasks: dict[str, asyncio.Task] = {}

    def _track_task(self, name: str, coro) -> asyncio.Task:
        """Track a background task with exception handling to prevent memory leaks."""
        task = asyncio.create_task(coro)
        task.add_done_callback(lambda t: self._handle_task_exception(t, name))
        self._background_tasks[name] = task
        return task

    def _handle_task_exception(self, task: asyncio.Task, name: str) -> None:
        """Log exceptions from background tasks without crashing."""
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception(f"Background task '{name}' failed")

    async def _sync_commands_bg(self) -> None:
        """Sync commands in the background so it doesn't block interactions."""
        for guild in self.guilds:
            try:
                self.tree.clear_commands(guild=guild)
                await self.tree.sync(guild=guild)
            except Exception:
                pass
        try:
            await self.tree.sync()
            logger.info("Global commands synced successfully.")
        except Exception:
            logger.exception("Failed to sync global commands.")

    async def _safe_send_ctx(self, ctx: commands.Context, content: str) -> None:
        try:
            if ctx.interaction is not None:
                if ctx.interaction.response.is_done():
                    await ctx.interaction.followup.send(content, ephemeral=True)
                else:
                    await ctx.interaction.response.send_message(content, ephemeral=True)
            else:
                await ctx.send(content)
        except Exception:
            try:
                if ctx.channel:
                    await ctx.channel.send(content)
            except Exception:
                pass

    async def on_app_command_error(self, interaction: discord.Interaction, error: discord.app_commands.AppCommandError) -> None:
        logger.exception("App command failed: %s", error)
        msg = "Something went wrong processing that command. Try again."
        if isinstance(error, discord.app_commands.CommandNotFound):
            msg = "That command doesn't exist. Check your spelling and try again."
        elif isinstance(error, discord.app_commands.MissingPermissions):
            msg = "You don't have permission to use this command."
        elif isinstance(error, discord.app_commands.NoPrivateMessage):
            msg = "This command can only be used inside a server."
        elif isinstance(error, discord.app_commands.TransformerError):
            msg = "Invalid parameters provided for this command."
        elif isinstance(error, discord.app_commands.CommandOnCooldown):
            msg = f"{get_emoji('clock')} **Calm down, bih—** That command is on cooldown. Try again in **{error.retry_after:.1f}s**."

        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            pass

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.CommandInvokeError) and error.original:
            error = error.original

        logger.exception("Prefix command failed: %s", error)

        if isinstance(error, commands.CommandNotFound):
            await self._safe_send_ctx(ctx, "That command doesn't exist. Check your spelling or type !help.")
            return

        if isinstance(error, commands.MissingRequiredArgument):
            param = error.param.name if hasattr(error, "param") and error.param else "value"
            await self._safe_send_ctx(ctx, f"You missed the required parameter '{param}' for this command. Check parameter usage and try again.")
            return

        if isinstance(error, (commands.BadArgument, commands.BadLiteralArgument)):
            await self._safe_send_ctx(ctx, "Invalid parameters provided for this command. Check your input and try again.")
            return

        if isinstance(error, (commands.MissingPermissions, commands.CheckFailure, commands.MissingRole)):
            await self._safe_send_ctx(ctx, "You don't have permission to use this command.")
            return

        if isinstance(error, commands.NoPrivateMessage):
            await self._safe_send_ctx(ctx, "This command can only be used inside a server.")
            return

        if isinstance(error, commands.CommandOnCooldown):
            await self._safe_send_ctx(ctx, f"{get_emoji('clock')} **Calm down, bih—** That command is on cooldown. Try again in **{error.retry_after:.1f}s**.")
            return

        await self._safe_send_ctx(ctx, "Something went wrong processing that command. Try again.")

    async def _load_extensions(self) -> None:
        extensions = (
            "cogs.help",
            "cogs.game",
            "cogs.lobby",
            "cogs.profile",
            "cogs.shop",
            "cogs.leaderboard",
            "cogs.admin",
            "cogs.events",
        )
        for extension in extensions:
            try:
                await self.load_extension(extension)
            except Exception:
                logger.exception("Failed to load extension %s", extension)


async def main() -> None:
    config = BotConfig.from_env()
    if not config.token:
        raise RuntimeError("DISCORD_TOKEN is not set.")

    bot = AnimeMafiaBot(config)
    async with bot:
        await bot.start(config.token)


if __name__ == "__main__":
    asyncio.run(main())
