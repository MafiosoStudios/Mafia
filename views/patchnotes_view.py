from __future__ import annotations

import discord
from config import get_emoji


# ---------------------------------------------------------------------------
# PATCH NOTES DATA
# Add new versions by appending a dict to the end of this list.
# Fields: version, date, title, description, changes (list of strings)
# ---------------------------------------------------------------------------
PATCHES: list[dict] = [
    {
        "version": "1.0.0",
        "date": "July 17, 2026",
        "title": "Mafioso — Official Launch",
        "description": (
            "The first official release of **Mafioso**, the ultimate anime-themed "
            "social deduction Discord bot. Every role, every faction, every ability "
            "has been crafted around the actual powers and personalities of iconic anime characters."
        ),
        "changes": [
            "**26 unique anime roles** across Town, Mafia, and Neutral factions",
            "**Night & Day cycle** with full ability resolution engine",
            "**Trial System** — nomination, plea, verdict, and retrial support",
            "**Leaderboard System** — across all servers, with XP and levels",
            "**Custom Role Emojis** — for all faction roles and characters",
            "**Live Support** — Taking active feedback and suggestions from the community",
            "**Player profiles**, XP, levels, win rates, and leaderboards",
            "**Shop system** with cosmetic inventory",
            "**Interactive tutorial** and full role directory",
            "Bot presence, admin reset, and developer tools",
        ],
    },
    # -----------------------------------------------------------------------
    # TEMPLATE — copy this block and fill it in to add a new patch version:
    # {
    #     "version": "1.1.0",
    #     "date": "Month DD, YYYY",
    #     "title": "Short descriptive patch title",
    #     "description": "One or two sentence summary of what this patch focused on.",
    #     "changes": [
    #         "emoji **Category** — description of change",
    #     ],
    # },
    # -----------------------------------------------------------------------
]


class PatchNotesView(discord.ui.View):
    """Paginated patch notes view. Previous/Next buttons navigate between versions."""

    PATCHES: list[dict] = PATCHES

    def __init__(self, index: int) -> None:
        super().__init__(timeout=300)
        self.index = index
        self._update_buttons()

    # ------------------------------------------------------------------
    # Embed builder
    # ------------------------------------------------------------------
    @staticmethod
    def build_embed(index: int) -> discord.Embed:
        patch = PATCHES[index]
        total = len(PATCHES)

        changes_text = "\n".join(f"> {line}" for line in patch["changes"])

        embed = discord.Embed(
            title=f"{patch['title']}",
            description=(
                f"**Version {patch['version']}** — {patch['date']}\n\n"
                f"{patch['description']}\n\n"
                f"**What's New:**\n{changes_text}"
            ),
            color=discord.Color.from_rgb(0, 0, 0),
        )
        embed.set_footer(text=f"Mafioso Patch Notes  •  Version {patch['version']}  •  {index + 1} of {total}")
        return embed

    # ------------------------------------------------------------------
    # Button state helpers
    # ------------------------------------------------------------------
    def _update_buttons(self) -> None:
        total = len(PATCHES)
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                if item.custom_id == "patch_prev":
                    item.disabled = self.index <= 0
                elif item.custom_id == "patch_next":
                    item.disabled = self.index >= total - 1

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------
    @discord.ui.button(
        label="◀ Previous",
        style=discord.ButtonStyle.secondary,
        custom_id="patch_prev",
        disabled=True,  # will be corrected by _update_buttons in __init__
    )
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.index -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(self.index), view=self)

    @discord.ui.button(
        label="Next ▶",
        style=discord.ButtonStyle.secondary,
        custom_id="patch_next",
    )
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.index += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(self.index), view=self)
