from __future__ import annotations

import discord
import roles
from config import get_emoji, get_role_image
from utils.helpers import get_emoji_url


class RoleDropdown(discord.ui.Select):
    def __init__(self, view_ref: RolesView, faction_group: str) -> None:
        self.view_ref = view_ref
        self.faction_group = faction_group
        options = []
        
        # Sort roles by name
        sorted_roles = sorted(
            [(rk, rm) for rk, rm in roles.ROLES_METADATA.items()],
            key=lambda x: x[1].get("name", x[0].replace("_", " ").title())
        )
        
        for rkey, rmeta in sorted_roles:
            faction = rmeta.get("faction", "Unknown")
            is_town = faction in ("Hero", "Town", "Protagonist")
            
            if faction_group == "town" and not is_town:
                continue
            if faction_group == "mafia_neutral" and is_town:
                continue
                
            name = rmeta.get("name", rkey.replace("_", " ").title())
            emoji = get_emoji(rkey)
            select_emoji = None
            if emoji:
                if emoji.startswith("<"):
                    try:
                        select_emoji = discord.PartialEmoji.from_str(emoji)
                    except Exception:
                        pass
                else:
                    select_emoji = emoji
                    
            desc = rmeta.get("description", "")[:100]
            options.append(
                discord.SelectOption(
                    label=name,
                    value=rkey,
                    description=desc,
                    emoji=select_emoji
                )
            )
            
        placeholder = "Select a Town Character..." if faction_group == "town" else "Select a Mafia / Neutral Character..."
        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        rkey = self.values[0]
        rmeta = roles.ROLES_METADATA.get(rkey)
        if not rmeta:
            await interaction.response.send_message("Role meta not found.", ephemeral=True)
            return

        name = rmeta.get("name", rkey.replace("_", " ").title())
        faction = rmeta.get("faction", "Unknown")
        win_condition = rmeta.get("win_condition", "Unknown")
        description = rmeta.get("description", "No description available.")
        active_ability = rmeta.get("active_ability", "None")
        passive_ability = rmeta.get("passive_ability", "None")

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

        embed = discord.Embed(
            title=name,
            description=description,
            color=embed_color
        )
        
        from config import get_emoji
        emoji = get_emoji(rkey)
        emoji_url = get_emoji_url(emoji) if emoji else None
        if emoji_url:
            embed.set_thumbnail(url=emoji_url)

        from config import ROLE_IMAGES
        big_image = ROLE_IMAGES.get(rkey) or rmeta.get("image_url")
        if big_image:
            embed.set_image(url=big_image)
            
        embed.add_field(name="Faction", value=faction, inline=True)
        embed.add_field(name="Win Condition", value=win_condition, inline=False)
        
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

        footer_text = rmeta.get("footer", "")
        if footer_text:
            embed.set_footer(text=footer_text)

        new_view = discord.ui.View(timeout=180)
        new_view.add_item(RoleDropdown(self.view_ref, "town"))
        new_view.add_item(RoleDropdown(self.view_ref, "mafia_neutral"))
        new_view.add_item(BackButton(self.view_ref))
        
        await interaction.response.edit_message(embed=embed, view=new_view)


class BackButton(discord.ui.Button):
    def __init__(self, view_ref: RolesView) -> None:
        super().__init__(
            label="Back to Roster",
            style=discord.ButtonStyle.secondary,
            emoji="◀️"
        )
        self.view_ref = view_ref

    async def callback(self, interaction: discord.Interaction) -> None:
        embed = self.view_ref.build_index_embed()
        new_view = discord.ui.View(timeout=180)
        new_view.add_item(RoleDropdown(self.view_ref, "town"))
        new_view.add_item(RoleDropdown(self.view_ref, "mafia_neutral"))
        await interaction.response.edit_message(embed=embed, view=new_view)


class RolesView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=180)
        self.add_item(RoleDropdown(self, "town"))
        self.add_item(RoleDropdown(self, "mafia_neutral"))

    @staticmethod
    def build_index_embed() -> discord.Embed:
        town_roles = []
        mafia_roles = []
        neutral_roles = []

        for rkey, rmeta in roles.ROLES_METADATA.items():
            name = rmeta.get("name", rkey.replace("_", " ").title())
            faction = rmeta.get("faction", "Unknown")
            emoji = get_emoji(rkey)
            emoji_str = f"{emoji} " if emoji else ""
            line = f"{emoji_str}**{name}**"

            if faction in ("Hero", "Town", "Protagonist"):
                town_roles.append(line)
            elif faction in ("Villain", "Mafia", "Antagonist"):
                mafia_roles.append(line)
            else:
                neutral_roles.append(line)

        embed = discord.Embed(
            title="🎭 The AniMafia Roster",
            description="Select any character from the dropdown menus below to view their active/passive abilities, win conditions, and strategic role mechanics.",
            color=discord.Color.dark_purple()
        )
        
        embed.add_field(
            name=f"🛡️ Protagonists (Town) — {len(town_roles)}",
            value="\n".join(town_roles) if town_roles else "None",
            inline=True
        )
        embed.add_field(
            name=f"🔪 Antagonists (Mafia) — {len(mafia_roles)}",
            value="\n".join(mafia_roles) if mafia_roles else "None",
            inline=True
        )
        embed.add_field(
            name=f"🃏 Neutrals — {len(neutral_roles)}",
            value="\n".join(neutral_roles) if neutral_roles else "None",
            inline=False
        )
        return embed
