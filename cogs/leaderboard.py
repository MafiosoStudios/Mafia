from __future__ import annotations

import discord
from discord.ext import commands

from utils.embeds import build_victory_embed
from utils.helpers import send_hybrid_response


class LeaderboardCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.hybrid_group(name="leaderboard", description="View Mafioso leaderboards")
    async def leaderboard(self, ctx: commands.Context) -> None:
        if ctx.invoked_subcommand is None:
            await send_hybrid_response(ctx, "Try `leaderboard wins`.", ephemeral=True)

    @leaderboard.command(name="wins")
    async def wins_leaderboard(self, ctx: commands.Context) -> None:
        database = getattr(self.bot, "db", None)
        if database is None:
            await send_hybrid_response(ctx, "Leaderboard system is not ready yet.", ephemeral=True)
            return

        entries = await database.get_leaderboard("stats", "wins", limit=10)
        if not entries:
            await send_hybrid_response(ctx, "No leaderboard data yet.", ephemeral=True)
            return

        lines = [f"{entry.rank}. <@{entry.user_id}> - {entry.value} wins" for entry in entries]
        embed = build_victory_embed("Top Wins", "\n".join(lines))
        await send_hybrid_response(ctx, embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LeaderboardCog(bot))
