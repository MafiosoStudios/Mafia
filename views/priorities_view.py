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
        ordered_keys = [
            "blackbeard",
            "makima",
            "tosen",
            "dazai",
            "asta",
            "doctor_tenma",
            "frieren",
            "tobirama_senju",
            "l",
            "kishibe",
            "ayanokoji_kiyotaka",
            "maomao",
            "levi_ackerman",
            "frieza",
            "light_yagami",
            "muzan_kibutsuji",
            "hisoka",
            "eren_jaeger",
            "gilgamesh",
        ]

        lines = [
            "Roles execute night actions in strict priority order from top to bottom:\n"
        ]

        for idx, key in enumerate(ordered_keys, 1):
            meta = roles.ROLES_METADATA.get(key, {})
            name = meta.get("name", key.replace("_", " ").title())
            emoji_str = get_emoji(key)
            display_name = f"{emoji_str} **{name}**" if emoji_str else f"**{name}**"
            lines.append(f"`{idx}.` {display_name}")

        view = PrioritiesView()
        view.add_item(AntagonistConversionButton())

        return build_v2_layout(
            title=f"{get_emoji('roster')} Role Action Priorities",
            description="\n".join(lines),
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
        )
