from __future__ import annotations

import discord
from discord.ext import commands
from config import get_emoji

import roles
from roles.balance import SPAWN_ONLY_ROLES
from utils.helpers import send_hybrid_response


def _role_faction_group(role_key: str) -> str:
    faction = roles.ROLES_METADATA.get(role_key, {}).get("faction", "Unknown")
    return "town" if faction in ("Hero", "Town", "Protagonist") else "mafia_neutral"


class _RoleSelect(discord.ui.Select):
    def __init__(self, view_ref: "RoleToggleView", role_keys: list[str], placeholder: str) -> None:
        self.view_ref = view_ref
        options = []
        for rkey in sorted(role_keys, key=lambda k: roles.ROLES_METADATA.get(k, {}).get("name", k)):
            meta = roles.ROLES_METADATA.get(rkey, {})
            name = meta.get("name", rkey.replace("_", " ").title())
            emoji = get_emoji(rkey)
            select_emoji = None
            if emoji:
                if emoji.startswith("<"):
                    try:
                        select_emoji = discord.PartialEmoji.from_str(emoji)
                    except Exception:
                        pass
                else:
                    select_emoji = emoji
            options.append(discord.SelectOption(label=name, value=rkey, emoji=select_emoji))

        super().__init__(placeholder=placeholder, min_values=1, max_values=len(options), options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        database = getattr(self.view_ref.bot, "db", None)
        if database is None:
            await interaction.response.send_message(f"{get_emoji('cross')} Database connection is not available.", ephemeral=True)
            return

        changed = []
        for role_key in self.values:
            await database.set_role_disabled(self.view_ref.guild_id, role_key, self.view_ref.disable)
            changed.append(roles.ROLES_METADATA.get(role_key, {}).get("name", role_key))

        verb = "Disabled" if self.view_ref.disable else "Enabled"
        await interaction.response.send_message(
            f"{get_emoji('check')} **{verb}:** " + ", ".join(f"`{n}`" for n in changed),
            ephemeral=True,
        )


from ui import MafiosoLayoutView


class RoleToggleView(MafiosoLayoutView):
    """Lets an admin pick one or more roles to disable/enable for this server."""

    def __init__(self, bot: commands.Bot, guild_id: int, author_id: int, disable: bool, eligible_roles: list[str]) -> None:
        super().__init__(timeout=120)

        self.bot = bot
        self.guild_id = guild_id
        self.author_id = author_id
        self.disable = disable  # True = disabling roles, False = re-enabling roles

        town_roles = [rk for rk in eligible_roles if _role_faction_group(rk) == "town"]
        other_roles = [rk for rk in eligible_roles if _role_faction_group(rk) == "mafia_neutral"]

        verb = "disable" if disable else "enable"
        if town_roles:
            self.add_item(_RoleSelect(self, town_roles, f"Select Town character(s) to {verb}..."))
        if other_roles:
            self.add_item(_RoleSelect(self, other_roles, f"Select Mafia/Neutral character(s) to {verb}..."))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                f"{get_emoji('cross')} You are not authorized to interact with this menu.", ephemeral=True
            )
            return False
        return True


