from __future__ import annotations

from collections.abc import Sequence

import discord


ANIME_PRIMARY = discord.Color.from_rgb(110, 58, 190)
ANIME_SECONDARY = discord.Color.from_rgb(19, 16, 28)
ANIME_GOLD = discord.Color.from_rgb(212, 175, 55)
ANIME_TEAL = discord.Color.from_rgb(53, 169, 166)
ANIME_RED = discord.Color.from_rgb(201, 72, 72)


def build_embed(
    title: str,
    description: str | None = None,
    *,
    color: discord.Color = ANIME_PRIMARY,
    image_url: str | None = None,
    thumbnail_url: str | None = None,
) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=color)
    embed.set_footer(text="Anime Mafia")
    if image_url:
        embed.set_image(url=image_url)
    if thumbnail_url:
        embed.set_thumbnail(url=thumbnail_url)
    return embed


def build_status_embed(title: str, description: str | None = None) -> discord.Embed:
    return build_embed(title, description, color=ANIME_SECONDARY)


def build_profile_embed(title: str, description: str | None = None) -> discord.Embed:
    return build_embed(title, description, color=discord.Color.from_rgb(0, 0, 0))


def build_victory_embed(title: str, description: str | None = None) -> discord.Embed:
    return build_embed(title, description, color=ANIME_GOLD)


def build_shop_embed(title: str, description: str | None = None) -> discord.Embed:
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
) -> discord.Embed:
    from config import get_event_image

    status_label = "Match in progress" if started else "Lobby waiting for players"
    color = discord.Color.from_rgb(255, 255, 255)
    lobby_image = get_event_image("lobby")
    embed = build_embed(f"{guild_name} Lobby", status_label, color=color, image_url=lobby_image)
    embed.add_field(name="Lobby Leader", value=leader_text, inline=True)
    embed.add_field(name="Players", value=f"{current_players}/{max_players}", inline=True)
    embed.add_field(name="Minimum to Start", value=str(min_players), inline=True)
    roster = "\n".join(roster_lines) if roster_lines else "No players joined yet."
    embed.add_field(name="Current Roster", value=roster, inline=False)
    embed.add_field(
        name="Start Rule",
        value="Only the lobby leader, admins, or bypass roles can launch the match.",
        inline=False,
    )
    return embed