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
        view = HelpView.build_index_layout(prefix)

        if isinstance(interaction_or_ctx, commands.Context):
            await send_hybrid_response(interaction_or_ctx, view=view, ephemeral=True)
            return

        if interaction_or_ctx.response.is_done():
            await interaction_or_ctx.followup.send(view=view, ephemeral=True)
        else:
            await interaction_or_ctx.response.send_message(view=view, ephemeral=True)

    @commands.command(name="help", help="Show the Mafioso command guide")
    async def help_prefix(self, ctx: commands.Context) -> None:
        await self._send_help(ctx)

    @discord.app_commands.command(name="help", description="Show the Mafioso command guide")
    async def help_app(self, interaction: discord.Interaction) -> None:
        await self._send_help(interaction)

    @commands.hybrid_command(name="roleinfo", description="View detailed information about a specific role")
    @discord.app_commands.describe(character="Name of the character")
    async def roleinfo(self, ctx: commands.Context, character: str) -> None:
        await ctx.defer()
        import roles
        from config import get_emoji
        from ui import build_v2_layout
        from utils.helpers import get_emoji_url

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
        emoji_url = get_emoji_url(emoji) if emoji else None

        from config import ROLE_IMAGES
        big_image = ROLE_IMAGES.get(character_matched_key) or character_matched_meta.get("image_url")

        desc_parts = [description]
        desc_parts.append(f"• **Faction:** **{faction}**")
        desc_parts.append(f"• **Win Condition:** {win_condition}")

        if "Max Ability:" in active_ability:
            parts = active_ability.split("Max Ability:")
            abilities = [parts[0].strip(), "Max Ability: " + parts[1].strip()]
        elif "Max Ability. " in active_ability:
            parts = active_ability.split("Max Ability. ")
            abilities = [parts[0].strip(), "Max Ability: " + parts[1].strip()]
        else:
            abilities = [a.strip() for a in active_ability.split(" / ") if a.strip()]

        if not abilities or (len(abilities) == 1 and not abilities[0]):
            desc_parts.append("• **Active Ability:** None")
        elif len(abilities) == 1:
            desc_parts.append(f"• **Active Ability:** {abilities[0]}")
        else:
            for idx, ability in enumerate(abilities, 1):
                desc_parts.append(f"• **Active Ability {idx}:** {ability}")

        passive_val = passive_ability.strip()
        if passive_val and passive_val.lower() != "none":
            desc_parts.append(f"• **Passive Ability:** {passive_val}")

        footer_text = character_matched_meta.get("footer", "")

        role_layout = build_v2_layout(
            title=name,
            description="\n\n".join(desc_parts),
            color=embed_color,
            thumbnail_url=emoji_url,
            image_url=big_image,
            footer_text=footer_text,
        )

        await send_hybrid_response(ctx, view=role_layout)


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
