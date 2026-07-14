from __future__ import annotations
from dotenv import load_dotenv

import asyncio
import logging

import discord
from discord.ext import commands

load_dotenv()
from config import BotConfig
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
                    await channel.send("✅ **Bot has successfully restarted and is now online!**")
                sys.argv.pop(idx + 1)
                sys.argv.pop(idx)
            except Exception:
                logger.exception("Failed to send restart confirmation message.")

        # 2. Sync commands subsequently in the background so it doesn't block interactions
        import asyncio
        async def sync_bg():
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

        asyncio.create_task(sync_bg())

    async def on_app_command_error(self, interaction: discord.Interaction, error: discord.app_commands.AppCommandError) -> None:
        logger.exception("App command failed: %s", error)
        if interaction.response.is_done():
            await interaction.followup.send("Something went wrong while running that command.", ephemeral=True)
        else:
            await interaction.response.send_message("Something went wrong while running that command.", ephemeral=True)

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        logger.exception("Prefix command failed: %s", error)
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("You do not have permission to use that command.")
            return
        if isinstance(error, commands.CommandNotFound):
            return
        await ctx.send("Something went wrong while running that command.")

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
