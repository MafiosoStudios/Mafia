from __future__ import annotations

import discord
from discord.ext import commands

from utils.helpers import send_hybrid_response
from views.help_view import HelpView


class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _send_help(self, interaction_or_ctx: commands.Context | discord.Interaction) -> None:
        prefix = getattr(self.bot, "config", None).command_prefix if getattr(self.bot, "config", None) else "!"
        view = HelpView(prefix)
        embed = view.build_index_embed(prefix)

        if isinstance(interaction_or_ctx, commands.Context):
            await send_hybrid_response(interaction_or_ctx, embed=embed, view=view, ephemeral=True)
            return

        if interaction_or_ctx.response.is_done():
            await interaction_or_ctx.followup.send(embed=embed, view=view, ephemeral=True)
        else:
            await interaction_or_ctx.response.send_message(embed=embed, view=view, ephemeral=True)

    @commands.command(name="help", help="Show the anime mafia command guide")
    async def help_prefix(self, ctx: commands.Context) -> None:
        await self._send_help(ctx)

    @discord.app_commands.command(name="help", description="Show the anime mafia command guide")
    async def help_app(self, interaction: discord.Interaction) -> None:
        await self._send_help(interaction)

    @commands.hybrid_command(name="roleinfo", description="View detailed information about a specific role")
    @discord.app_commands.describe(character="Name of the character")
    async def roleinfo(self, ctx: commands.Context, character: str) -> None:
        await ctx.defer()
        import roles
        from config import get_emoji

        character_matched_key = None
        character_matched_meta = None
        
        input_cleaned = character.lower().strip().replace(" ", "_").replace("'", "").replace(".", "")
        for rkey, rmeta in roles.ROLES_METADATA.items():
            rname = rmeta.get("name", "").lower().strip().replace(" ", "_").replace("'", "").replace(".", "")
            if input_cleaned == rkey or input_cleaned == rname:
                character_matched_key = rkey
                character_matched_meta = rmeta
                break

        if character_matched_key is None:
            # Try partial matching
            for rkey, rmeta in roles.ROLES_METADATA.items():
                rname = rmeta.get("name", "").lower().strip()
                if input_cleaned in rkey or input_cleaned in rname.replace(" ", "_") or input_cleaned in rname:
                    character_matched_key = rkey
                    character_matched_meta = rmeta
                    break

        if character_matched_key is None:
            await send_hybrid_response(ctx, f"{get_emoji('cross')} **Role Not Found:** '{character}' could not be matched to any role.", ephemeral=True)
            return

        name = character_matched_meta.get("name", character_matched_key.replace("_", " ").title())
        faction = character_matched_meta.get("faction", "Unknown")
        win_condition = character_matched_meta.get("win_condition", "Unknown")
        description = character_matched_meta.get("description", "No description available.")
        active_ability = character_matched_meta.get("active_ability", "None")
        passive_ability = character_matched_meta.get("passive_ability", "None")

        # Color mapping based on faction
        color_map = {
            "Hero": discord.Color.green(),
            "Town": discord.Color.green(),
            "Protagonist": discord.Color.green(),
            "Villain": discord.Color.red(),
            "Mafia": discord.Color.red(),
            "Antagonist": discord.Color.red(),
            "Neutral": discord.Color.from_rgb(255, 255, 255)
        }
        embed_color = color_map.get(faction, discord.Color.purple())

        emoji = get_emoji(character_matched_key)
        emoji_prefix = f"{emoji} " if emoji else ""

        embed = discord.Embed(
            title=name,
            description=description,
            color=embed_color
        )
        from utils.helpers import get_emoji_url
        emoji_url = get_emoji_url(emoji) if emoji else None
        if emoji_url:
            embed.set_thumbnail(url=emoji_url)

        from config import ROLE_IMAGES
        big_image = ROLE_IMAGES.get(character_matched_key) or character_matched_meta.get("image_url")
        if big_image:
            embed.set_image(url=big_image)
        embed.add_field(name="Faction", value=faction, inline=True)
        embed.add_field(name="Win Condition", value=win_condition, inline=False)
        
        # Split active abilities
        if "Max Ability:" in active_ability:
            parts = active_ability.split("Max Ability:")
            abilities = [parts[0].strip(), "Max Ability: " + parts[1].strip()]
        elif "Max Ability. " in active_ability:
            parts = active_ability.split("Max Ability. ")
            abilities = [parts[0].strip(), "Max Ability: " + parts[1].strip()]
        else:
            abilities = [a.strip() for a in active_ability.split(" / ") if a.strip()]

        if not abilities or (len(abilities) == 1 and not abilities[0]):
            embed.add_field(name="Active Ability", value="None", inline=False)
        elif len(abilities) == 1:
            embed.add_field(name="Active Ability", value=abilities[0], inline=False)
        else:
            for idx, ability in enumerate(abilities, 1):
                embed.add_field(name=f"Active Ability {idx}", value=ability, inline=False)

        passive_val = passive_ability.strip()
        if passive_val and passive_val.lower() != "none":
            embed.add_field(name="Passive Ability", value=passive_val, inline=False)

        footer_text = character_matched_meta.get("footer", "")
        if footer_text:
            embed.set_footer(text=footer_text)

        await send_hybrid_response(ctx, embed=embed)

    @roleinfo.autocomplete("character")
    async def roleinfo_autocomplete(self, interaction: discord.Interaction, current: str) -> list[discord.app_commands.Choice[str]]:
        import roles
        choices = []
        for rkey, rmeta in roles.ROLES_METADATA.items():
            name = rmeta.get("name", rkey.replace("_", " ").title())
            if current.lower() in name.lower() or current.lower() in rkey.lower():
                choices.append(discord.app_commands.Choice(name=name, value=name))
        return choices[:25]


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HelpCog(bot))
