from __future__ import annotations

import discord
from discord.ext import commands

from utils.embeds import build_shop_embed
from utils.helpers import send_hybrid_response


class ShopCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.hybrid_group(name="shop", description="Browse Mafioso cosmetics and inventory")
    @commands.cooldown(1, 1.5, commands.BucketType.user)
    async def shop(self, ctx: commands.Context) -> None:
        if ctx.invoked_subcommand is None:
            await send_hybrid_response(ctx, "Try `shop inventory` or `shop cosmetics`.", ephemeral=True)

    @shop.command(name="inventory")
    @commands.cooldown(1, 1.5, commands.BucketType.user)
    async def inventory(self, ctx: commands.Context) -> None:
        database = getattr(self.bot, "db", None)
        if database is None:
            await send_hybrid_response(ctx, "Shop system is not ready yet.", ephemeral=True)
            return

        items = await database.get_inventory_items(ctx.author.id)
        if not items:
            await send_hybrid_response(ctx, "Your inventory is empty.", ephemeral=True)
            return

        from ui import build_v2_layout
        lines = [f"{item.name} x{item.quantity} - {item.item_type}" for item in items]
        shop_layout = build_v2_layout(title=f"{ctx.author.display_name}'s Inventory", description="\n".join(lines), footer_text="")
        await send_hybrid_response(ctx, view=shop_layout, ephemeral=True)

    @shop.command(name="cosmetics")
    @commands.cooldown(1, 1.5, commands.BucketType.user)
    async def cosmetics(self, ctx: commands.Context) -> None:
        database = getattr(self.bot, "db", None)
        if database is None:
            await send_hybrid_response(ctx, "Shop system is not ready yet.", ephemeral=True)
            return

        cosmetics = await database.list_cosmetics()
        if not cosmetics:
            await send_hybrid_response(ctx, "No cosmetics have been registered yet.", ephemeral=True)
            return

        from ui import build_v2_layout
        lines = [f"{row['name']} - {row['cosmetic_type']} ({row['rarity']})" for row in cosmetics[:10]]
        shop_layout = build_v2_layout(title="Available Cosmetics", description="\n".join(lines), footer_text="")
        await send_hybrid_response(ctx, view=shop_layout, ephemeral=True)



async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ShopCog(bot))
