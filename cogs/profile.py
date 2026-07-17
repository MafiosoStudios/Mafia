from __future__ import annotations

import discord
from discord.ext import commands

from database.models import PlayerProfileRecord, StatisticsRecord
from utils.embeds import build_profile_embed
from utils.helpers import send_hybrid_response, utcnow


class ProfileCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.hybrid_command(name="profile", description="View your Mafioso profile")
    async def profile(self, ctx: commands.Context) -> None:
        database = getattr(self.bot, "db", None)
        if database is None:
            await send_hybrid_response(ctx, "Profile system is not ready yet.", ephemeral=True)
            return

        profile_record = await database.get_player_profile(ctx.author.id)
        if profile_record is None:
            profile_record = PlayerProfileRecord(
                user_id=ctx.author.id,
                username=ctx.author.display_name,
                discriminator=getattr(ctx.author, "discriminator", "0000"),
            )
            await database.upsert_player_profile(profile_record)

        statistics = await database.get_statistics(ctx.author.id)
        if statistics is None:
            statistics = StatisticsRecord(user_id=ctx.author.id)
            await database.upsert_statistics(statistics)

        total_games = statistics.games_played
        win_rate = 0.0 if total_games == 0 else (statistics.wins / total_games) * 100
        embed = build_profile_embed(f"{profile_record.username}'s Profile")
        embed.set_thumbnail(url=ctx.author.display_avatar.url)
        embed.remove_footer()

        # Row 1: Rank alone
        embed.add_field(name="Rank", value=profile_record.rank, inline=False)

        # Row 2: Level and XP
        embed.add_field(name="Level", value=str(profile_record.level), inline=True)
        embed.add_field(name="XP", value=str(profile_record.xp), inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)

        # Row 3: Wins and Losses
        embed.add_field(name="Wins", value=str(statistics.wins), inline=True)
        embed.add_field(name="Losses", value=str(statistics.losses), inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)

        # Row 4: Games Played and Win Rate
        embed.add_field(name="Games Played", value=str(total_games), inline=True)
        embed.add_field(name="Win Rate", value=f"{win_rate:.1f}%", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)

        # Row 5: Gold
        embed.add_field(name="Gold", value=str(profile_record.coins), inline=False)

        # Row 6: Favorite Character
        embed.add_field(name="Favorite Character", value=profile_record.favorite_character or "None yet", inline=False)
        await send_hybrid_response(ctx, embed=embed)

    @commands.hybrid_command(name="setfavourite", description="Set your favorite anime character on your profile")
    @discord.app_commands.describe(character="Name of the character")
    async def setfavourite(self, ctx: commands.Context, character: str) -> None:
        database = getattr(self.bot, "db", None)
        if database is None:
            await send_hybrid_response(ctx, "Profile system is not ready yet.", ephemeral=True)
            return

        import roles
        character_matched = None
        input_cleaned = character.lower().strip().replace(" ", "_").replace("'", "").replace(".", "")
        for rkey, rmeta in roles.ROLES_METADATA.items():
            rname = rmeta.get("name", "").lower().strip().replace(" ", "_").replace("'", "").replace(".", "")
            if input_cleaned == rkey or input_cleaned == rname:
                character_matched = rmeta.get("name", rkey.replace("_", " ").title())
                break

        from config import get_emoji
        if character_matched is None:
            await send_hybrid_response(ctx, f"{get_emoji('cross')} **Invalid Character:** '{character}' is not a valid character in Mafioso.", ephemeral=True)
            return

        profile_record = await database.get_player_profile(ctx.author.id)
        if profile_record is None:
            profile_record = PlayerProfileRecord(
                user_id=ctx.author.id,
                username=ctx.author.display_name,
                discriminator=getattr(ctx.author, "discriminator", "0000"),
                favorite_character=character_matched
            )
        else:
            import dataclasses
            profile_record = dataclasses.replace(profile_record, favorite_character=character_matched)
        
        await database.upsert_player_profile(profile_record)
        await send_hybrid_response(ctx, f"{get_emoji('check')} Your favorite character has been set to **{character_matched}**!", ephemeral=True)

    @setfavourite.autocomplete("character")
    async def character_autocomplete(self, interaction: discord.Interaction, current: str) -> list[discord.app_commands.Choice[str]]:
        import roles
        choices = []
        for rkey, rmeta in roles.ROLES_METADATA.items():
            name = rmeta.get("name", rkey.replace("_", " ").title())
            if current.lower() in name.lower() or current.lower() in rkey.lower():
                choices.append(discord.app_commands.Choice(name=name, value=name))
        return choices[:25]


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ProfileCog(bot))
