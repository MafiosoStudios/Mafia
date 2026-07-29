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

        from utils.progression import ProgressionManager
        from config import get_emoji
        import roles

        lvl_info = ProgressionManager.calculate_level_info(profile_record.xp)
        rank_info = ProgressionManager.get_rank_info(profile_record.xp)

        if profile_record.level != lvl_info.level or profile_record.rank != rank_info.get("name"):
            import dataclasses
            profile_record = dataclasses.replace(
                profile_record,
                level=lvl_info.level,
                rank=str(rank_info.get("name", "Bronze")),
            )
            await database.upsert_player_profile(profile_record)

        progress_bar_str = ProgressionManager.format_progress_bar(
            lvl_info.xp_in_level, lvl_info.xp_for_next, length=12
        )

        total_games = statistics.games_played
        win_rate = 0.0 if total_games == 0 else (statistics.wins / total_games) * 100

        rank_emoji = get_emoji(rank_info.get("emoji_key", "rank_bronze")) or "🥉"
        gold_emoji = get_emoji("gold") or "🪙"
        xp_emoji = get_emoji("xp") or "✨"
        level_emoji = get_emoji("level") or "📈"

        fav_char = profile_record.favorite_character
        fav_emoji_prefix = ""
        if fav_char:
            for rkey, rmeta in roles.ROLES_METADATA.items():
                rname = rmeta.get("name", "")
                if rname.lower() == fav_char.lower() or rkey.lower() == fav_char.lower():
                    char_emoji = get_emoji(rkey)
                    if char_emoji:
                        fav_emoji_prefix = char_emoji + " "
                    break

        fav_display = f"{fav_emoji_prefix}**{fav_char}**" if fav_char else "*None set (use `/setfavourite`)*"

        desc = (
            f"## {rank_emoji} {profile_record.rank} Tier\n"
            f"• **Rank Badge**: `{rank_info.get('badge', 'Tier')}`\n"
            f"• **Total XP**: {xp_emoji} `{profile_record.xp:,}` XP\n\n"
            f"### {level_emoji} Level Progression\n"
            f"• **Current Level**: `{lvl_info.level}`\n"
            f"• **Level Progress**: {progress_bar_str}\n"
            f"• **XP in Level**: `{lvl_info.xp_in_level:,}` / `{lvl_info.xp_for_next:,}` XP\n\n"
            f"### {gold_emoji} Inventory & Favorites\n"
            f"• **Gold Balance**: {gold_emoji} `{profile_record.coins:,}` Gold\n"
            f"• **Favorite Character**: {fav_display}\n\n"
            f"## 📊 Global Match Statistics\n"
            f"• **Wins**: `{statistics.wins}` 🏆 | **Losses**: `{statistics.losses}` 💀 | **Draws**: `{statistics.draws}` 🤝\n"
            f"• **Total Games**: `{total_games}` 🎮 | **Win Rate**: `{win_rate:.1f}%` 🔥"
        )

        from ui import build_v2_layout
        profile_view = build_v2_layout(
            title=f"👤 {profile_record.username}'s Player Profile",
            description=desc,
            color=discord.Color.from_str(rank_info.get("color", "#FFD700")),
            thumbnail_url=ctx.author.display_avatar.url,
            footer_text="Mafioso Progression & Career Stats",
        )
        await send_hybrid_response(ctx, view=profile_view)




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
