from __future__ import annotations

import discord
from discord.ext import commands

from utils.helpers import send_hybrid_response
from views.help_view import HelpView


class HelpCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _send_help(self, interaction_or_ctx: commands.Context | discord.Interaction) -> None:
        prefix = getattr(self.bot, "config", None).command_prefix if getattr(self.bot, "config", None) else "!"
        view = HelpView(prefix)
        embed = view.build_index_embed(prefix)

        if isinstance(interaction_or_ctx, commands.Context):
            await send_hybrid_response(interaction_or_ctx, embed=embed, view=view, ephemeral=True)
            return

        if interaction_or_ctx.response.is_done():
            await interaction_or_ctx.followup.send(embed=embed, view=view, ephemeral=True)
        else:
            await interaction_or_ctx.response.send_message(embed=embed, view=view, ephemeral=True)

    @commands.command(name="help", help="Show the anime mafia command guide")
    async def help_prefix(self, ctx: commands.Context) -> None:
        await self._send_help(ctx)

    @discord.app_commands.command(name="help", description="Show the anime mafia command guide")
    async def help_app(self, interaction: discord.Interaction) -> None:
        await self._send_help(interaction)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HelpCog(bot))
