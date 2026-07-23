from __future__ import annotations

import discord
from ui.base import MafiosoLayoutView
from ui import build_v2_layout
from config import get_emoji
from utils.roles import role_registry
import roles


class BackToPrioritiesButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(
            label="Back to Priorities",
            style=discord.ButtonStyle.secondary,
            custom_id="back_to_priorities_btn",
            emoji="⬅️",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = PrioritiesView.build_layout()
        await interaction.response.edit_message(view=view)


class AntagonistConversionButton(discord.ui.Button):
    def __init__(self) -> None:
        emoji_val = get_emoji("mafia") or "⚔️"
        super().__init__(
            label="Antagonist Conversion",
            style=discord.ButtonStyle.secondary,
            custom_id="antagonist_conversion_btn",
            emoji=emoji_val if emoji_val else None,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        view = PrioritiesView.build_conversion_layout()
        await interaction.response.edit_message(view=view)


class PrioritiesView(MafiosoLayoutView):
    def __init__(self) -> None:
        super().__init__(timeout=180)

    @staticmethod
    def build_layout() -> discord.ui.LayoutView:
        all_roles = sorted(role_registry.all(), key=lambda c: (c.priority, c.role_key))

        priority_labels = {
            1: "Priority 1 — Roleblockers & Redirects",
            2: "Priority 2 — Protective & Shields",
            3: "Priority 3 — Investigative & Support",
            4: "Priority 4 — Attacks, Executions & Conversions",
            5: "Priority 5 — Passives & Special Roles",
            9: "Priority 9 — Late Phase & Special Triggers",
        }

        priority_groups: dict[int, list[str]] = {}
        for role_cls in all_roles:
            p = role_cls.priority
            meta = roles.ROLES_METADATA.get(role_cls.role_key, {})
            emoji_str = get_emoji(role_cls.role_key)
            name = meta.get("name", role_cls.role_key.capitalize())
            display = f"{emoji_str} {name}" if emoji_str else name
            priority_groups.setdefault(p, []).append(display)

        description_lines = [
            "Roles execute night actions in strict priority order (from top to bottom).\n"
        ]

        for p in sorted(priority_groups.keys()):
            group_header = priority_labels.get(p, f"Priority {p}")
            role_list = " • ".join(priority_groups[p])
            description_lines.append(f"### {group_header}\n{role_list}\n")

        view = PrioritiesView()
        view.add_item(AntagonistConversionButton())

        return build_v2_layout(
            title=f"{get_emoji('roster')} Role Action Priorities",
            description="\n".join(description_lines),
            color=discord.Color.gold(),
            view=view,
            footer_text="Mafioso Priority System",
        )

    @staticmethod
    def build_conversion_layout() -> discord.ui.LayoutView:
        e_bb = get_emoji("blackbeard") or "🏴‍☠️"
        e_ly = get_emoji("light_yagami") or "📓"
        e_mk = get_emoji("makima") or "⛓️"
        e_mz = get_emoji("muzan_kibutsuji") or "👹"

        view = PrioritiesView()
        view.add_item(BackToPrioritiesButton())

        return build_v2_layout(
            title=f"{get_emoji('mafia')} Antagonist Conversion Rules",
            description=(
                "The Antagonist (Mafia) faction must **ALWAYS** maintain an active killing threat.\n\n"
                "If the primary Antagonist killer dies by any means, the highest-priority "
                "living Antagonist is stripped of all former powers/abilities and inherits the **Base Kill** power.\n\n"
                "### 🩸 Inheritance Priority Order:\n"
                f"`1.` {e_bb} **Blackbeard**\n"
                f"`2.` {e_ly} **Light Yagami**\n"
                f"`3.` {e_mk} **Makima**\n"
                f"`4.` {e_mz} **Muzan Kibutsuji**\n\n"
                "*(If none of the above exist in the match, any remaining living Antagonist receives the Base Kill).*"
            ),
            color=discord.Color.red(),
            view=view,
            footer_text="Mafioso Conversion Engine",
g        )
