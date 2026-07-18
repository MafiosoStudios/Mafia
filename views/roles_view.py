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

# All internal faction aliases that map to each group
_TOWN_ALIASES   = ("Hero", "Town", "Protagonist")
_MAFIA_ALIASES  = ("Villain", "Mafia", "Antagonist")
_NEUT_ALIASES   = ("Neutral",)

FACTION_ORDER = [FACTION_PROTAGONIST, FACTION_ANTAGONIST, FACTION_NEUTRAL]

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
}

# Role embed colors
_COLOR_MAP = {
    **{a: discord.Color.from_rgb(52, 211, 153)  for a in _TOWN_ALIASES},
    **{a: discord.Color.from_rgb(239, 68, 68)   for a in _MAFIA_ALIASES},
    **{a: discord.Color.from_rgb(168, 85, 247)  for a in _NEUT_ALIASES},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _canonical_faction(faction_str: str) -> str:
    """Map any faction alias to one of the 3 canonical keys."""
    if faction_str in _TOWN_ALIASES:
        return FACTION_PROTAGONIST
    if faction_str in _MAFIA_ALIASES:
        return FACTION_ANTAGONIST
    return FACTION_NEUTRAL


def _roles_for_faction(faction: str) -> list[tuple[str, dict]]:
    """Return sorted (key, meta) pairs for a canonical faction."""
    aliases = _FACTION_META[faction]["aliases"]
    result = [
        (rk, rm)
        for rk, rm in roles.ROLES_METADATA.items()
        if rm.get("faction", "") in aliases
    ]
    return sorted(result, key=lambda x: x[1].get("name", x[0].replace("_", " ").title()))


def _build_faction_embed(faction: str) -> discord.Embed:
    """Build the roster embed for a given faction."""
    meta  = _FACTION_META[faction]
    pairs = _roles_for_faction(faction)

    lines = []
    for rk, rm in pairs:
        name    = rm.get("name", rk.replace("_", " ").title())
        emoji   = get_emoji(rk)
        prefix  = f"{emoji} " if emoji else ""
        wc      = rm.get("win_condition", "")
        lines.append(f"{prefix}**{name}**\n> {wc}")

    embed = discord.Embed(
        title       = f"{meta['emoji']} {meta['label']} — {len(pairs)} Roles",
        description = (
            "\n\n".join(lines)
            if lines
            else "No roles in this faction yet."
        ),
        color       = meta["color"],
    )
    embed.set_footer(text=f"Mafioso  •  Use the dropdown below to inspect any role")
    return embed


def _build_role_detail_embed(rkey: str, rmeta: dict) -> discord.Embed:
    """Build the detailed embed for a single role."""
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

    embed.add_field(name="Faction",       value=faction,       inline=True)
    embed.add_field(name="Win Condition", value=win_condition,  inline=False)

    # Split multiple active abilities (slash-separated or "Max Ability:" divider)
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
# Dropdown — shows roles for the currently active faction
# ---------------------------------------------------------------------------

class RoleSelectDropdown(discord.ui.Select):
    def __init__(self, active_faction: str) -> None:
        self.active_faction = active_faction
        meta    = _FACTION_META[active_faction]
        pairs   = _roles_for_faction(active_faction)

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
        meta    = _FACTION_META[faction]
        is_active = (faction == active_faction)
        super().__init__(
            label      = meta["label"],
            emoji      = meta["emoji"],
            style      = meta["style"] if is_active else discord.ButtonStyle.secondary,
            custom_id  = f"faction_tab_{faction}",
            disabled   = is_active,            # highlight the current tab
            row        = 1,
        )
        self.faction = faction

    async def callback(self, interaction: discord.Interaction) -> None:
        new_view  = RolesView(active_faction=self.faction)
        embed     = _build_faction_embed(self.faction)
        await interaction.response.edit_message(embed=embed, view=new_view)


class BackToRosterButton(discord.ui.Button):
    """Appears in detail mode — returns to the faction roster list."""
    def __init__(self, active_faction: str) -> None:
        super().__init__(
            label      = "← Back to Roster",
            style      = discord.ButtonStyle.secondary,
            custom_id  = "back_to_roster",
            row        = 1,
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

        # Row 1 — faction tab buttons (or Back button in detail mode)
        if detail_mode:
            self.add_item(BackToRosterButton(active_faction))
            # Still show the inactive faction buttons so the user can jump directly
            for faction in FACTION_ORDER:
                if faction != active_faction:
                    btn = FactionButton(faction, active_faction)
                    self.add_item(btn)
        else:
            for faction in FACTION_ORDER:
                self.add_item(FactionButton(faction, active_faction))

    # Convenience static used by the command
    @staticmethod
    def build_index_embed(faction: str = FACTION_PROTAGONIST) -> discord.Embed:
        return _build_faction_embed(faction)
