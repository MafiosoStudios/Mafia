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
    {
        "version": "1.0.1",
        "date": "July 18, 2026",
        "title": "Version 1.0.1 — Mahoraga Rework, Bug Fixes, and More",
        "description": (
            "A major update introducing a complete rework for Mahoraga, "
            "critical bug fixes to the game and administration loops, "
            "interactive roles directory, and player profile enhancements."
        ),
        "changes": [
            "**Mahoraga Rework** — Adapted factions no longer harm Mahoraga at night; adapt to all 3 factions to gain vote/trial immunity",
            "**Trial Crash Fixed** — Resolved issue where the game would draw or crash during voting and trial verdict phases",
            "**Interactive Directory** — Added `!roles` command with faction tab navigation to inspect any character's abilities",
            "**Profile Draws** — Added Draw category field in the profile card output (between Losses and Games Played)",
            "**Admin Sync Fixed** — Fixed command sync mechanism failing to respond during registration of slash commands",
            "**Victory Embeds** — Cleaned up and polished the game over win screens for Protagonists, Antagonists, and Neutrals",
            "**Visual Polish** — Multiple interface alignments, custom emojis, and interaction locks for command authors",
        ],
    },
    {
        "version": "1.0.2",
        "date": "July 20, 2026",
        "title": "Version 1.0.2 — Components V2 Overhaul, Design System & Engine Hardening",
        "description": (
            "A comprehensive system-wide upgrade introducing Discord's Components V2 layout "
            "architecture, a unified anime design system, 100% embed elimination, "
            "and complete interaction stability across all commands and game phases."
        ),
        "changes": [
            "**Components V2 Overhaul** — Migrated the entire bot messaging layer to Discord Components V2 LayoutViews with zero legacy embeds",
            "**Sleek Card Design** — Every button, select menu, and text block is enclosed inside unified HSL Container cards across the entire bot",
            "**Image & Media Parity** — Full-width media gallery placement for event banners and side thumbnail accessories for role character icons",
            "**Interaction Stability** — Automated ActionRow component wrapping and interaction deferrals eliminating 400 Bad Request and 404 Not Found errors",
            "**Server Settings Overhaul** — Upgraded `/settings` command to display formatted game parameters with descriptions and quick configuration tools",
            "**Profile & Status Polish** — Restructured `/profile` and `/game status` into sleek V2 cards showing rank, level, XP, coins, and win rates",
        ],
    },
    {
        "version": "1.0.3",
        "date": "July 21, 2026",
        "title": "Version 1.0.3 — Higuruma Aura, Lobby Queue System & Defense DM Notifications",
        "description": (
            "An action-packed update introducing anonymous attacker feedback for nullified attacks, "
            "Hiromi Higuruma cinematic animations & courtroom limits, channel lockdown removal during trials, "
            "persistent game lobbies with join/leave queues, and developer global role management."
        ),
        "changes": [
            "**Anonymous Defense DMs** — Fixed issue where attackers were left uninformed when attacks were nullified (e.g. Tobirama counter, Frieren barrier, Doctor Tenma heal, Muzan/Mahoraga passives)",
            "**Hiromi Higuruma Aura** — Added custom animations and cinematic domain expansion GIF reveals for Retrials and Deadly Sentencing",
            "**Higuruma Ability Limit** — Hiromi Higuruma is now limited to using at most 1 courtroom ability (Retrial or Deadly Sentencing) per day",
            "**Trial Channel Unlocked** — The main game channel no longer locks during defendant plea; everyone can now speak during trials",
            "**Clear Lobby Command** — Added `/clear` (or `!clear`) command allowing lobby hosts, leaders, and admins to clear out lobbies",
            "**Global Role Control** — Added `/globalroledisable` and `/globalroleenable` commands for bot developers to unload roles globally across all servers",
            "**Persistent Lobbies** — Game lobbies no longer auto-clear after matches; streamlined lobby command names to `/join`, `/lobby`, `/leave`, `/start`, `/clear`",
            "**Lobby Join & Leave Queues** — Players joining or leaving during an active match are added to live Join/Leave queues that resolve automatically after the game",
            "**UI Fixes** — Multiple visual polish improvements, silent real-time lobby updates, and layout refinements",
        ],
    },
    {
        "version": "1.0.4",
        "date": "July 23, 2026",
        "title": "Version 1.0.4 — Antagonist Conversion, Role Priorities & Night Engine Stability",
        "description": (
            "A major mechanical balance and stability update introducing the Antagonist Conversion System, "
            "a strict 1-to-19 role priority resolution engine, the `/priorities` command, "
            "and critical fixes for night end announcements and Muzan Kibutsuji cooldowns."
        ),
        "changes": [
            "**Antagonist Conversion System** — If the primary killing role (Frieza) dies by any means, the highest-priority living Antagonist is stripped of all former abilities/passives and given the Antagonist Base Kill power",
            "**Role Priorities System** — Assigned explicit 1-to-19 priority numbers to every active role across the engine to prevent resolution clashes and ensure smooth night processing",
            "**`/priorities` Command** — Added `/priorities` (or `!priorities`) command to display the exact 1-to-19 execution order of all roles, featuring an interactive red Antagonist Conversion rules button",
            "**Night Action Phase Embed Fix** — Modified the night resolution engine so that when the night phase ends, a brand new notification embed is posted instead of editing the prompt",
            "**Muzan Kibutsuji Cooldown & Infection Fix** — Fixed Muzan Kibutsuji converting from Night 1 and doing it repeatedly without cooldown; strictly enforced Night 3 requirement (every 3 nights)",
        ],
    },
    {
        "version": "1.0.5",
        "date": "July 23, 2026",
        "title": "Version 1.0.5 — Progression System, Custom Rolelists & UI Hardening",
        "description": (
            "A major feature and progression update introducing root `rank.json` configuration, "
            "automated Level/XP/Gold calculation, post-match V2 Container DM reward notifications, "
            "the All-in-One Custom Gamemode Suite, and system-wide UI stability."
        ),
        "changes": [
            "**Global Progression & Ranks** — Added `rank.json` configuration with 8 customizable rank tiers (Bronze to Mafia Legend), level curves, and global MongoDB synchronization",
            "**Match Reward DMs** — Automatically calculates XP, Gold, Level, and Rank after every match and sends an itemized V2 Container DM with level-up/rank-up alerts",
            "**Profile UI Overhaul** — Restructured `/profile` to render player rank, visual progress bar, gold, and global match statistics inside a clean V2 Container card",
            "**Custom Rolelist Suite** — Interactive menu (`/customrolelist`) to create, name, load, and delete custom role lists with real-time role breakdown displays",
            "**Multi-Copy & Balanced Custom Pools** — Full support for duplicate roles in custom lists (e.g. 5x Higuruma) with guaranteed Mafia assignment and balanced role filler",
            "**Non-Destructive Ephemeral UX** — Selecting targets or votes now sends fresh ephemeral notifications instead of overwriting selection dropdowns",
            "**Rate Limit & Deferral Hardening** — Instant <3s interaction deferrals and debounced embed updaters preventing 429 rate limits and 404 interaction errors",
            "**Components V2 Migration** — Upgraded custom gamemode views to pure V2 Container cards with strict `config.py` emoji discipline",
            "**Database State Stability** — Fixed MongoDB BSON serialization issues with sets and Discord message handles during active game state saves",
        ],
    },
]



