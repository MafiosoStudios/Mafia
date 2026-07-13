from __future__ import annotations

import logging

import discord
from discord.ext import commands

logger = logging.getLogger(__name__)


class EventsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        game_manager = getattr(self.bot, "game_manager", None)
        game_engine = getattr(self.bot, "game_engine", None)
        if game_manager is None or game_engine is None:
            return

        active = await game_manager.get_game_by_guild(member.guild.id)
        if active is None:
            return

        session = await game_engine.get_session(active.game_id)
        if session is None or member.id not in session.players:
            return

        try:
            await game_engine.mark_disconnected(active.game_id, member.id)
        except Exception:
            logger.exception("Failed to mark member %s disconnected in game %s", member.id, active.game_id)

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild) -> None:
        game_manager = getattr(self.bot, "game_manager", None)
        game_engine = getattr(self.bot, "game_engine", None)
        database = getattr(self.bot, "db", None)
        lobby_manager = getattr(self.bot, "lobby_manager", None)
        active = await game_manager.get_game_by_guild(guild.id) if game_manager is not None else None

        if lobby_manager is not None:
            await lobby_manager.close_lobby(guild.id)

        if active is not None and game_engine is not None:
            session = await game_engine.get_session(active.game_id)
            if session is not None:
                await game_engine.end_game(active.game_id, winner_faction=None, draw_reason="guild_removed")

        if active is not None and game_manager is not None:
            await game_manager.remove_game(active.game_id)

        if database is not None:
            await database.delete_guild_data(guild.id)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EventsCog(bot))