class _GlobalRoleSelect(discord.ui.Select):
    def __init__(self, view_ref: "GlobalRoleToggleView", role_keys: list[str], placeholder: str) -> None:
        self.view_ref = view_ref
        options = []
        for rkey in sorted(role_keys, key=lambda k: roles.ROLES_METADATA.get(k, {}).get("name", k)):
            meta = roles.ROLES_METADATA.get(rkey, {})
            name = meta.get("name", rkey.replace("_", " ").title())
            emoji = get_emoji(rkey)
            select_emoji = None
            if emoji:
                if emoji.startswith("<"):
                    try:
                        select_emoji = discord.PartialEmoji.from_str(emoji)
                    except Exception:
                        pass
                else:
                    select_emoji = emoji
            options.append(discord.SelectOption(label=name, value=rkey, emoji=select_emoji))

        super().__init__(placeholder=placeholder, min_values=1, max_values=len(options), options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        database = getattr(self.view_ref.bot, "db", None)
        if database is None:
            await interaction.response.send_message(f"{get_emoji('cross')} Database connection is not available.", ephemeral=True)
            return

        changed = []
        for role_key in self.values:
            await database.set_global_role_disabled(role_key, self.view_ref.disable)
            changed.append(roles.ROLES_METADATA.get(role_key, {}).get("name", role_key))

        verb = "Globally Disabled" if self.view_ref.disable else "Globally Enabled"
        await interaction.response.send_message(
            f"{get_emoji('check')} **{verb}:** " + ", ".join(f"`{n}`" for n in changed),
            ephemeral=True,
        )


class GlobalRoleToggleView(MafiosoLayoutView):
    """Lets a bot developer pick one or more roles to disable/enable globally across all servers."""

    def __init__(self, bot: commands.Bot, author_id: int, disable: bool, eligible_roles: list[str]) -> None:
        super().__init__(timeout=120)

        self.bot = bot
        self.author_id = author_id
        self.disable = disable

        town_roles = [rk for rk in eligible_roles if _role_faction_group(rk) == "town"]
        other_roles = [rk for rk in eligible_roles if _role_faction_group(rk) == "mafia_neutral"]

        verb = "globally disable" if disable else "globally enable"
        if town_roles:
            self.add_item(_GlobalRoleSelect(self, town_roles, f"Select Town character(s) to {verb}..."))
        if other_roles:
            self.add_item(_GlobalRoleSelect(self, other_roles, f"Select Mafia/Neutral character(s) to {verb}..."))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                f"{get_emoji('cross')} You are not authorized to interact with this menu.", ephemeral=True
            )
            return False
        return True