from ui import MafiosoLayoutView, build_v2_layout


class PatchNotesView(MafiosoLayoutView):
    """Paginated patch notes view using V2 LayoutView."""

    PATCHES: list[dict] = PATCHES

    def __init__(self, index: int) -> None:
        super().__init__(timeout=300)
        self.index = index
        self._update_buttons()

    @staticmethod
    def build_layout_view(index: int) -> MafiosoLayoutView:
        patch = PATCHES[index]
        total = len(PATCHES)

        changes_text = "\n".join(f"> {line}" for line in patch["changes"])
        description = (
            f"**Version {patch['version']}** — {patch['date']}\n\n"
            f"{patch['description']}\n\n"
            f"**What's New:**\n{changes_text}"
        )
        footer_text = f"Mafioso Patch Notes  •  Version {patch['version']}  •  {index + 1} of {total}"

        view = PatchNotesView(index)
        layout = build_v2_layout(
            title=patch["title"],
            description=description,
            color=discord.Color.from_rgb(0, 0, 0),
            footer_text=footer_text,
            view=view,
        )
        return layout

    def _update_buttons(self) -> None:
        total = len(PATCHES)
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                if item.custom_id == "patch_prev":
                    item.disabled = self.index <= 0
                elif item.custom_id == "patch_next":
                    item.disabled = self.index >= total - 1

    @discord.ui.button(
        label="◀ Previous",
        style=discord.ButtonStyle.secondary,
        custom_id="patch_prev",
        disabled=True,
    )
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.index -= 1
        new_layout = self.build_layout_view(self.index)
        await interaction.response.edit_message(view=new_layout)

    @discord.ui.button(
        label="Next ▶",
        style=discord.ButtonStyle.secondary,
        custom_id="patch_next",
    )
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.index += 1
        new_layout = self.build_layout_view(self.index)
        await interaction.response.edit_message(view=new_layout)

