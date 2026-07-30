from __future__ import annotations

import discord
from discord import ui
import roles
from config import get_emoji, get_role_image
from utils.helpers import get_emoji_url
from ui.base import MafiosoLayoutView
from ui.theme import (
    COLOR_TOWN,
    COLOR_MAFIA,
    COLOR_NEUTRAL,
    COLOR_SYSTEM,
    heading,
    subheading,
    small_footer,
    bold,
)

# ---------------------------------------------------------------------------
# Faction constants
# ---------------------------------------------------------------------------
FACTION_PROTAGONIST = "Protagonist"
FACTION_ANTAGONIST  = "Antagonist"
FACTION_NEUTRAL     = "Neutral"
FACTION_SPECIAL     = "Special"

_TOWN_ALIASES    = ("Hero", "Town", "Protagonist")
_MAFIA_ALIASES   = ("Villain", "Mafia", "Antagonist")
_NEUT_ALIASES    = ("Neutral",)
_SPECIAL_ALIASES = ("Special",)

SPECIAL_ROLE_KEYS = frozenset({"villager", "demon", "lower_moon", "upper_moon"})
FACTION_ORDER = [FACTION_PROTAGONIST, FACTION_ANTAGONIST, FACTION_NEUTRAL, FACTION_SPECIAL]

_FACTION_META = {
    FACTION_PROTAGONIST: {
        "label"       : "Protagonists",
        "emoji"       : get_emoji("Protagonist") or "🦸",
        "color"       : COLOR_TOWN,
        "aliases"     : _TOWN_ALIASES,
        "dropdown_ph" : "Select a Protagonist…",
        "style"       : discord.ButtonStyle.success,
    },
    FACTION_ANTAGONIST: {
        "label"       : "Antagonists",
        "emoji"       : get_emoji("skull"),
        "color"       : COLOR_MAFIA,
        "aliases"     : _MAFIA_ALIASES,
        "dropdown_ph" : "Select an Antagonist…",
        "style"       : discord.ButtonStyle.danger,
    },
    FACTION_NEUTRAL: {
        "label"       : "Neutrals",
        "emoji"       : get_emoji("Neutral") or "⚖️",
        "color"       : COLOR_NEUTRAL,
        "aliases"     : _NEUT_ALIASES,
        "dropdown_ph" : "Select a Neutral…",
        "style"       : discord.ButtonStyle.secondary,
    },
    FACTION_SPECIAL: {
        "label"       : "Special",
        "emoji"       : "✨",
        "color"       : COLOR_SYSTEM,
        "aliases"     : _SPECIAL_ALIASES,
        "dropdown_ph" : "Select a Special Role…",
        "style"       : discord.ButtonStyle.secondary,
    },
}

