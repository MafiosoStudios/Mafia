from __future__ import annotations

from collections.abc import Sequence
import discord
from discord import ui

from ui.theme import (
    COLOR_PRIMARY,
    COLOR_SECONDARY,
    COLOR_SYSTEM,
    heading,
    subheading,
    small_footer,
    bold,
)
from config import get_emoji, get_event_image


def build_status_card(
    title: str,
    description: str | None = None,
    *,
    color: discord.Color = COLOR_SECONDARY,
    thumbnail_url: str | None = None,
    footer_text: str = "Anime Mafia",
) -> ui.Container:
    """Builds a basic status/info V2 Container card."""
    container = ui.Container(accent_color=color)
    
    content = heading(title)
    if description:
        content += f"\n\n{description}"
        
    text_item = ui.TextDisplay(content)
    
    if thumbnail_url:
        container.add_item(ui.Section(text_item, accessory=ui.Thumbnail(thumbnail_url)))
    else:
        container.add_item(text_item)

        
    container.add_item(ui.Separator())
    container.add_item(ui.TextDisplay(small_footer(footer_text)))
    return container


def build_card(
    title: str,
    body: str | None = None,
    *,
    color: discord.Color = COLOR_SYSTEM,
    thumbnail_url: str | None = None,
    image_url: str | None = None,
    footer_text: str = "Anime Mafia",
) -> ui.Container:
    """Builds a rich content V2 Container card supporting thumbnail, media gallery, and footer."""
    container = ui.Container(accent_color=color)
    
    content = heading(title)
    if body:
        content += f"\n\n{body}"
        
    text_item = ui.TextDisplay(content)
    
    if thumbnail_url:
        container.add_item(ui.Section(text_item, accessory=ui.Thumbnail(thumbnail_url)))
    else:
        container.add_item(text_item)
        
    if image_url:
        container.add_item(ui.MediaGallery(discord.MediaGalleryItem(image_url)))
        
    container.add_item(ui.Separator())
    container.add_item(ui.TextDisplay(small_footer(footer_text)))
    return container


def build_v2_layout(
    title: str | None = None,
    description: str | None = None,
    *,
    color: discord.Color = COLOR_SYSTEM,
    image_url: str | None = None,
    thumbnail_url: str | None = None,
    footer_text: str = "Anime Mafia",
    view: discord.ui.LayoutView | discord.ui.View | None = None,
) -> ui.LayoutView:
    """Builds a complete LayoutView from legacy embed parameters and an optional View."""
    from ui.base import MafiosoLayoutView

    container = ui.Container(accent_color=color)
    
    header_md = ""
    if title:
        header_md = heading(title)
        if description:
            header_md += f"\n\n{description}"
    elif description:
        header_md = description

    if header_md:
        text_display = ui.TextDisplay(header_md)
        if thumbnail_url:
            container.add_item(ui.Section(text_display, accessory=ui.Thumbnail(thumbnail_url)))
        else:
            container.add_item(text_display)
        
    if image_url:
        container.add_item(ui.MediaGallery(discord.MediaGalleryItem(image_url)))
        
    if view is not None:
        items_to_add = []
        if hasattr(view, "children"):
            items_to_add = [c for c in view.children if not isinstance(c, ui.Container)]
            
        if items_to_add:
            container.add_item(ui.Separator())
            current_row = ui.ActionRow()
            for item in items_to_add:
                if isinstance(item, ui.Select):
                    if current_row.children:
                        container.add_item(current_row)
                        current_row = ui.ActionRow()
                    s_row = ui.ActionRow()
                    s_row.add_item(item)
                    container.add_item(s_row)
                elif isinstance(item, ui.Button):
                    current_row.add_item(item)
                    if len(current_row.children) == 5:
                        container.add_item(current_row)
                        current_row = ui.ActionRow()
                elif isinstance(item, ui.ActionRow):
                    if current_row.children:
                        container.add_item(current_row)
                        current_row = ui.ActionRow()
                    container.add_item(item)
            if current_row.children:
                container.add_item(current_row)

    if footer_text:
        container.add_item(ui.Separator())
        container.add_item(ui.TextDisplay(small_footer(footer_text)))

    timeout = getattr(view, "timeout", 180) if view else 180
    layout = MafiosoLayoutView(timeout=timeout)
    layout.add_item(container)
    return layout






def build_lobby_card(
    *,
    guild_name: str,
    leader_text: str,
    roster_lines: Sequence[str],
    current_players: int,
    min_players: int,
    max_players: int,
    started: bool = False,
    gamemode: str = "chaos",
) -> ui.Container:
    """Builds the main V2 Container card for game lobbies, replacing build_lobby_embed."""
    color = discord.Color.from_rgb(255, 255, 255)
    lobby_image = get_event_image("lobby")
    status_label = "Match in progress" if started else "Lobby waiting for players"
    
    container = ui.Container(accent_color=color)
    
    # Title & Header
    header_text = f"{heading(f'{guild_name} Lobby')}\n*{status_label}*"
    container.add_item(ui.TextDisplay(header_text))
    container.add_item(ui.Separator())
    
    # Details & Meta Information
    mode_emoji = get_emoji("category_control")
    details_md = (
        f"{subheading('Lobby Information')}\n"
        f"• {bold('Lobby Leader')}: {leader_text}\n"
        f"• {bold('Players')}: {current_players}/{max_players} (Min: {min_players})\n"
        f"• {bold('Game Mode')}: {mode_emoji} {gamemode.upper()}\n\n"
        f"{subheading('Current Roster')}\n"
    )
    
    if roster_lines:
        details_md += "\n".join(roster_lines)
    else:
        details_md += "*No players joined yet.*"
        
    details_md += (
        f"\n\n{subheading('Start Rule')}\n"
        "Only the lobby leader, admins, or bypass roles can launch the match."
    )
    
    container.add_item(ui.TextDisplay(details_md))

    # Full-width lobby banner below text
    if lobby_image:
        container.add_item(ui.MediaGallery(discord.MediaGalleryItem(lobby_image)))

    return container



