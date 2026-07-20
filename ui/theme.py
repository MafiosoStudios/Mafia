from __future__ import annotations

import discord

# Faction & System Color Palette (Anime Mafia House Style)
COLOR_TOWN = discord.Color.from_rgb(53, 169, 166)       # Teal / Hero Faction
COLOR_MAFIA = discord.Color.from_rgb(201, 72, 72)      # Crimson Red / Villain Faction
COLOR_NEUTRAL = discord.Color.from_rgb(212, 175, 55)    # Gold / Neutral Faction
COLOR_SYSTEM = discord.Color.from_rgb(110, 58, 190)    # Deep Purple / Primary System
COLOR_PRIMARY = COLOR_SYSTEM                             # Primary Alias
COLOR_SECONDARY = discord.Color.from_rgb(19, 16, 28)   # Dark Slate / Neutral System

COLOR_SUCCESS = discord.Color.from_rgb(46, 139, 87)     # Emerald / Positive Output
COLOR_ERROR = discord.Color.from_rgb(178, 34, 34)      # Dark Crimson / Error Card

# House Markdown Typography Helpers
def heading(text: str) -> str:
    """Formats text as a Discord V2 Big Title (# Heading)."""
    return f"# {text}"

def subheading(text: str) -> str:
    """Formats text as an in-body section header (## Subheading)."""
    return f"## {text}"

def subsubheading(text: str) -> str:
    """Formats text as a minor header (### Header)."""
    return f"### {text}"

def small_footer(text: str) -> str:
    """Formats footer text using Discord V2 small markdown (-# text)."""
    return f"-# {text}"

def bold(text: str) -> str:
    return f"**{text}**"

def italic(text: str) -> str:
    return f"*{text}*"
