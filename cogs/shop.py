from __future__ import annotations

import discord
from discord.ext import commands

from utils.embeds import build_shop_embed
from utils.helpers import send_hybrid_response


class ShopCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.hybrid_group(name="shop", description="Browse anime mafia cosmetics and inventory")
    async def shop(self, ctx: commands.Context) -> None:
        if ctx.invoked_subcommand is None:
            await send_hybrid_response(ctx, "Try `shop inventory` or `shop cosmetics`.", ephemeral=True)

    @shop.command(name="inventory")
    async def inventory(self, ctx: commands.Context) -> None:
        database = getattr(self.bot, "db", None)
        if database is None:
            await send_hybrid_response(ctx, "Shop system is not ready yet.", ephemeral=True)
            return

        items = await database.get_inventory_items(ctx.author.id)
        if not items:
            await send_hybrid_response(ctx, "Your inventory is empty.", ephemeral=True)
            return

        lines = [f"{item.name} x{item.quantity} - {item.item_type}" for item in items]
        embed = build_shop_embed(f"{ctx.author.display_name}'s Inventory", "\n".join(lines))
        await send_hybrid_response(ctx, embed=embed, ephemeral=True)

    @shop.command(name="cosmetics")
    async def cosmetics(self, ctx: commands.Context) -> None:
        database = getattr(self.bot, "db", None)
        if database is None:
            await send_hybrid_response(ctx, "Shop system is not ready yet.", ephemeral=True)
            return

        cosmetics = await database.list_cosmetics()
        if not cosmetics:
            await send_hybrid_response(ctx, "No cosmetics have been registered yet.", ephemeral=True)
            return

        lines = [f"{row['name']} - {row['cosmetic_type']} ({row['rarity']})" for row in cosmetics[:10]]
        embed = build_shop_embed("Available Cosmetics", "\n".join(lines))
        await send_hybrid_response(ctx, embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ShopCog(bot))
