from __future__ import annotations

import discord
from discord.ext import commands

from database.models import PlayerProfileRecord, StatisticsRecord
from utils.embeds import build_profile_embed
from utils.helpers import send_hybrid_response, utcnow


class ProfileCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.hybrid_command(name="profile", description="View your anime mafia profile")
    async def profile(self, ctx: commands.Context) -> None:
        if ctx.guild is None:
            await send_hybrid_response(ctx, "This command must be used in a server.", ephemeral=True)
            return

        database = getattr(self.bot, "db", None)
        if database is None:
            await send_hybrid_response(ctx, "Profile system is not ready yet.", ephemeral=True)
            return

        profile_record = await database.get_player_profile(ctx.author.id, ctx.guild.id)
        if profile_record is None:
            profile_record = PlayerProfileRecord(
                user_id=ctx.author.id,
                guild_id=ctx.guild.id,
                username=ctx.author.display_name,
                discriminator=getattr(ctx.author, "discriminator", "0000"),
            )
            await database.upsert_player_profile(profile_record)

        statistics = await database.get_statistics(ctx.author.id, ctx.guild.id)
        if statistics is None:
            statistics = StatisticsRecord(user_id=ctx.author.id, guild_id=ctx.guild.id)
            await database.upsert_statistics(statistics)

        total_games = statistics.games_played
        win_rate = 0.0 if total_games == 0 else (statistics.wins / total_games) * 100
        embed = build_profile_embed(f"{profile_record.username}'s Profile")
        embed.add_field(name="Rank", value=profile_record.rank, inline=True)
        embed.add_field(name="Level", value=str(profile_record.level), inline=True)
        embed.add_field(name="XP", value=str(profile_record.xp), inline=True)
        embed.add_field(name="Wins", value=str(statistics.wins), inline=True)
        embed.add_field(name="Losses", value=str(statistics.losses), inline=True)
        embed.add_field(name="Win Rate", value=f"{win_rate:.1f}%", inline=True)
        embed.add_field(name="Coins", value=str(profile_record.coins), inline=True)
        embed.add_field(name="Games Played", value=str(total_games), inline=True)
        embed.add_field(name="Favorite Character", value=profile_record.favorite_character or "None yet", inline=True)
        embed.set_footer(text=f"Updated {utcnow().isoformat()}")
        await send_hybrid_response(ctx, embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ProfileCog(bot))
