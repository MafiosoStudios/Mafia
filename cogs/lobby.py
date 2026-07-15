from __future__ import annotations

import discord
from discord.ext import commands

from config import BotConfig
from utils.embeds import build_status_embed
from utils.helpers import send_hybrid_response
from views.lobby_view import LobbyView


class LobbyCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.hybrid_command(name="lobby", description="View the current lobby status and roster")
    async def lobby(self, ctx: commands.Context) -> None:
        lobby_manager = getattr(self.bot, "lobby_manager", None)
        if lobby_manager is None:
            await send_hybrid_response(ctx, "Lobby system is not ready yet.", ephemeral=True)
            return
        
        guild_id = ctx.guild.id if ctx.guild is not None else 0
        lobby = await lobby_manager.get_lobby(guild_id)
        if lobby is None:
            await send_hybrid_response(
                ctx,
                "No active lobby found. Try `/lobby_create` to create one.",
                ephemeral=True,
            )
            return

        from utils.embeds import build_lobby_embed
        guild_name = lobby_manager._guild_name(guild_id)
        roster_lines = lobby_manager._render_roster(lobby)

        embed = build_lobby_embed(
            guild_name=guild_name,
            leader_text=f"<@{lobby.leader_id}>",
            roster_lines=roster_lines,
            current_players=len(lobby.players),
            min_players=lobby.min_players,
            max_players=lobby.max_players,
        )
        view = LobbyView(self.bot, lobby)
        message = await send_hybrid_response(
            ctx,
            embed=embed,
            view=view,
        )
        if message is not None:
            await lobby_manager.bind_lobby_message(guild_id, message)

    @commands.hybrid_command(name="lobby_create", description="Create a new game lobby")
    async def create_lobby(self, ctx: commands.Context) -> None:
        config: BotConfig = self.bot.config  # type: ignore[assignment]
        lobby_manager = getattr(self.bot, "lobby_manager", None)
        if lobby_manager is None:
            await send_hybrid_response(ctx, "Lobby system is not ready yet.", ephemeral=True)
            return
        lobby = await lobby_manager.create_lobby(
            guild_id=ctx.guild.id if ctx.guild is not None else 0,
            channel_id=ctx.channel.id if ctx.channel is not None else 0,
            host_id=ctx.author.id,
            min_players=config.min_players,
            max_players=config.max_players,
        )
        view = LobbyView(self.bot, lobby)
        from utils.embeds import build_lobby_embed
        guild_name = lobby_manager._guild_name(ctx.guild.id if ctx.guild is not None else 0)
        roster_lines = lobby_manager._render_roster(lobby)
        embed = build_lobby_embed(
            guild_name=guild_name,
            leader_text=f"<@{lobby.leader_id}>",
            roster_lines=roster_lines,
            current_players=len(lobby.players),
            min_players=lobby.min_players,
            max_players=lobby.max_players,
        )
        message = await send_hybrid_response(
            ctx,
            embed=embed,
            view=view,
        )
        if message is not None:
            await lobby_manager.bind_lobby_message(ctx.guild.id if ctx.guild is not None else 0, message)

    @commands.hybrid_command(name="lobby_join", description="Join the active lobby")
    async def join_lobby(self, ctx: commands.Context) -> None:
        lobby_manager = getattr(self.bot, "lobby_manager", None)
        if lobby_manager is None:
            await send_hybrid_response(ctx, "Lobby system is not ready yet.", ephemeral=True)
            return
        try:
            await lobby_manager.join_lobby(
                guild_id=ctx.guild.id if ctx.guild is not None else 0,
                user_id=ctx.author.id,
            )
        except Exception as exc:  # pragma: no cover - UI feedback path
            await send_hybrid_response(ctx, str(exc), ephemeral=True)
            return
        await send_hybrid_response(ctx, "Joined the lobby.", ephemeral=True)

    @commands.hybrid_command(name="lobby_leave", description="Leave the active lobby")
    async def leave_lobby(self, ctx: commands.Context) -> None:
        lobby_manager = getattr(self.bot, "lobby_manager", None)
        if lobby_manager is None:
            await send_hybrid_response(ctx, "Lobby system is not ready yet.", ephemeral=True)
            return
        await lobby_manager.leave_lobby(guild_id=ctx.guild.id if ctx.guild is not None else 0, user_id=ctx.author.id)
        await send_hybrid_response(ctx, "Left the lobby.", ephemeral=True)

    @commands.hybrid_command(name="lobby_start", description="Start the game match")
    async def start_lobby(self, ctx: commands.Context) -> None:
        lobby_manager = getattr(self.bot, "lobby_manager", None)
        if lobby_manager is None:
            await send_hybrid_response(ctx, "Lobby system is not ready yet.", ephemeral=True)
            return
        try:
            member = ctx.author if isinstance(ctx.author, discord.Member) else None
            if member is None:
                await send_hybrid_response(ctx, "This command must be used in a server.", ephemeral=True)
                return
            await lobby_manager.start_lobby(ctx.guild.id if ctx.guild is not None else 0, member)
        except Exception as exc:  # pragma: no cover - UI feedback path
            await send_hybrid_response(ctx, str(exc), ephemeral=True)
            return
        await send_hybrid_response(ctx, "The game is beginning.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LobbyCog(bot))
