from __future__ import annotations

import discord
from discord.ext import commands
from config import get_emoji

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
            await send_hybrid_response(ctx, f"{get_emoji('cross')} **Unauthorized:** You do not have permission to use this command.", ephemeral=True)
            return
        # Clear guild commands to remove duplicates
        self.bot.tree.clear_commands(guild=ctx.guild)
        await self.bot.tree.sync(guild=ctx.guild)
        # Sync globally
        synced = await self.bot.tree.sync()
        await send_hybrid_response(ctx, f"Cleaned duplicates and synced {len(synced)} global commands successfully!", ephemeral=True)

    @admin.command(name="wipe", description="Wipe global database user profiles and leaderboards (Bot Admin only)")
    async def wipe(self, ctx: commands.Context) -> None:
        import config
        if ctx.author.id not in config.ADMIN_IDS:
            await send_hybrid_response(ctx, f"{get_emoji('cross')} **Unauthorized:** Only bot developers can run this command.", ephemeral=True)
            return

        view = WipeConfirmationView(self.bot, ctx.author.id)
        await send_hybrid_response(
            ctx,
            f"{get_emoji('warning')} **CAUTION:** You are about to wipe ALL global database profiles, statistics, achievements, character statistics, inventory, and leaderboards! This action cannot be undone.\n"
            "An export backup will be automatically generated. Click **Confirm Wipe** to proceed.",
            view=view,
            ephemeral=True
        )
        await view.wait()
        if not view.confirmed:
            return

        import json
        import os
        from datetime import datetime

        database = getattr(self.bot, "db", None)
        if database is None:
            if view.interaction:
                await view.interaction.followup.send(f"{get_emoji('cross')} Database connection is not available.", ephemeral=True)
            else:
                await send_hybrid_response(ctx, f"{get_emoji('cross')} Database connection is not available.", ephemeral=True)
            return

        global_db = database.global_db
        collections_to_wipe = [
            "players",
            "statistics",
            "character_statistics",
            "leaderboards",
            "unlocked_achievements",
            "inventory",
            "unlocked_characters"
        ]

        backup_data = {}
        counts = {}
        for coll_name in collections_to_wipe:
            cursor = global_db[coll_name].find()
            docs = []
            async for doc in cursor:
                def clean_doc(d):
                    cleaned = {}
                    for k, v in d.items():
                        if k == "_id":
                            cleaned[k] = str(v)
                        elif isinstance(v, datetime):
                            cleaned[k] = v.isoformat()
                        elif isinstance(v, dict):
                            cleaned[k] = clean_doc(v)
                        elif isinstance(v, list):
                            cleaned[k] = [clean_doc(x) if isinstance(x, dict) else x for x in v]
                        else:
                            cleaned[k] = v
                    return cleaned
                docs.append(clean_doc(doc))
            backup_data[coll_name] = docs
            counts[coll_name] = len(docs)

        os.makedirs("backups", exist_ok=True)
        backup_filename = f"backups/wipe_backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
        with open(backup_filename, "w", encoding="utf-8") as f:
            json.dump(backup_data, f, indent=4)

        for coll_name in collections_to_wipe:
            await global_db[coll_name].delete_many({})

        summary_lines = [f"• `{coll}`: **{count}** records cleared" for coll, count in counts.items()]
        summary_str = "\n".join(summary_lines)

        if view.interaction:
            await view.interaction.followup.send(
                f"{get_emoji('check')} **Database Wipe Completed Successfully!**\n"
                f"Backup written to: `{backup_filename}`\n\n"
                f"**Wiped Collections Summary:**\n{summary_str}",
                ephemeral=True
            )
        else:
            await send_hybrid_response(
                ctx,
                f"{get_emoji('check')} **Database Wipe Completed Successfully!**\n"
                f"Backup written to: `{backup_filename}`\n\n"
                f"**Wiped Collections Summary:**\n{summary_str}",
                ephemeral=True
            )

    @commands.hybrid_command(name="reset", description="Reset the bot in the server, cleaning up game channels and status")
    async def reset(self, ctx: commands.Context) -> None:
        import config
        has_perm = ctx.author.id in config.ADMIN_IDS or (ctx.guild and ctx.author.guild_permissions.manage_guild)
        if not has_perm:
            await send_hybrid_response(ctx, f"{get_emoji('cross')} **Unauthorized:** You do not have permission to use this command.", ephemeral=True)
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
            f"{get_emoji('check')} **Server Reset Completed!**\n"
            f"• Removed active session: {'Yes' if removed_game else 'None found'}\n"
            f"• Deleted categories: **{deleted_categories}**\n"
            f"• Deleted channels: **{deleted_channels}**\n"
            f"• Bot status refreshed.",
            ephemeral=True
        )

    @commands.hybrid_command(name="devrestart", aliases=["dev_restart"], description="Pull latest code from git and restart the bot (Developer only)")
    async def devrestart(self, ctx: commands.Context) -> None:
        import config
        if ctx.author.id not in config.ADMIN_IDS:
            await send_hybrid_response(ctx, f"{get_emoji('cross')} **Unauthorized:** Only bot developers can run this command.", ephemeral=True)
            return

        # Defer the response since git pull and cleanup can take a second
        await ctx.defer(ephemeral=False)

        import subprocess
        try:
            result = subprocess.run(["git", "pull"], capture_output=True, text=True, check=True)
            git_output = result.stdout + result.stderr
        except Exception as e:
            git_output = f"Git pull failed:\n{e}"

        # Send git output and starting indicator
        await ctx.send(f"{get_emoji('package')} **Git Pull Output:**\n```\n{git_output[:1800]}\n```\n{get_emoji('refresh')} **Restarting bot process...** Please wait.")

        import os
        import sys

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

    @commands.hybrid_command(name="push", description="Stage all, commit, push changes, and print git output (Developer only)")
    @discord.app_commands.describe(message="The commit message")
    async def push(self, ctx: commands.Context, message: str) -> None:
        import config
        if ctx.author.id not in config.ADMIN_IDS:
            await send_hybrid_response(ctx, f"{get_emoji('cross')} **Unauthorized:** Only bot developers can run this command.", ephemeral=True)
            return

        await ctx.defer(ephemeral=False)

        import subprocess
        outputs = []
        
        # 1. git add .
        try:
            subprocess.run(["git", "add", "."], capture_output=True, text=True, check=True)
            outputs.append(f"{get_emoji('check')} Git Add: Success")
        except Exception as e:
            outputs.append(f"{get_emoji('cross')} Git Add Failed:\n{e}")
            await ctx.send("\n".join(outputs))
            return

        # 2. git commit -m "..."
        try:
            res_commit = subprocess.run(["git", "commit", "-m", message], capture_output=True, text=True, check=True)
            outputs.append(f"{get_emoji('check')} Git Commit:\n{res_commit.stdout or res_commit.stderr}")
        except Exception as e:
            err_str = str(e)
            if hasattr(e, "stdout") and e.stdout:
                err_str += f"\nstdout: {e.stdout}"
            if hasattr(e, "stderr") and e.stderr:
                err_str += f"\nstderr: {e.stderr}"
            outputs.append(f"{get_emoji('warning')} Git Commit Warning/Failure:\n{err_str}")
            if "nothing to commit" in err_str.lower() or "no changes added to commit" in err_str.lower():
                pass
            else:
                await ctx.send("\n".join(outputs))
                return

        # 3. git push
        try:
            res_push = subprocess.run(["git", "push"], capture_output=True, text=True, check=True)
            outputs.append(f"{get_emoji('check')} Git Push:\n{res_push.stdout or res_push.stderr}")
        except Exception as e:
            err_str = str(e)
            if hasattr(e, "stdout") and e.stdout:
                err_str += f"\nstdout: {e.stdout}"
            if hasattr(e, "stderr") and e.stderr:
                err_str += f"\nstderr: {e.stderr}"
            outputs.append(f"{get_emoji('cross')} Git Push Failed:\n{err_str}")

        full_output = "\n\n".join(outputs)
        await ctx.send(f"{get_emoji('package')} **Git Push Summary:**\n```\n{full_output[:1800]}\n```")


class WipeConfirmationView(discord.ui.View):
    def __init__(self, bot: commands.Bot, author_id: int) -> None:
        super().__init__(timeout=30)
        self.bot = bot
        self.author_id = author_id
        self.confirmed = False
        self.interaction: discord.Interaction | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(f"{get_emoji('cross')} You are not authorized to interact with this menu.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirm Wipe", style=discord.ButtonStyle.danger, emoji=get_emoji("warning"))
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.confirmed = True
        self.interaction = interaction
        await interaction.response.defer(ephemeral=True)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.confirmed = False
        self.interaction = interaction
        await interaction.response.send_message(f"{get_emoji('cross')} Wipe cancelled.", ephemeral=True)
        self.stop()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
