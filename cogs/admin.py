from __future__ import annotations

import discord
from discord.ext import commands

from utils.helpers import send_hybrid_response


class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.hybrid_group(name="admin", description="Administrative controls for anime mafia")
    async def admin(self, ctx: commands.Context) -> None:
        if ctx.invoked_subcommand is None:
            await send_hybrid_response(ctx, "Try `admin sync`.", ephemeral=True)

    @admin.command(name="sync")
    @commands.has_permissions(administrator=True)
    @discord.app_commands.checks.has_permissions(administrator=True)
    async def sync_commands(self, ctx: commands.Context) -> None:
        synced = await self.bot.tree.sync()
        await send_hybrid_response(ctx, f"Synced {len(synced)} commands.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
