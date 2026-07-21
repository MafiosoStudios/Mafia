from __future__ import annotations

import discord
from discord.ext import commands

from config import BotConfig, get_emoji
from utils.embeds import build_status_embed
from utils.helpers import send_hybrid_response
from views.lobby_view import LobbyView


class LobbyCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.hybrid_command(name="lobby", description="View the current lobby status and roster")
    async def lobby(self, ctx: commands.Context) -> None:
        lobby_manager = getattr(self.bot, "lobby_manager", None)
        if lobby_manager is None:
            await send_hybrid_response(ctx, "Lobby system is not ready yet.", ephemeral=True)
            return
        
        guild_id = ctx.guild.id if ctx.guild is not None else 0
        lobby = await lobby_manager.get_lobby(guild_id)
        if lobby is None:
            await send_hybrid_response(
                ctx,
                "No active lobby found. Type `/join` to create and join one!",
                ephemeral=True,
            )
            return

        view = LobbyView(self.bot, lobby)
        message = await send_hybrid_response(ctx, view=view)
        if message is not None:
            await lobby_manager.bind_lobby_message(guild_id, message)

    @commands.hybrid_command(name="join", aliases=["lobby_join", "lobby_create"], description="Join or create the game lobby")
    async def join(self, ctx: commands.Context) -> None:
        config: BotConfig = self.bot.config  # type: ignore[assignment]
        lobby_manager = getattr(self.bot, "lobby_manager", None)
        if lobby_manager is None:
            await send_hybrid_response(ctx, "Lobby system is not ready yet.", ephemeral=True)
            return

        guild_id = ctx.guild.id if ctx.guild is not None else 0
        channel_id = ctx.channel.id if ctx.channel is not None else 0

        lobby = await lobby_manager.get_lobby(guild_id)
        if lobby is None:
            # Auto-create lobby
            lobby = await lobby_manager.create_lobby(
                guild_id=guild_id,
                channel_id=channel_id,
                host_id=ctx.author.id,
                min_players=config.min_players,
                max_players=config.max_players,
            )
            view = LobbyView(self.bot, lobby)
            message = await send_hybrid_response(ctx, view=view)
            if message is not None:
                await lobby_manager.bind_lobby_message(guild_id, message)
            await send_hybrid_response(ctx, f"{get_emoji('check')} Lobby created! You joined the lobby.", ephemeral=True)
        else:
            # Join existing lobby
            try:
                _, status_msg = await lobby_manager.join_lobby(
                    guild_id=guild_id,
                    user_id=ctx.author.id,
                )
            except Exception as exc:
                await send_hybrid_response(ctx, str(exc), ephemeral=True)
                return
            await send_hybrid_response(ctx, f"{get_emoji('check')} {status_msg}", ephemeral=True)

    @commands.hybrid_command(name="leave", aliases=["lobby_leave"], description="Leave the active lobby")
    async def leave(self, ctx: commands.Context) -> None:
        lobby_manager = getattr(self.bot, "lobby_manager", None)
        if lobby_manager is None:
            await send_hybrid_response(ctx, "Lobby system is not ready yet.", ephemeral=True)
            return
        _, status_msg = await lobby_manager.leave_lobby(guild_id=ctx.guild.id if ctx.guild is not None else 0, user_id=ctx.author.id)
        await send_hybrid_response(ctx, status_msg, ephemeral=True)

    @commands.hybrid_command(name="start", aliases=["lobby_start"], description="Start the game match")
    async def start(self, ctx: commands.Context) -> None:
        lobby_manager = getattr(self.bot, "lobby_manager", None)
        if lobby_manager is None:
            await send_hybrid_response(ctx, "Lobby system is not ready yet.", ephemeral=True)
            return
        try:
            member = ctx.author if isinstance(ctx.author, discord.Member) else None
            if member is None:
                await send_hybrid_response(ctx, "This command must be used in a server.", ephemeral=True)
                return
            await lobby_manager.start_lobby(ctx.guild.id if ctx.guild is not None else 0, member)
        except Exception as exc:
            await send_hybrid_response(ctx, str(exc), ephemeral=True)
            return
        await send_hybrid_response(ctx, "The game is beginning.", ephemeral=True)

    @commands.hybrid_command(name="clear", aliases=["lobby_clear", "disband"], description="Clear and disband the current game lobby (Leader/Admin only)")
    async def clear(self, ctx: commands.Context) -> None:
        lobby_manager = getattr(self.bot, "lobby_manager", None)
        if lobby_manager is None:
            await send_hybrid_response(ctx, "Lobby system is not ready yet.", ephemeral=True)
            return

        member = ctx.author if isinstance(ctx.author, discord.Member) else None
        if member is None:
            await send_hybrid_response(ctx, "This command must be used in a server.", ephemeral=True)
            return

        try:
            guild_id = ctx.guild.id if ctx.guild is not None else 0
            await lobby_manager.clear_lobby(guild_id, member)
            await send_hybrid_response(ctx, f"🧹 **Lobby Cleared:** The game lobby has been cleared.")
        except Exception as exc:
            await send_hybrid_response(ctx, f"{get_emoji('cross')} {exc}", ephemeral=True)

    @commands.hybrid_command(name="gamemode", description="Change the current lobby's gamemode (chaos/custom)")
    @discord.app_commands.describe(mode="Choose either 'chaos' or 'custom'")
    async def gamemode(self, ctx: commands.Context, mode: str) -> None:
        if ctx.guild is None:
            await send_hybrid_response(ctx, "This command must be used in a server.", ephemeral=True)
            return

        lobby_manager = getattr(self.bot, "lobby_manager", None)
        if lobby_manager is None:
            await send_hybrid_response(ctx, "Lobby system is not ready yet.", ephemeral=True)
            return

        lobby = await lobby_manager.get_lobby(ctx.guild.id)
        if lobby is None:
            await send_hybrid_response(ctx, f"{get_emoji('cross')} **No active lobby** to configure.", ephemeral=True)
            return

        import config
        is_bot_admin = ctx.author.id in config.ADMIN_IDS
        is_server_admin = ctx.author.guild_permissions.administrator
        is_lobby_leader = ctx.author.id == lobby.leader_id

        if not (is_bot_admin or is_server_admin or is_lobby_leader):
            await send_hybrid_response(
                ctx, 
                f"{get_emoji('cross')} *\"Know your place, weakling. Only the lobby leader or an administrator holds the power to reshape this reality.\"*", 
                ephemeral=True
            )
            return

        mode_clean = mode.lower().strip()
        if mode_clean not in ("chaos", "custom"):
            await send_hybrid_response(ctx, f"{get_emoji('cross')} **Invalid Gamemode:** Choose either `chaos` or `custom`.", ephemeral=True)
            return

        lobby.gamemode = mode_clean
        warning = ""
        if mode_clean == "custom":
            active_list = lobby_manager._active_custom_role_lists.get(ctx.guild.id)
            if not active_list:
                warning = f"\n{get_emoji('warning')} *Note: No custom role list is currently loaded. Use `/customrolelist load <name>` to load one, or the bot will fallback to chaos behavior.*"

        await lobby_manager.refresh_lobby_message(ctx.guild.id)
        await send_hybrid_response(ctx, f"🔮 **Reality has shifted.** Game mode set to **{mode_clean.upper()}** for this lobby.{warning}")

    @commands.hybrid_command(name="kick", description="Kick a player from the pre-game lobby")
    @discord.app_commands.describe(player="The player to kick")
    async def kick_player(self, ctx: commands.Context, player: discord.Member) -> None:
        if ctx.guild is None:
            await send_hybrid_response(ctx, "This command must be used in a server.", ephemeral=True)
            return

        lobby_manager = getattr(self.bot, "lobby_manager", None)
        if lobby_manager is None:
            await send_hybrid_response(ctx, "Lobby system is not ready yet.", ephemeral=True)
            return

        lobby = await lobby_manager.get_lobby(ctx.guild.id)
        if lobby is None:
            await send_hybrid_response(ctx, f"{get_emoji('cross')} **No active lobby** found to kick players from.", ephemeral=True)
            return

        import config
        is_bot_admin = ctx.author.id in config.ADMIN_IDS
        is_server_admin = ctx.author.guild_permissions.administrator or ctx.author.guild_permissions.kick_members
        is_lobby_leader = ctx.author.id == lobby.leader_id

        if not (is_bot_admin or is_server_admin or is_lobby_leader):
            await send_hybrid_response(
                ctx, 
                f"{get_emoji('cross')} *\"You lack the authority to banish anyone from this circle.\"*", 
                ephemeral=True
            )
            return

        if player.id not in lobby.players:
            await send_hybrid_response(ctx, f"{get_emoji('cross')} **{player.display_name}** is not in the lobby roster.", ephemeral=True)
            return

        if player.id == lobby.leader_id:
            await send_hybrid_response(ctx, f"{get_emoji('cross')} You cannot kick the lobby leader.", ephemeral=True)
            return

        await lobby_manager.leave_lobby(ctx.guild.id, player.id)
        await send_hybrid_response(ctx, f"🚪 **{player.display_name}** was banished from the lobby.")

    @commands.hybrid_group(name="customrolelist", description="Manage custom role lists for the guild")
    async def customrolelist(self, ctx: commands.Context) -> None:
        if ctx.invoked_subcommand is None:
            await send_hybrid_response(ctx, "Try `/customrolelist list` or `/customrolelist create`.", ephemeral=True)

    @customrolelist.command(name="create", description="Start editing a new custom role list draft")
    @discord.app_commands.describe(name="Name of the custom role list")
    async def create_list(self, ctx: commands.Context, name: str) -> None:
        if ctx.guild is None:
            await send_hybrid_response(ctx, "This command must be used in a server.", ephemeral=True)
            return

        lobby_manager = getattr(self.bot, "lobby_manager", None)
        if lobby_manager is None:
            await send_hybrid_response(ctx, "Lobby system is not ready yet.", ephemeral=True)
            return

        lobby = await lobby_manager.get_lobby(ctx.guild.id)
        import config
        is_bot_admin = ctx.author.id in config.ADMIN_IDS
        is_server_admin = ctx.author.guild_permissions.administrator
        is_lobby_leader = lobby is not None and ctx.author.id == lobby.leader_id

        if not (is_bot_admin or is_server_admin or is_lobby_leader):
            await send_hybrid_response(ctx, f"{get_emoji('cross')} *\"Only the lobby leader or an administrator can draft custom rules.\"*", ephemeral=True)
            return

        name_clean = name.strip()
        if not hasattr(lobby_manager, "_custom_role_drafts"):
            lobby_manager._custom_role_drafts = {}
        lobby_manager._custom_role_drafts[ctx.guild.id] = {"name": name_clean, "roles": []}
        await send_hybrid_response(ctx, f"📝 **Draft list created:** '{name_clean}'. Use `/customrolelist add` to add roles to this draft.")

    @customrolelist.command(name="add", description="Add a role to the active custom role list draft")
    @discord.app_commands.describe(role="The role to add")
    async def add_role(self, ctx: commands.Context, role: str) -> None:
        if ctx.guild is None:
            await send_hybrid_response(ctx, "This command must be used in a server.", ephemeral=True)
            return

        lobby_manager = getattr(self.bot, "lobby_manager", None)
        if lobby_manager is None:
            await send_hybrid_response(ctx, "Lobby system is not ready yet.", ephemeral=True)
            return

        lobby = await lobby_manager.get_lobby(ctx.guild.id)
        import config
        is_bot_admin = ctx.author.id in config.ADMIN_IDS
        is_server_admin = ctx.author.guild_permissions.administrator
        is_lobby_leader = lobby is not None and ctx.author.id == lobby.leader_id

        if not (is_bot_admin or is_server_admin or is_lobby_leader):
            await send_hybrid_response(ctx, f"{get_emoji('cross')} *\"Only the lobby leader or an administrator can draft custom rules.\"*", ephemeral=True)
            return

        if not hasattr(lobby_manager, "_custom_role_drafts"):
            lobby_manager._custom_role_drafts = {}

        draft = lobby_manager._custom_role_drafts.get(ctx.guild.id)
        if not draft:
            await send_hybrid_response(ctx, f"{get_emoji('cross')} No active draft. Start one first with `/customrolelist create <name>`.", ephemeral=True)
            return

        import roles
        role_key = role.lower().strip()
        if role_key not in roles.ROLES_METADATA:
            found_key = None
            for rk, rmeta in roles.ROLES_METADATA.items():
                if rmeta.get("name", "").lower() == role_key:
                    found_key = rk
                    break
            if found_key:
                role_key = found_key
            else:
                await send_hybrid_response(ctx, f"{get_emoji('cross')} **Invalid Role:** '{role}' does not exist in the role registry.", ephemeral=True)
                return

        role_name = roles.ROLES_METADATA[role_key].get("name", role_key.replace("_", " ").title())
        if role_key in draft["roles"]:
            await send_hybrid_response(ctx, f"{get_emoji('warning')} **{role_name}** is already in the draft list '{draft['name']}'.", ephemeral=True)
            return

        draft["roles"].append(role_key)
        await send_hybrid_response(ctx, f"{get_emoji('join')} Added **{role_name}** to draft list '{draft['name']}' (Total roles: **{len(draft['roles'])}**).")

    @customrolelist.command(name="remove", description="Remove a role from the active custom role list draft")
    @discord.app_commands.describe(role="The role to remove")
    async def remove_role(self, ctx: commands.Context, role: str) -> None:
        if ctx.guild is None:
            await send_hybrid_response(ctx, "This command must be used in a server.", ephemeral=True)
            return

        lobby_manager = getattr(self.bot, "lobby_manager", None)
        if lobby_manager is None:
            await send_hybrid_response(ctx, "Lobby system is not ready yet.", ephemeral=True)
            return

        lobby = await lobby_manager.get_lobby(ctx.guild.id)
        import config
        is_bot_admin = ctx.author.id in config.ADMIN_IDS
        is_server_admin = ctx.author.guild_permissions.administrator
        is_lobby_leader = lobby is not None and ctx.author.id == lobby.leader_id

        if not (is_bot_admin or is_server_admin or is_lobby_leader):
            await send_hybrid_response(ctx, f"{get_emoji('cross')} *\"Only the lobby leader or an administrator can draft custom rules.\"*", ephemeral=True)
            return

        if not hasattr(lobby_manager, "_custom_role_drafts"):
            lobby_manager._custom_role_drafts = {}

        draft = lobby_manager._custom_role_drafts.get(ctx.guild.id)
        if not draft:
            await send_hybrid_response(ctx, f"{get_emoji('cross')} No active draft. Start one first with `/customrolelist create <name>`.", ephemeral=True)
            return

        import roles
        role_key = role.lower().strip()
        if role_key not in draft["roles"]:
            found_key = None
            for rk in draft["roles"]:
                rmeta = roles.ROLES_METADATA.get(rk, {})
                if rmeta.get("name", "").lower() == role_key:
                    found_key = rk
                    break
            if found_key:
                role_key = found_key
            else:
                await send_hybrid_response(ctx, f"{get_emoji('cross')} **Role not in list:** '{role}' is not in draft list '{draft['name']}'.", ephemeral=True)
                return

        draft["roles"].remove(role_key)
        role_name = roles.ROLES_METADATA[role_key].get("name", role_key.replace("_", " ").title())
        await send_hybrid_response(ctx, f"{get_emoji('leave')} Removed **{role_name}** from draft list '{draft['name']}' (Total roles: **{len(draft['roles'])}**).")

    @customrolelist.command(name="save", description="Save the active custom role list draft to database")
    async def save_list(self, ctx: commands.Context) -> None:
        if ctx.guild is None:
            await send_hybrid_response(ctx, "This command must be used in a server.", ephemeral=True)
            return

        lobby_manager = getattr(self.bot, "lobby_manager", None)
        database = getattr(self.bot, "db", None)
        if lobby_manager is None or database is None:
            await send_hybrid_response(ctx, "Lobby/Database system is not ready yet.", ephemeral=True)
            return

        lobby = await lobby_manager.get_lobby(ctx.guild.id)
        import config
        is_bot_admin = ctx.author.id in config.ADMIN_IDS
        is_server_admin = ctx.author.guild_permissions.administrator
        is_lobby_leader = lobby is not None and ctx.author.id == lobby.leader_id

        if not (is_bot_admin or is_server_admin or is_lobby_leader):
            await send_hybrid_response(ctx, f"{get_emoji('cross')} *\"Only the lobby leader or an administrator can draft custom rules.\"*", ephemeral=True)
            return

        if not hasattr(lobby_manager, "_custom_role_drafts"):
            lobby_manager._custom_role_drafts = {}

        draft = lobby_manager._custom_role_drafts.get(ctx.guild.id)
        if not draft:
            await send_hybrid_response(ctx, f"{get_emoji('cross')} No active draft. Create one first with `/customrolelist create <name>`.", ephemeral=True)
            return

        if not draft["roles"]:
            await send_hybrid_response(ctx, f"{get_emoji('cross')} Cannot save an empty list. Add some roles first with `/customrolelist add`.", ephemeral=True)
            return

        await database.save_custom_role_list(ctx.guild.id, draft["name"], draft["roles"])
        await send_hybrid_response(ctx, f"{get_emoji('save')} **Role list saved successfully!** '{draft['name']}' containing **{len(draft['roles'])}** roles.")

    @customrolelist.command(name="load", description="Load a saved custom role list and set it as active")
    @discord.app_commands.describe(name="Name of the saved list")
    async def load_list(self, ctx: commands.Context, name: str) -> None:
        if ctx.guild is None:
            await send_hybrid_response(ctx, "This command must be used in a server.", ephemeral=True)
            return

        lobby_manager = getattr(self.bot, "lobby_manager", None)
        database = getattr(self.bot, "db", None)
        if lobby_manager is None or database is None:
            await send_hybrid_response(ctx, "Lobby/Database system is not ready yet.", ephemeral=True)
            return

        lobby = await lobby_manager.get_lobby(ctx.guild.id)
        import config
        is_bot_admin = ctx.author.id in config.ADMIN_IDS
        is_server_admin = ctx.author.guild_permissions.administrator
        is_lobby_leader = lobby is not None and ctx.author.id == lobby.leader_id

        if not (is_bot_admin or is_server_admin or is_lobby_leader):
            await send_hybrid_response(ctx, f"{get_emoji('cross')} *\"Only the lobby leader or an administrator can load custom rules.\"*", ephemeral=True)
            return

        name_clean = name.strip()
        roles_list = await database.load_custom_role_list(ctx.guild.id, name_clean)
        if not roles_list:
            await send_hybrid_response(ctx, f"{get_emoji('cross')} **Not Found:** No saved list named '{name_clean}' exists in this server.", ephemeral=True)
            return

        if not hasattr(lobby_manager, "_custom_role_drafts"):
            lobby_manager._custom_role_drafts = {}

        lobby_manager._custom_role_drafts[ctx.guild.id] = {"name": name_clean, "roles": list(roles_list)}
        lobby_manager._active_custom_role_lists[ctx.guild.id] = list(roles_list)

        lobby_msg = ""
        if lobby:
            lobby.gamemode = "custom"
            await lobby_manager.refresh_lobby_message(ctx.guild.id)
            lobby_msg = " The lobby has been automatically set to **CUSTOM** gamemode."

        await send_hybrid_response(
            ctx, 
            f"{get_emoji('download')} **Loaded list:** '{name_clean}' containing **{len(roles_list)}** roles is now the active draft.{lobby_msg}"
        )

    @customrolelist.command(name="delete", description="Delete a saved custom role list")
    @discord.app_commands.describe(name="Name of the saved list")
    async def delete_list(self, ctx: commands.Context, name: str) -> None:
        if ctx.guild is None:
            await send_hybrid_response(ctx, "This command must be used in a server.", ephemeral=True)
            return

        lobby_manager = getattr(self.bot, "lobby_manager", None)
        database = getattr(self.bot, "db", None)
        if lobby_manager is None or database is None:
            await send_hybrid_response(ctx, "Lobby/Database system is not ready yet.", ephemeral=True)
            return

        lobby = await lobby_manager.get_lobby(ctx.guild.id)
        import config
        is_bot_admin = ctx.author.id in config.ADMIN_IDS
        is_server_admin = ctx.author.guild_permissions.administrator
        is_lobby_leader = lobby is not None and ctx.author.id == lobby.leader_id

        if not (is_bot_admin or is_server_admin or is_lobby_leader):
            await send_hybrid_response(ctx, f"{get_emoji('cross')} *\"Only the lobby leader or an administrator can delete custom rules.\"*", ephemeral=True)
            return

        name_clean = name.strip()
        deleted = await database.delete_custom_role_list(ctx.guild.id, name_clean)
        if not deleted:
            await send_hybrid_response(ctx, f"{get_emoji('cross')} **Not Found:** No saved list named '{name_clean}' exists in this server.", ephemeral=True)
            return

        await send_hybrid_response(ctx, f"{get_emoji('trash')} **Deleted list:** '{name_clean}' has been permanently removed.")

    @customrolelist.command(name="list", description="List all saved custom role lists for this server")
    async def list_lists(self, ctx: commands.Context) -> None:
        if ctx.guild is None:
            await send_hybrid_response(ctx, "This command must be used in a server.", ephemeral=True)
            return

        database = getattr(self.bot, "db", None)
        if database is None:
            await send_hybrid_response(ctx, "Database system is not ready yet.", ephemeral=True)
            return

        saved_lists = await database.list_custom_role_lists(ctx.guild.id)
        if not saved_lists:
            await send_hybrid_response(ctx, f"{get_emoji('empty')} **No saved custom role lists** in this server yet.")
            return

        import roles
        lines = []
        for item in saved_lists:
            role_names = []
            for rk in item["roles"]:
                rmeta = roles.ROLES_METADATA.get(rk, {})
                role_names.append(rmeta.get("name", rk.replace("_", " ").title()))
            roles_str = ", ".join(role_names)
            if len(roles_str) > 100:
                roles_str = roles_str[:97] + "..."
            lines.append(f"• **{item['name']}** ({len(item['roles'])} roles):\n  *{roles_str}*")

        from ui import build_v2_layout
        custom_roles_view = build_v2_layout(
            title=f"📜 Custom Role Lists — {ctx.guild.name}",
            description="\n\n".join(lines),
            color=discord.Color.blue(),
        )
        await send_hybrid_response(ctx, view=custom_roles_view)


    @add_role.autocomplete("role")
    async def add_role_autocomplete(self, interaction: discord.Interaction, current: str) -> list[discord.app_commands.Choice[str]]:
        import roles
        choices = []
        for rkey, rmeta in roles.ROLES_METADATA.items():
            name = rmeta.get("name", rkey.replace("_", " ").title())
            if current.lower() in name.lower() or current.lower() in rkey.lower():
                choices.append(discord.app_commands.Choice(name=name, value=rkey))
        return choices[:25]

    @remove_role.autocomplete("role")
    async def remove_role_autocomplete(self, interaction: discord.Interaction, current: str) -> list[discord.app_commands.Choice[str]]:
        lobby_manager = getattr(interaction.client, "lobby_manager", None)
        if not lobby_manager:
            return []
        draft = lobby_manager._custom_role_drafts.get(interaction.guild_id)
        if not draft:
            return []
        import roles
        choices = []
        for rkey in draft.get("roles", []):
            rmeta = roles.ROLES_METADATA.get(rkey, {})
            name = rmeta.get("name", rkey.replace("_", " ").title())
            if current.lower() in name.lower() or current.lower() in rkey.lower():
                choices.append(discord.app_commands.Choice(name=name, value=rkey))
        return choices[:25]

    @load_list.autocomplete("name")
    @delete_list.autocomplete("name")
    async def name_autocomplete(self, interaction: discord.Interaction, current: str) -> list[discord.app_commands.Choice[str]]:
        database = getattr(interaction.client, "db", None)
        if not database:
            return []
        lists = await database.list_custom_role_lists(interaction.guild_id)
        choices = []
        for row in lists:
            name = row["name"]
            if current.lower() in name.lower():
                choices.append(discord.app_commands.Choice(name=name, value=name))
        return choices[:25]

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LobbyCog(bot))
