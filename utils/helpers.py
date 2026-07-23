from __future__ import annotations

from datetime import datetime, timezone
import secrets
import string

import discord
from discord.ext import commands


_ALPHABET = string.ascii_uppercase + string.digits


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def generate_invite_code(length: int = 6) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(value, maximum))


async def send_hybrid_response(
    ctx: commands.Context[commands.Bot, object, object],
    content: str | None = None,
    *,
    embed: discord.ui.LayoutView | None = None,
    view: discord.ui.LayoutView | None = None,
    ephemeral: bool = False,
) -> discord.Message | None:
    from ui.components import build_v2_layout
    final_view = view or embed

    if final_view is None and content is not None:
        final_view = build_v2_layout(description=content, footer_text="")
    elif final_view is not None and content is not None:
        final_view = build_v2_layout(description=content, view=final_view, footer_text="")

    if ctx.interaction is not None:
        if ctx.interaction.response.is_done():
            return await ctx.interaction.followup.send(view=final_view, ephemeral=ephemeral)
        else:
            await ctx.interaction.response.send_message(view=final_view, ephemeral=ephemeral)
            return await ctx.interaction.original_response()

    return await ctx.send(view=final_view)




def get_emoji_url(emoji_str: str) -> str | None:
    if not emoji_str:
        return None
    emoji_str = emoji_str.strip()
    
    # Check if it's a custom Discord emoji: <:name:id> or <a:name:id>
    if emoji_str.startswith("<") and emoji_str.endswith(">"):
        parts = emoji_str.split(":")
        if len(parts) >= 3:
            emoji_id = parts[-1].rstrip(">")
            is_animated = emoji_str.startswith("<a:")
            ext = "gif" if is_animated else "png"
            return f"https://cdn.discordapp.com/emojis/{emoji_id}.{ext}"
            
    # Otherwise, assume it's a standard unicode emoji and get its Twemoji URL
    try:
        codepoints = []
        for char in emoji_str:
            cp = f"{ord(char):x}"
            if cp != "fe0f":
                codepoints.append(cp)
        if not codepoints:
            return None
        hex_str = "-".join(codepoints)
        return f"https://cdnjs.cloudflare.com/ajax/libs/twemoji/14.0.2/72x72/{hex_str}.png"
    except Exception:
        return None
