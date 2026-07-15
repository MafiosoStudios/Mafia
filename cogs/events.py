from __future__ import annotations

import logging

import discord
from discord.ext import commands

from config import get_emoji

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

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if message.guild is not None:
            return

        game_manager = getattr(self.bot, "game_manager", None)
        game_engine = getattr(self.bot, "game_engine", None)
        if game_manager is None or game_engine is None:
            return

        target_session = None
        player_state = None
        for session in list(game_engine._sessions.values()):
            if message.author.id in session.players:
                target_session = session
                player_state = session.players[message.author.id]
                break

        if not target_session or not player_state:
            return

        # Check Tōsen Bankai communication
        if player_state.alive and message.content.startswith("."):
            content_without_dot = message.content[1:].strip()
            
            # Case 1: Tōsen sending to Prisoner
            if player_state.role_key == "tosen":
                prisoner_id = player_state.metadata.get("detained_player_id")
                if prisoner_id:
                    guild = self.bot.get_guild(target_session.game_handle.guild_id)
                    prisoner_mem = guild.get_member(prisoner_id) if guild else None
                    if prisoner_mem:
                        try:
                            self.bot.message_queue.send(prisoner_mem, f"🌑 **[Bankai Chat] Tōsen**: {content_without_dot}")
                            await message.channel.send(f"🌑 **[Bankai Chat] To Prisoner**: {content_without_dot}")
                        except Exception:
                            pass
                    else:
                        await message.channel.send("❌ Could not send message: Prisoner is not in the server.")
                else:
                    await message.channel.send("❌ You do not have any prisoner detained tonight.")
                return
            
            # Case 2: Prisoner sending to Tōsen
            elif player_state.metadata.get("detained"):
                tosen_id = None
                for pid, ps in target_session.players.items():
                    if ps.role_key == "tosen" and ps.alive:
                        tosen_id = pid
                        break
                if tosen_id:
                    guild = self.bot.get_guild(target_session.game_handle.guild_id)
                    tosen_mem = guild.get_member(tosen_id) if guild else None
                    if tosen_mem:
                        try:
                            self.bot.message_queue.send(tosen_mem, f"🌑 **[Bankai Chat] Prisoner**: {content_without_dot}")
                            await message.channel.send(f"🌑 **[Bankai Chat] To Tōsen**: {content_without_dot}")
                        except Exception:
                            pass
                    else:
                        await message.channel.send("❌ Could not send message: Tōsen is not in the server.")
                else:
                    await message.channel.send("❌ Tōsen is not active or dead.")
                return

        # Fallback to Mafia Chat if they belong to Villain faction
        if player_state.faction != "Villain":
            return

        guild = self.bot.get_guild(target_session.game_handle.guild_id)
        if not guild:
            return

        sender_name = message.author.display_name
        content = message.content
        if player_state.alive:
            formatted_msg = f"{get_emoji('group')} **[Mafia Chat] {sender_name}**: {content}"
        else:
            formatted_msg = f"~~{get_emoji('group')} [Mafia Chat] [Dead] {sender_name}: {content}~~"

        for pid, pstate in target_session.players.items():
            if pid == message.author.id:
                continue
            if pstate.faction == "Villain":
                member = guild.get_member(pid)
                if member:
                    try:
                        self.bot.message_queue.send(member, formatted_msg)
                    except Exception:
                        pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EventsCog(bot))
