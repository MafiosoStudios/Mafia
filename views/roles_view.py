from __future__ import annotations

import discord
import roles
from config import get_emoji, get_role_image
from utils.helpers import get_emoji_url

# ---------------------------------------------------------------------------
# Faction constants
# ---------------------------------------------------------------------------
FACTION_PROTAGONIST = "Protagonist"
FACTION_ANTAGONIST  = "Antagonist"
FACTION_NEUTRAL     = "Neutral"
FACTION_SPECIAL     = "Special"

# All internal faction aliases that map to each group
_TOWN_ALIASES    = ("Hero", "Town", "Protagonist")
_MAFIA_ALIASES   = ("Villain", "Mafia", "Antagonist")
_NEUT_ALIASES    = ("Neutral",)
_SPECIAL_ALIASES = ("Special",)

# These role keys are never shown in the main faction tabs
SPECIAL_ROLE_KEYS = frozenset({"villager", "lower_moon", "upper_moon"})

FACTION_ORDER = [FACTION_PROTAGONIST, FACTION_ANTAGONIST, FACTION_NEUTRAL, FACTION_SPECIAL]

_FACTION_META = {
    FACTION_PROTAGONIST: {
        "label"       : "Protagonists",
        "emoji"       : "🦸",
        "color"       : discord.Color.from_rgb(52, 211, 153),   # emerald
        "aliases"     : _TOWN_ALIASES,
        "dropdown_ph" : "Select a Protagonist…",
        "style"       : discord.ButtonStyle.success,
    },
    FACTION_ANTAGONIST: {
        "label"       : "Antagonists",
        "emoji"       : "💀",
        "color"       : discord.Color.from_rgb(239, 68, 68),    # red
        "aliases"     : _MAFIA_ALIASES,
        "dropdown_ph" : "Select an Antagonist…",
        "style"       : discord.ButtonStyle.danger,
    },
    FACTION_NEUTRAL: {
        "label"       : "Neutrals",
        "emoji"       : "⚖️",
        "color"       : discord.Color.from_rgb(168, 85, 247),   # purple
        "aliases"     : _NEUT_ALIASES,
        "dropdown_ph" : "Select a Neutral…",
        "style"       : discord.ButtonStyle.secondary,
    },
    FACTION_SPECIAL: {
        "label"       : "Special",
        "emoji"       : "✨",
        "color"       : discord.Color.from_rgb(251, 191, 36),   # amber/gold
        "aliases"     : _SPECIAL_ALIASES,
        "dropdown_ph" : "Select a Special Role…",
        "style"       : discord.ButtonStyle.secondary,
    },
}