_COLOR_MAP = {
    **{a: COLOR_TOWN  for a in _TOWN_ALIASES},
    **{a: COLOR_MAFIA   for a in _MAFIA_ALIASES},
    **{a: COLOR_NEUTRAL  for a in _NEUT_ALIASES},
    **{a: COLOR_SYSTEM  for a in _SPECIAL_ALIASES},
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
    meta_aliases = _FACTION_META[faction]["aliases"]
    result = []
    for rk, rm in roles.ROLES_METADATA.items():
        rf = rm.get("faction", "")
        if faction == FACTION_SPECIAL:
            if rk in SPECIAL_ROLE_KEYS:
                result.append((rk, rm))
        else:
            if rk in SPECIAL_ROLE_KEYS:
                continue
            if rf in meta_aliases:
                result.append((rk, rm))

    return sorted(result, key=lambda x: x[1].get("name", x[0].replace("_", " ").title()))


def _build_faction_card(faction: str) -> ui.Container:
    meta  = _FACTION_META[faction]
    pairs = _roles_for_faction(faction)

    lines = []
    for rk, rm in pairs:
        name   = rm.get("name", rk.replace("_", " ").title())
        emoji  = get_emoji(rk)
        prefix = f"{emoji} " if emoji else ""
        lines.append(f"• {prefix}{name}")

    container = ui.Container(accent_color=meta["color"])

    emoji_str = meta["emoji"]
    label_str = meta["label"]

    if faction == FACTION_SPECIAL:
        header_text = (
            f"{heading(f'{emoji_str} Special Roles — Not Assigned at Game Start')}\n"
            "These roles are **never distributed during opening role assignment**. "
            "They enter the game through specific in-game mechanics:\n\n"
            + ("\n".join(lines) if lines else "None")
        )
    else:
        header_text = (
            f"{heading(f'{emoji_str} {label_str} — {len(pairs)} Roles')}\n\n"
            + ("\n".join(lines) if lines else "No roles in this faction yet.")
        )


    container.add_item(ui.TextDisplay(header_text))
    return container


def _build_role_detail_card(rkey: str, rmeta: dict) -> ui.Container:
    name            = rmeta.get("name", rkey.replace("_", " ").title())
    faction         = rmeta.get("faction", "Unknown")
    win_condition   = rmeta.get("win_condition", "Unknown")
    description     = rmeta.get("description", "No description available.")
    active_ability  = rmeta.get("active_ability", "None")
    passive_ability = rmeta.get("passive_ability", "None")
    color           = _COLOR_MAP.get(faction, COLOR_SYSTEM)

    container = ui.Container(accent_color=color)

    header_text = f"{heading(name)}\n{description}"
    header_display = ui.TextDisplay(header_text)

    emoji = get_emoji(rkey)
    emoji_url = get_emoji_url(emoji) if emoji else None
    if emoji_url:
        container.add_item(ui.Section(header_display, accessory=ui.Thumbnail(emoji_url)))
    else:
        container.add_item(header_display)


    from config import ROLE_IMAGES
    big_image = ROLE_IMAGES.get(rkey) or rmeta.get("image_url")
    if big_image:
        container.add_item(ui.MediaGallery(discord.MediaGalleryItem(big_image)))

    container.add_item(ui.Separator())

    # Formatted details body
    details_md = (
        f"{subheading('Character Overview')}\n"
        f"• {bold('Faction')}: {faction}\n"
        f"• {bold('Win Condition')}: {win_condition}\n\n"
    )

    # Split multiple active abilities
    if "Max Ability:" in active_ability:
        parts     = active_ability.split("Max Ability:")
        abilities = [parts[0].strip(), "Max Ability: " + parts[1].strip()]
    elif "Max Ability. " in active_ability:
        parts     = active_ability.split("Max Ability. ")
        abilities = [parts[0].strip(), "Max Ability: " + parts[1].strip()]
    else:
        abilities = [a.strip() for a in active_ability.split(" / ") if a.strip()]

    details_md += f"{subheading('Abilities')}\n"
    if not abilities or (len(abilities) == 1 and not abilities[0]):
        details_md += f"• {bold('Active Ability')}: None\n"
    elif len(abilities) == 1:
        details_md += f"• {bold('Active Ability')}: {abilities[0]}\n"
    else:
        for idx, ability in enumerate(abilities, 1):
            details_md += f"• {bold(f'Active Ability {idx}')}: {ability}\n"

    passive_val = passive_ability.strip()
    if passive_val and passive_val.lower() != "none":
        details_md += f"• {bold('Passive Ability')}: {passive_val}\n"

    container.add_item(ui.TextDisplay(details_md))
    return container


# ---------------------------------------------------------------------------
# Interactive Components
# ---------------------------------------------------------------------------

class RoleSelectDropdown(ui.Select):
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

        new_view = RolesView(
            author_id=self.view.author_id,
            active_faction=self.active_faction,
            detail_role_key=rkey,
        )
        await interaction.response.edit_message(view=new_view)


class FactionButton(ui.Button):
    def __init__(self, faction: str, active_faction: str) -> None:
        meta      = _FACTION_META[faction]
        is_active = (faction == active_faction)

        emoji_str = meta["emoji"]
        button_emoji = None
        if emoji_str:
            if emoji_str.startswith("<"):
                try:
                    button_emoji = discord.PartialEmoji.from_str(emoji_str)
                except Exception:
                    pass
            else:
                button_emoji = emoji_str

        super().__init__(
            label     = meta["label"],
            emoji     = button_emoji,
            style     = meta["style"] if is_active else discord.ButtonStyle.secondary,
            custom_id = f"faction_tab_{faction}",
            disabled  = is_active,
        )
        self.faction = faction

    async def callback(self, interaction: discord.Interaction) -> None:
        new_view = RolesView(author_id=self.view.author_id, active_faction=self.faction)
        await interaction.response.edit_message(view=new_view)


class BackToRosterButton(ui.Button):
    def __init__(self, active_faction: str) -> None:
        super().__init__(
            label     = "← Back to Roster",
            style     = discord.ButtonStyle.secondary,
            custom_id = "back_to_roster",
        )
        self.active_faction = active_faction

    async def callback(self, interaction: discord.Interaction) -> None:
        new_view = RolesView(author_id=self.view.author_id, active_faction=self.active_faction)
        await interaction.response.edit_message(view=new_view)


# ---------------------------------------------------------------------------
# Main LayoutView
# ---------------------------------------------------------------------------

class RolesView(MafiosoLayoutView):
    """Components V2 LayoutView for the interactive roles directory."""

    def __init__(
        self,
        author_id: int,
        active_faction: str = FACTION_PROTAGONIST,
        detail_role_key: str | None = None,
    ) -> None:
        super().__init__(timeout=300)
        self.author_id = author_id
        self.active_faction = active_faction
        self.detail_role_key = detail_role_key

        # Build Container card
        if detail_role_key and detail_role_key in roles.ROLES_METADATA:
            container = _build_role_detail_card(detail_role_key, roles.ROLES_METADATA[detail_role_key])
            footer_text = roles.ROLES_METADATA[detail_role_key].get("footer") or "Mafioso Role Inspection"
        else:
            container = _build_faction_card(active_faction)
            footer_text = "Mafioso  •  Use the dropdown below to inspect any role"

        container.add_item(ui.Separator())

        # ActionRow 1: Character Select Dropdown
        dropdown_row = ui.ActionRow(RoleSelectDropdown(active_faction))
        container.add_item(dropdown_row)

        # ActionRow 2: Faction Tab Navigation Buttons
        buttons_row = ui.ActionRow()
        if detail_role_key:
            buttons_row.add_item(BackToRosterButton(active_faction))
            for faction in FACTION_ORDER:
                if faction != active_faction:
                    buttons_row.add_item(FactionButton(faction, active_faction))
        else:
            for faction in FACTION_ORDER:
                buttons_row.add_item(FactionButton(faction, active_faction))

        container.add_item(buttons_row)
        container.add_item(ui.Separator())
        container.add_item(ui.TextDisplay(small_footer(footer_text)))

        self.add_item(container)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                f"{get_emoji('cross')} **Unauthorized:** Only the person who ran this command can interact with it.",
                ephemeral=True,
            )
            return False
        return True
