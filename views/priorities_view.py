from __future__ import annotations

import discord
from ui.base import MafiosoLayoutView
from ui import build_v2_layout
from config import get_emoji
from utils.roles import role_registry
import roles


class AntagonistConversionButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(
            label="Antagonist Conversion",
            style=discord.ButtonStyle.secondary,
            custom_id="antagonist_conversion_btn",
            emoji=get_emoji("mafia"),
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            f"{get_emoji('info')} **Antagonist Conversion**\nWhen the main killing role (e.g. Frieza) is eliminated, a random Mafia member inherits the base kill ability.",
            ephemeral=True,
        )


class PrioritiesView(MafiosoLayoutView):
    def __init__(self) -> None:
        super().__init__(timeout=180)
        self.add_item(AntagonistConversionButton())

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
        return build_v2_layout(
            title=f"{get_emoji('roster')} Role Action Priorities",
            description="\n".join(description_lines),
            color=discord.Color.gold(),
            view=view,
            footer_text="Mafioso Priority System",
        )