# Role embed colors (aliases → color)
_COLOR_MAP = {
    **{a: discord.Color.from_rgb(52, 211, 153)  for a in _TOWN_ALIASES},
    **{a: discord.Color.from_rgb(239, 68, 68)   for a in _MAFIA_ALIASES},
    **{a: discord.Color.from_rgb(168, 85, 247)  for a in _NEUT_ALIASES},
    **{a: discord.Color.from_rgb(251, 191, 36)  for a in _SPECIAL_ALIASES},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _canonical_faction(faction_str: str) -> str:
    if faction_str in _TOWN_ALIASES:
        return FACTION_PROTAGONIST
    if faction_str in _MAFIA_ALIASES:
        return FACTION_ANTAGONIST
    if faction_str in _SPECIAL_ALIASES:
        return FACTION_SPECIAL
    return FACTION_NEUTRAL


def _roles_for_faction(faction: str) -> list[tuple[str, dict]]:
    """Return sorted (key, meta) pairs for a canonical faction.
    Special faction = exactly the SPECIAL_ROLE_KEYS; all others exclude them.
    """
    meta_aliases = _FACTION_META[faction]["aliases"]
    result = []
    for rk, rm in roles.ROLES_METADATA.items():
        rf = rm.get("faction", "")
        if faction == FACTION_SPECIAL:
            # Only the three hand-picked special roles
            if rk in SPECIAL_ROLE_KEYS:
                result.append((rk, rm))
        else:
            # Exclude special roles from all main faction tabs
            if rk in SPECIAL_ROLE_KEYS:
                continue
            if rf in meta_aliases:
                result.append((rk, rm))

    return sorted(result, key=lambda x: x[1].get("name", x[0].replace("_", " ").title()))


def _build_faction_embed(faction: str) -> discord.Embed:
    meta  = _FACTION_META[faction]
    pairs = _roles_for_faction(faction)

    lines = []
    for rk, rm in pairs:
        name   = rm.get("name", rk.replace("_", " ").title())
        emoji  = get_emoji(rk)
        prefix = f"{emoji} " if emoji else ""
        lines.append(f"• {prefix}**{name}**")

    if faction == FACTION_SPECIAL:
        embed = discord.Embed(
            title=f"{meta['emoji']} Special Roles — Not Assigned at Game Start",
            description=(
                "These roles are **never distributed during the opening role assignment**. "
                "They enter the game through specific in-game mechanics:\n\n"
                + ("\n".join(lines) if lines else "None")
            ),
            color=meta["color"],
        )
    else:
        embed = discord.Embed(
            title=f"{meta['emoji']} {meta['label']} — {len(pairs)} Roles",
            description=(
                "\n".join(lines)
                if lines
                else "No roles in this faction yet."
            ),
            color=meta["color"],
        )

    embed.set_footer(text="Mafioso  •  Use the dropdown below to inspect any role")
    return embed


def _build_role_detail_embed(rkey: str, rmeta: dict) -> discord.Embed:
    name           = rmeta.get("name", rkey.replace("_", " ").title())
    faction        = rmeta.get("faction", "Unknown")
    win_condition  = rmeta.get("win_condition", "Unknown")
    description    = rmeta.get("description", "No description available.")
    active_ability = rmeta.get("active_ability", "None")
    passive_ability= rmeta.get("passive_ability", "None")

    embed = discord.Embed(
        title       = name,
        description = description,
        color       = _COLOR_MAP.get(faction, discord.Color.purple()),
    )

    emoji     = get_emoji(rkey)
    emoji_url = get_emoji_url(emoji) if emoji else None
    if emoji_url:
        embed.set_thumbnail(url=emoji_url)

    from config import ROLE_IMAGES
    big_image = ROLE_IMAGES.get(rkey) or rmeta.get("image_url")
    if big_image:
        embed.set_image(url=big_image)

    embed.add_field(name="Faction",       value=faction,      inline=True)
    embed.add_field(name="Win Condition", value=win_condition, inline=False)

    # Split multiple active abilities
    if "Max Ability:" in active_ability:
        parts     = active_ability.split("Max Ability:")
        abilities = [parts[0].strip(), "Max Ability: " + parts[1].strip()]
    elif "Max Ability. " in active_ability:
        parts     = active_ability.split("Max Ability. ")
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
    embed.set_footer(text=footer_text if footer_text else "Mafioso")
    return embed


# ---------------------------------------------------------------------------
# Dropdown — shows roles for the active faction
# ---------------------------------------------------------------------------

class RoleSelectDropdown(discord.ui.Select):
    def __init__(self, active_faction: str) -> None:
        self.active_faction = active_faction
        meta  = _FACTION_META[active_faction]
        pairs = _roles_for_faction(active_faction)

        options = []
        for rk, rm in pairs:
            name  = rm.get("name", rk.replace("_", " ").title())
            emoji = get_emoji(rk)
            sel_emoji = None
            if emoji:
                if emoji.startswith("<"):
                    try:
                        sel_emoji = discord.PartialEmoji.from_str(emoji)
                    except Exception:
                        pass
                else:
                    sel_emoji = emoji

            desc = rm.get("description", "")[:100]
            options.append(
                discord.SelectOption(
                    label       = name[:100],
                    value       = rk,
                    description = desc,
                    emoji       = sel_emoji,
                )
            )

        super().__init__(
            placeholder = meta["dropdown_ph"],
            min_values  = 1,
            max_values  = 1,
            options     = options,
            custom_id   = f"role_select_{active_faction}",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        rkey  = self.values[0]
        rmeta = roles.ROLES_METADATA.get(rkey)
        if not rmeta:
            await interaction.response.send_message("Role not found.", ephemeral=True)
            return

        embed    = _build_role_detail_embed(rkey, rmeta)
        new_view = RolesView(active_faction=self.active_faction, detail_mode=True)
        await interaction.response.edit_message(embed=embed, view=new_view)


# ---------------------------------------------------------------------------
# Faction tab buttons
# ---------------------------------------------------------------------------

class FactionButton(discord.ui.Button):
    def __init__(self, faction: str, active_faction: str) -> None:
        meta      = _FACTION_META[faction]
        is_active = (faction == active_faction)
        super().__init__(
            label     = meta["label"],
            emoji     = meta["emoji"],
            style     = meta["style"] if is_active else discord.ButtonStyle.secondary,
            custom_id = f"faction_tab_{faction}",
            disabled  = is_active,
            row       = 1,
        )
        self.faction = faction

    async def callback(self, interaction: discord.Interaction) -> None:
        new_view = RolesView(active_faction=self.faction)
        embed    = _build_faction_embed(self.faction)
        await interaction.response.edit_message(embed=embed, view=new_view)


class BackToRosterButton(discord.ui.Button):
    def __init__(self, active_faction: str) -> None:
        super().__init__(
            label     = "← Back to Roster",
            style     = discord.ButtonStyle.secondary,
            custom_id = "back_to_roster",
            row       = 1,
        )
        self.active_faction = active_faction

    async def callback(self, interaction: discord.Interaction) -> None:
        new_view = RolesView(active_faction=self.active_faction)
        embed    = _build_faction_embed(self.active_faction)
        await interaction.response.edit_message(embed=embed, view=new_view)


# ---------------------------------------------------------------------------
# Main view
# ---------------------------------------------------------------------------

class RolesView(discord.ui.View):
    def __init__(self, active_faction: str = FACTION_PROTAGONIST, detail_mode: bool = False) -> None:
        super().__init__(timeout=300)
        self.active_faction = active_faction

        # Row 0 — dropdown for the active faction's roles
        self.add_item(RoleSelectDropdown(active_faction))

        # Row 1 — faction tab buttons (or Back + inactive faction tabs in detail mode)
        if detail_mode:
            self.add_item(BackToRosterButton(active_faction))
            for faction in FACTION_ORDER:
                if faction != active_faction:
                    self.add_item(FactionButton(faction, active_faction))
        else:
            for faction in FACTION_ORDER:
                self.add_item(FactionButton(faction, active_faction))

    @staticmethod
    def build_index_embed(faction: str = FACTION_PROTAGONIST) -> discord.Embed:
        return _build_faction_embed(faction)
