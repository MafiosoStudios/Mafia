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

        # Build leaderboard lines from entries
        lines = []
        for rank, entry in enumerate(entries, start=1):
            user_id = entry.get("user_id")
            wins = entry.get("wins", 0)
            if user_id:
                lines.append(f"{rank}. <@{user_id}>: **{wins}** wins")

        from ui import build_v2_layout
        from config import get_emoji

        leaderboard_layout = build_v2_layout(
            title=f"{get_emoji('victory')} Top Wins Leaderboard",
            description="\n".join(lines) if lines else "No data available yet.",
            footer_text="Keep playing to climb the ranks!"
        )
        await send_hybrid_response(ctx, view=leaderboard_layout)



async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LeaderboardCog(bot))
