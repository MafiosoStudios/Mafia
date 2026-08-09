from __future__ import annotations

import discord
from discord.ext import commands

from config import get_emoji, get_role_image
from database.models import PlayerProfileRecord, StatisticsRecord
from ui.theme import small_footer
from utils.embeds import build_profile_embed
from utils.helpers import send_hybrid_response, utcnow


class ProfileCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.hybrid_command(name="profile", description="View your Mafioso profile")
    @commands.cooldown(1, 1.5, commands.BucketType.user)
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

        progress_bar_str = ProgressionManager.format_progress_bar(lvl_info.xp_in_level, lvl_info.xp_for_next)

        total_games = statistics.games_played
        win_rate = 0.0 if total_games == 0 else (statistics.wins / total_games) * 100

        rank_emoji = get_emoji(rank_info.get("emoji_key", "rank_bronze")) or ""
        level_emoji = get_emoji("level") or "📈"
        gold_emoji = get_emoji("gold") or "🪙"
        xp_emoji = get_emoji("xp") or "✨"
        wins_emoji = get_emoji("sword") or "⚔️"
        losses_emoji = get_emoji("skull") or "☠️"
        draws_emoji = get_emoji("peace") or "🤝"
        crown_emoji = get_emoji("crown") or "👑"

        # Favorite character visuals
        fav_role_key = profile_record.favorite_character or ""
        fav_emoji = get_emoji(fav_role_key) if fav_role_key else ""
        fav_image = get_role_image(fav_role_key) if fav_role_key else None
        fav_line = (
            f"{fav_emoji} **{fav_role_key.replace('_', ' ').title()}**"
            if fav_role_key else "*None set — use `/setfavourite`*"
        )

        # Combat record
        combat_lines = (
            f"{wins_emoji} Wins: `{statistics.wins}`"
            f"  |  {losses_emoji} Losses: `{statistics.losses}`\n"
            f"{draws_emoji} Draws: `{statistics.draws}`"
            f"  |  🎮 Games: `{total_games}`\n"
            f"📊 Win Rate: **`{win_rate:.1f}%`**"
        )

        # Progression card
        progression_lines = (
            f"{crown_emoji} Rank: **{rank_emoji} `{profile_record.rank}`**"
            f"  |  {level_emoji} Level: **`{lvl_info.level}`**\n"
            f"{xp_emoji} {progress_bar_str}\n"
            f"{gold_emoji} Gold: **`{profile_record.coins:,}`**"
        )

        desc = (
            f"{crown_emoji} **{profile_record.username}'s Dossier**\n\n"
            f"## ⚔️ Combat Record\n{combat_lines}\n\n"
            f"## 📈 Progression\n{progression_lines}\n\n"
            f"## 🎭 Favorite Character\n{fav_line}"
        )

        from ui import build_v2_layout
        profile_view = build_v2_layout(
            title=f"{rank_emoji} {profile_record.username}",
            description=desc,
            color=discord.Color.from_str(rank_info.get("color", "#FFD700")),
            thumbnail_url=ctx.author.display_avatar.url,
            image_url=fav_image,
            footer_text=small_footer("Mafioso Dossier — every match is a step toward the throne."),
        )
        await send_hybrid_response(ctx, view=profile_view)





    @commands.hybrid_command(name="setfavourite", description="Set your favorite anime character on your profile")
    @commands.cooldown(1, 1.5, commands.BucketType.user)
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