class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.hybrid_group(name="admin", description="Administrative controls for Mafioso")
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

    @commands.hybrid_command()
    async def ping(self, ctx:commands.Context):
        return await send_hybrid_response(ctx, "pong")
        
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
            name = channel.name.lower()
            if name == "mafia" or name.startswith("mafia-"):
                try:
                    await channel.delete(reason="Mafia bot reset command.")
                    deleted_channels += 1
                except Exception:
                    pass

        # 3. Refresh presence/status
        try:
            await self.bot.change_presence(activity=discord.Game(name="Mafioso"), status=discord.Status.online)
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

    @commands.hybrid_command(name="roledisable", description="Disable one or more characters from appearing in future games (Admin only)")
    async def roledisable(self, ctx: commands.Context) -> None:
        import config
        has_perm = ctx.author.id in config.ADMIN_IDS or (ctx.guild and ctx.author.guild_permissions.manage_guild)
        if not has_perm:
            await send_hybrid_response(ctx, f"{get_emoji('cross')} **Unauthorized:** You do not have permission to use this command.", ephemeral=True)
            return
        if ctx.guild is None:
            await send_hybrid_response(ctx, "This command must be used in a server.", ephemeral=True)
            return

        database = getattr(self.bot, "db", None)
        if database is None:
            await send_hybrid_response(ctx, f"{get_emoji('cross')} Database connection is not available.", ephemeral=True)
            return

        disabled_now = set(await database.get_disabled_roles(ctx.guild.id))
        all_roles = [rk for rk in roles.ROLES_METADATA if rk not in SPAWN_ONLY_ROLES]
        enabled_roles = [rk for rk in all_roles if rk not in disabled_now]

        if not enabled_roles:
            await send_hybrid_response(ctx, f"{get_emoji('warning')} Every character is already disabled on this server.", ephemeral=True)
            return

        view = RoleToggleView(self.bot, ctx.guild.id, ctx.author.id, disable=True, eligible_roles=enabled_roles)
        await send_hybrid_response(
            ctx,
            f"{get_emoji('roster')} **Disable Characters**\nPick any character(s) below to remove them from the random role pool for this server. This does not affect games already in progress.",
            view=view,
            ephemeral=True,
        )

    @commands.hybrid_command(name="roleenable", description="Re-enable one or more previously disabled characters (Admin only)")
    async def roleenable(self, ctx: commands.Context) -> None:
        import config
        has_perm = ctx.author.id in config.ADMIN_IDS or (ctx.guild and ctx.author.guild_permissions.manage_guild)
        if not has_perm:
            await send_hybrid_response(ctx, f"{get_emoji('cross')} **Unauthorized:** You do not have permission to use this command.", ephemeral=True)
            return
        if ctx.guild is None:
            await send_hybrid_response(ctx, "This command must be used in a server.", ephemeral=True)
            return

        database = getattr(self.bot, "db", None)
        if database is None:
            await send_hybrid_response(ctx, f"{get_emoji('cross')} Database connection is not available.", ephemeral=True)
            return

        disabled_roles = await database.get_disabled_roles(ctx.guild.id)
        disabled_roles = [rk for rk in disabled_roles if rk in roles.ROLES_METADATA]

        if not disabled_roles:
            await send_hybrid_response(ctx, f"{get_emoji('warning')} No characters are currently disabled on this server.", ephemeral=True)
            return

        view = RoleToggleView(self.bot, ctx.guild.id, ctx.author.id, disable=False, eligible_roles=disabled_roles)
        await send_hybrid_response(
            ctx,
            f"{get_emoji('roster')} **Enable Characters**\nPick any character(s) below to add them back into the random role pool for this server.",
            view=view,
            ephemeral=True,
        )

    @commands.hybrid_command(name="globalroledisable", description="Globally disable a character across all servers (Developer only)")
    async def globalroledisable(self, ctx: commands.Context) -> None:
        import config
        if ctx.author.id not in config.ADMIN_IDS:
            await send_hybrid_response(ctx, f"{get_emoji('cross')} **Unauthorized:** Only bot developers can run this command.", ephemeral=True)
            return

        database = getattr(self.bot, "db", None)
        if database is None:
            await send_hybrid_response(ctx, f"{get_emoji('cross')} Database connection is not available.", ephemeral=True)
            return

        global_disabled = set(await database.get_global_disabled_roles())
        all_roles = [rk for rk in roles.ROLES_METADATA if rk not in SPAWN_ONLY_ROLES]
        eligible_roles = [rk for rk in all_roles if rk not in global_disabled]

        if not eligible_roles:
            await send_hybrid_response(ctx, f"{get_emoji('warning')} Every character is already globally disabled.", ephemeral=True)
            return

        view = GlobalRoleToggleView(self.bot, ctx.author.id, disable=True, eligible_roles=eligible_roles)
        await send_hybrid_response(
            ctx,
            f"{get_emoji('roster')} **Globally Disable Characters**\nPick any character(s) below to remove them from the random role pool across all servers.",
            view=view,
            ephemeral=True,
        )

    @commands.hybrid_command(name="globalroleenable", description="Globally re-enable a previously disabled character (Developer only)")
    async def globalroleenable(self, ctx: commands.Context) -> None:
        import config
        if ctx.author.id not in config.ADMIN_IDS:
            await send_hybrid_response(ctx, f"{get_emoji('cross')} **Unauthorized:** Only bot developers can run this command.", ephemeral=True)
            return

        database = getattr(self.bot, "db", None)
        if database is None:
            await send_hybrid_response(ctx, f"{get_emoji('cross')} Database connection is not available.", ephemeral=True)
            return

        global_disabled = await database.get_global_disabled_roles()
        disabled_roles = [rk for rk in global_disabled if rk in roles.ROLES_METADATA]

        if not disabled_roles:
            await send_hybrid_response(ctx, f"{get_emoji('warning')} No characters are currently globally disabled.", ephemeral=True)
            return

        view = GlobalRoleToggleView(self.bot, ctx.author.id, disable=False, eligible_roles=disabled_roles)
        await send_hybrid_response(
            ctx,
            f"{get_emoji('roster')} **Globally Enable Characters**\nPick any character(s) below to add them back into the random role pool across all servers.",
            view=view,
            ephemeral=True,
        )

    @commands.hybrid_command(name="resume", description="Restore a crashed or frozen game (Admin/Host only)")
    async def resume(self, ctx: commands.Context, game_id: str | None = None) -> None:
        """
        Restore a crashed/frozen game or recover after bot restart.
        Authorization: Bot admins, server admins, or lobby host.
        """
        import config

        # Check authorization: bot admin OR server admin
        has_admin_perm = ctx.author.id in config.ADMIN_IDS or (ctx.guild and ctx.author.guild_permissions.administrator)

        if not has_admin_perm:
            await send_hybrid_response(ctx, f"{get_emoji('cross')} **Unauthorized:** Only bot admins or server admins can use this command.", ephemeral=True)
            return

        if ctx.guild is None:
            await send_hybrid_response(ctx, "This command must be used in a server.", ephemeral=True)
            return

        await ctx.defer(ephemeral=False)

        game_manager = getattr(self.bot, "game_manager", None)
        game_engine = getattr(self.bot, "game_engine", None)
        database = getattr(self.bot, "db", None)

        if not all([game_manager, game_engine, database]):
            await send_hybrid_response(ctx, f"{get_emoji('cross')} Bot systems not fully initialized.", ephemeral=True)
            return

        # Find the game to resume
        target_game_id = game_id
        if not target_game_id:
            # Auto-detect: find active game in this guild
            game_handle = await game_manager.get_game_by_guild(ctx.guild.id)
            if game_handle:
                target_game_id = game_handle.game_id
            else:
                # Check database for active game
                active_doc = await database.get_active_game_by_guild(ctx.guild.id)
                if active_doc and active_doc.get("active_state"):
                    target_game_id = active_doc["active_state"].get("game_handle", {}).get("game_id")

        if not target_game_id:
            await send_hybrid_response(
                ctx,
                f"{get_emoji('warning')} No active or frozen game found in this server.\n"
                f"Use `/resume <game_id>` if you know the specific game ID to restore.",
                ephemeral=True
            )
            return

        # Check if session exists in memory (frozen but not crashed)
        session = game_engine._sessions.get(target_game_id)

        if session:
            # Session exists in memory - game is frozen, not crashed
            # Keep existing session and tasks, just notify
            await send_hybrid_response(
                ctx,
                f"{get_emoji('check')} **Game Session Found in Memory**\n"
                f"Game ID: `{target_game_id}`\n"
                f"Phase: `{session.phase.value}`\n"
                f"Alive Players: `{sum(1 for p in session.players.values() if p.alive)}/{len(session.players)}`\n\n"
                f"Session is still active. If the game is truly frozen, consider:\n"
                f"• Waiting a few more seconds for automatic phase transition\n"
                f"• Using `/admin reset` to force-cancel and start fresh\n"
                f"• Checking if players need to submit actions",
                ephemeral=False
            )
        else:
            # Session not in memory - need to restore from database
            active_doc = await database.get_active_game_by_guild(ctx.guild.id)

            if not active_doc or not active_doc.get("active_state"):
                await send_hybrid_response(
                    ctx,
                    f"{get_emoji('cross')} No saved game state found in database for game `{target_game_id}`.\n"
                    f"The game may have ended normally or was never saved.",
                    ephemeral=True
                )
                return

            # Reconstruct session from database (hybrid approach - memory efficient)
            try:
                await game_engine.restore_session_from_db(target_game_id, active_doc["active_state"])

                restored_session = game_engine._sessions.get(target_game_id)
                if restored_session:
                    await send_hybrid_response(
                        ctx,
                        f"{get_emoji('check')} **Game Restored Successfully!**\n"
                        f"Game ID: `{target_game_id}`\n"
                        f"Phase: `{restored_session.phase.value}`\n"
                        f"Alive Players: `{sum(1 for p in restored_session.players.values() if p.alive)}/{len(restored_session.players)}`\n\n"
                        f"The game has been restored from the last saved state. Phase timers have been reset.\n"
                        f"Players can now continue submitting actions.",
                        ephemeral=False
                    )
                else:
                    raise RuntimeError("Session restoration completed but session not found in memory")

            except Exception as e:
                await send_hybrid_response(
                    ctx,
                    f"{get_emoji('cross')} **Failed to restore game:** {str(e)}\n"
                    f"The saved state may be corrupted. Consider using `/admin reset` to clean up.",
                    ephemeral=True
                )
                import logging
                logging.exception(f"Failed to restore game {target_game_id}")

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
        await ctx.send(f"**Git Pull Output:**\n```\n{git_output[:1800]}\n```\n**Yeah ok sybau and wait like a good boy.**")

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





class WipeConfirmationView(MafiosoLayoutView):
    def __init__(self, bot: commands.Bot, author_id: int) -> None:
        super().__init__(timeout=60)

        self.bot = bot
        self.author_id = author_id
        self.confirmed = False
        self.interaction: discord.Interaction | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(f"{get_emoji('cross')} You are not authorized to interact with this menu.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirm Wipe", style=discord.ButtonStyle.danger, custom_id="admin_wipe_confirm")
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.confirmed = True
        self.interaction = interaction
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, custom_id="admin_wipe_cancel")
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.confirmed = False
        self.interaction = interaction
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=build_v2_layout(description=f"{get_emoji('cross')} **Database wipe cancelled.**", footer_text=""))
        self.stop()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))

