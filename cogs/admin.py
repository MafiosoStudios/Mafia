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
    async def sync_commands(self, ctx: commands.Context) -> None:
        import config
        has_perm = ctx.author.id in config.ADMIN_IDS or (ctx.guild and ctx.author.guild_permissions.administrator)
        if not has_perm:
            await send_hybrid_response(ctx, "❌ **Unauthorized:** You do not have permission to use this command.", ephemeral=True)
            return
        # Clear guild commands to remove duplicates
        self.bot.tree.clear_commands(guild=ctx.guild)
        await self.bot.tree.sync(guild=ctx.guild)
        # Sync globally
        synced = await self.bot.tree.sync()
        await send_hybrid_response(ctx, f"Cleaned duplicates and synced {len(synced)} global commands successfully!", ephemeral=True)

    @commands.hybrid_command(name="reset", description="Reset the bot in the server, cleaning up game channels and status")
    async def reset(self, ctx: commands.Context) -> None:
        import config
        has_perm = ctx.author.id in config.ADMIN_IDS or (ctx.guild and ctx.author.guild_permissions.manage_guild)
        if not has_perm:
            await send_hybrid_response(ctx, "❌ **Unauthorized:** You do not have permission to use this command.", ephemeral=True)
            return

        if ctx.guild is None:
            await send_hybrid_response(ctx, "This command must be used in a server.", ephemeral=True)
            return

        # Defer to avoid interaction timeout
        await ctx.defer(ephemeral=True)

        # 1. Remove active game from manager
        game_manager = getattr(self.bot, "game_manager", None)
        removed_game = False
        if game_manager:
            game_handle = await game_manager.get_game_by_guild(ctx.guild.id)
            if game_handle:
                try:
                    await game_manager.remove_game(game_handle.game_id)
                    removed_game = True
                except Exception:
                    pass

        # 2. Find and delete mafia channels/categories
        deleted_categories = 0
        deleted_channels = 0
        for category in list(ctx.guild.categories):
            if "mafia match" in category.name.lower():
                try:
                    for ch in list(category.channels):
                        await ch.delete(reason="Mafia bot reset command.")
                        deleted_channels += 1
                    await category.delete(reason="Mafia bot reset command.")
                    deleted_categories += 1
                except Exception:
                    pass

        for channel in list(ctx.guild.text_channels):
            if channel.name.lower().startswith("mafia-"):
                try:
                    await channel.delete(reason="Mafia bot reset command.")
                    deleted_channels += 1
                except Exception:
                    pass

        # 3. Refresh presence/status
        try:
            await self.bot.change_presence(activity=discord.Game(name="Anime Mafia"), status=discord.Status.online)
        except Exception:
            pass

        await send_hybrid_response(
            ctx,
            f"✅ **Server Reset Completed!**\n"
            f"• Removed active session: {'Yes' if removed_game else 'None found'}\n"
            f"• Deleted categories: **{deleted_categories}**\n"
            f"• Deleted channels: **{deleted_channels}**\n"
            f"• Bot status refreshed.",
            ephemeral=True
        )

    @commands.hybrid_command(name="dev_restart", description="Restart the bot process (Developer only)")
    async def dev_restart(self, ctx: commands.Context) -> None:
        import config
        if ctx.author.id not in config.ADMIN_IDS:
            await send_hybrid_response(ctx, "❌ **Unauthorized:** Only bot developers can run this command.", ephemeral=True)
            return

        import os
        import sys

        await send_hybrid_response(ctx, "🔄 **Restarting bot process...** Please wait.", ephemeral=True)
        
        # Clean up database and message queue
        try:
            if hasattr(self.bot, "db"):
                await self.bot.db.close()
            if hasattr(self.bot, "message_queue"):
                await self.bot.message_queue.stop()
        except Exception:
            pass

        # Clean existing restart-channel arguments from sys.argv if present
        clean_argv = list(sys.argv)
        while "--restart-channel" in clean_argv:
            try:
                idx = clean_argv.index("--restart-channel")
                clean_argv.pop(idx + 1)
                clean_argv.pop(idx)
            except ValueError:
                break

        # Restart process and pass the restart channel ID
        os.execv(sys.executable, [sys.executable] + clean_argv + ["--restart-channel", str(ctx.channel.id)])


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
