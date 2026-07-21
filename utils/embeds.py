from __future__ import annotations

from collections.abc import Sequence
import discord
from discord import ui

from ui.components import build_v2_layout, build_lobby_card
from ui.theme import (
    COLOR_PRIMARY,
    COLOR_SECONDARY,
    COLOR_NEUTRAL,
    COLOR_TOWN,
    COLOR_MAFIA,
)

ANIME_PRIMARY = COLOR_PRIMARY
ANIME_SECONDARY = COLOR_SECONDARY
ANIME_GOLD = COLOR_NEUTRAL
ANIME_TEAL = COLOR_TOWN
ANIME_RED = COLOR_MAFIA


def build_embed(
    title: str,
    description: str | None = None,
    *,
    color: discord.Color = ANIME_PRIMARY,
    image_url: str | None = None,
    thumbnail_url: str | None = None,
    footer_text: str = "",
    view: ui.LayoutView | ui.View | None = None,
) -> ui.LayoutView:

    """Builds a V2 LayoutView card replacing the legacy discord.Embed builder."""
    return build_v2_layout(
        title=title,
        description=description,
        color=color,
        image_url=image_url,
        thumbnail_url=thumbnail_url,
        footer_text=footer_text,
        view=view,
    )


def build_status_embed(title: str, description: str | None = None) -> ui.LayoutView:
    return build_embed(title, description, color=ANIME_SECONDARY)


def build_profile_embed(title: str, description: str | None = None) -> ui.LayoutView:
    return build_embed(title, description, color=discord.Color.from_rgb(0, 0, 0))


def build_victory_embed(title: str, description: str | None = None) -> ui.LayoutView:
    return build_embed(title, description, color=ANIME_GOLD)


def build_shop_embed(title: str, description: str | None = None) -> ui.LayoutView:
    return build_embed(title, description, color=ANIME_TEAL)


def build_lobby_embed(
    *,
    guild_name: str,
    leader_text: str,
    roster_lines: Sequence[str],
    current_players: int,
    min_players: int,
    max_players: int,
    started: bool = False,
    gamemode: str = "chaos",
) -> ui.LayoutView:
    """Builds a V2 LayoutView card replacing legacy build_lobby_embed."""
    container = build_lobby_card(
        guild_name=guild_name,
        leader_text=leader_text,
        roster_lines=roster_lines,
        current_players=current_players,
        min_players=min_players,
        max_players=max_players,
        started=started,
        gamemode=gamemode,
    )
    layout = ui.LayoutView(timeout=180)
    layout.add_item(container)
    return layout