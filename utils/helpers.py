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
    embed: discord.Embed | None = None,
    view: discord.ui.View | None = None,
    ephemeral: bool = False,
) -> discord.Message | None:
    message_kwargs: dict[str, object] = {}
    if content is not None:
        message_kwargs["content"] = content
    if embed is not None:
        message_kwargs["embed"] = embed
    if view is not None:
        message_kwargs["view"] = view

    if ctx.interaction is not None:
        if ctx.interaction.response.is_done():
            return await ctx.interaction.followup.send(**message_kwargs, ephemeral=ephemeral)
        else:
            await ctx.interaction.response.send_message(**message_kwargs, ephemeral=ephemeral)
            return await ctx.interaction.original_response()

    return await ctx.send(**message_kwargs)
