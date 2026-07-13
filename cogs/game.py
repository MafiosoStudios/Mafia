from __future__ import annotations

import discord
from discord.ext import commands

from views.vote_view import VoteView
from utils.constants import GameState
from utils.embeds import build_status_embed
from utils.helpers import send_hybrid_response


class GameCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.hybrid_group(name="game", description="Inspect and manage the current game")
    async def game(self, ctx: commands.Context) -> None:
        if ctx.invoked_subcommand is None:
            await send_hybrid_response(
                ctx,
                "Try `game status`, `game night`, or `game ability`.",
                ephemeral=True,
            )

    @game.command(name="status")
    async def status(self, ctx: commands.Context) -> None:
        game_manager = getattr(self.bot, "game_manager", None)
        game_engine = getattr(self.bot, "game_engine", None)
        if game_manager is None:
            await send_hybrid_response(ctx, "Game manager is not ready yet.", ephemeral=True)
            return
        active = await game_manager.get_game_by_guild(ctx.guild.id if ctx.guild is not None else 0)
        if active is None:
            await send_hybrid_response(ctx, "No active game in this server.", ephemeral=True)
            return
        session = await game_engine.get_session(active.game_id) if game_engine is not None else None
        if session is None:
            embed = build_status_embed(
                f"Game {active.game_id}",
                f"State: `{active.state}`\nUse the lobby controls to manage the match.",
            )
            await send_hybrid_response(ctx, embed=embed, view=VoteView(), ephemeral=True)
            return

        player_lines = [f"<@{user_id}>: {state.role_key or 'Unassigned'}" for user_id, state in session.players.items()]
        embed = build_status_embed(
            f"Game {active.game_id}",
            "\n".join(player_lines) if player_lines else "No players registered.",
        )
        if session.state == GameState.ENDED:
            embed.color = discord.Color.red()
        embed.add_field(name="State", value=str(session.state), inline=True)
        embed.add_field(name="Phase", value=str(session.phase), inline=True)
        embed.add_field(name="Players", value=str(len(session.players)), inline=True)
        await send_hybrid_response(ctx, embed=embed, view=VoteView(), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GameCog(bot))
