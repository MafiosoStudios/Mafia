from __future__ import annotations

import discord
from discord.ext import commands

from views.vote_view import VoteView
from utils.constants import GameState
from ui import build_v2_layout, MafiosoLayoutView
from utils.helpers import send_hybrid_response
from config import get_emoji



class GameCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.hybrid_group(name="game", description="Inspect and manage the current game")
    async def game(self, ctx: commands.Context) -> None:
        if ctx.invoked_subcommand is None:
            await send_hybrid_response(
                ctx,
                "Try `game status`, `game night`, or `game ability`.",
                ephemeral=True,
            )

    @game.command(name="status")
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def status(self, ctx: commands.Context) -> None:
        game_manager = getattr(self.bot, "game_manager", None)
        game_engine = getattr(self.bot, "game_engine", None)
        if game_manager is None:
            await send_hybrid_response(ctx, "Game manager is not ready yet.", ephemeral=True)
            return
        active = await game_manager.get_game_by_guild(ctx.guild.id if ctx.guild is not None else 0)
        if active is None:
            await send_hybrid_response(ctx, "No active game in this server.", ephemeral=True)
            return
        session = await game_engine.get_session(active.game_id) if game_engine is not None else None
        if session is None:
            status_layout = build_status_embed(
                f"Game {active.game_id}",
                f"State: `{active.state}`\nUse the lobby controls to manage the match.",
            )
            await send_hybrid_response(ctx, view=status_layout, ephemeral=True)
            return



        import roles
        player_lines = []
        for user_id, state in session.players.items():
            if state.role_key:
                role_emoji = get_emoji(state.role_key)
                role_emoji_prefix = f"{role_emoji} " if role_emoji else ""
                role_name = roles.ROLES_METADATA.get(state.role_key, {}).get("name", state.role_key)
                player_lines.append(f"<@{user_id}>: {role_emoji_prefix}{role_name}")
            else:
                player_lines.append(f"<@{user_id}>: Unassigned")
        desc = (
            f"• **State:** `{session.state.name if hasattr(session.state, 'name') else session.state}`\n"
            f"• **Phase:** `{session.phase.name if hasattr(session.phase, 'name') else session.phase}`\n"
            f"• **Players Registered:** `{len(session.players)}`\n\n"
            f"## Roster\n" + ("\n".join(player_lines) if player_lines else "*No players registered.*")
        )
        status_view = build_v2_layout(
            title=f"{get_emoji('lobby')} Game Status — Match {active.game_id}",
            description=desc,
            color=discord.Color.red() if session.state == GameState.ENDED else discord.Color.blue(),
        )
        await send_hybrid_response(ctx, view=status_view, ephemeral=True)

    @commands.hybrid_group(name="settings", description="Configure game settings for this server", invoke_without_command=True)
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def settings(self, ctx: commands.Context) -> None:
        import config
        has_perm = ctx.author.id in config.ADMIN_IDS or (ctx.guild and ctx.author.guild_permissions.manage_guild)
        if not has_perm:
            await send_hybrid_response(ctx, f"{get_emoji('cross')} **Unauthorized:** You do not have permission to use this command.", ephemeral=True)
            return
        if ctx.invoked_subcommand is None:
            await self.list_settings(ctx)

    @settings.command(name="list", aliases=["show"], description="List current game settings for this server")
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def list_settings(self, ctx: commands.Context) -> None:
        import config
        has_perm = ctx.author.id in config.ADMIN_IDS or (ctx.guild and ctx.author.guild_permissions.manage_guild)
        if not has_perm:
            await send_hybrid_response(ctx, f"{get_emoji('cross')} **Unauthorized:** You do not have permission to use this command.", ephemeral=True)
            return
        guild_id = ctx.guild.id if ctx.guild else 0
        db = getattr(self.bot, "db", None)
        if not db:
            await send_hybrid_response(ctx, "Database not available.", ephemeral=True)
            return
        current = await db.get_guild_settings(guild_id)
        
        labels = {
            "night_duration": "🌙 Night Duration",
            "day_duration": "☀️ Day Discussion Duration",
            "vote_duration": "🗳️ Nomination/Vote Duration",
            "plea_duration": "⚖️ Defense Plea Duration",
            "verdict_duration": f"{get_emoji('verdict')} Verdict Duration",
            "anonymous_voting": "🕶️ Anonymous Voting",
        }
        
        lines = []
        for key, val in current.items():
            label = labels.get(key, f"⚙️ {key.replace('_', ' ').title()}")
            display_val = f"`{val}` seconds" if "duration" in key else (f"`Enabled`" if val else f"`Disabled`")
            lines.append(f"• **{label}:** {display_val}")

        settings_desc = (
            f"Here are the active game parameters for **{ctx.guild.name if ctx.guild else 'this server'}**:\n\n"
            + "\n".join(lines) + "\n\n"
            f"-# Use `/settings set <key> <value>` to change any value."
        )
        settings_view = build_v2_layout(
            title=f"{get_emoji('settings')} Server Game Settings",
            description=settings_desc,
            color=discord.Color.blue(),
        )
        await send_hybrid_response(ctx, view=settings_view, ephemeral=True)

    @settings.command(name="set", description="Set a game setting value")
    @commands.cooldown(1, 30, commands.BucketType.user)
    @discord.app_commands.choices(key=[
        discord.app_commands.Choice(name="Night Duration (seconds)", value="night_duration"),
        discord.app_commands.Choice(name="Day Discussion Duration (seconds)", value="day_duration"),
        discord.app_commands.Choice(name="Voting Duration (seconds)", value="vote_duration"),
        discord.app_commands.Choice(name="Defense Plea Duration (seconds)", value="plea_duration"),
        discord.app_commands.Choice(name="Verdict Duration (seconds)", value="verdict_duration"),
        discord.app_commands.Choice(name="Anonymous Voting (True/False)", value="anonymous_voting")
    ])
    async def set_setting(self, ctx: commands.Context, key: str, value: str) -> None:
        import config
        has_perm = ctx.author.id in config.ADMIN_IDS or (ctx.guild and ctx.author.guild_permissions.manage_guild)
        if not has_perm:
            await send_hybrid_response(ctx, f"{get_emoji('cross')} **Unauthorized:** You do not have permission to use this command.", ephemeral=True)
            return
        guild_id = ctx.guild.id if ctx.guild else 0
        db = getattr(self.bot, "db", None)
        if not db:
            await send_hybrid_response(ctx, "Database not available.", ephemeral=True)
            return

        if key == "anonymous_voting":
            parsed_value = value.lower() in ("true", "yes", "1", "enable")
        else:
            try:
                parsed_value = int(value)
                if parsed_value <= 0:
                    raise ValueError
            except ValueError:
                await send_hybrid_response(ctx, f"{get_emoji('cross')} Value for this setting must be a positive integer.", ephemeral=True)
                return

        await db.update_guild_setting(guild_id, key, parsed_value)
        updated_card = build_v2_layout(
            title=f"{get_emoji('check')} Setting Updated",
            description=f"Setting **`{key}`** has been updated to **`{parsed_value}`** for this server.",
            color=discord.Color.green(),
        )
        await send_hybrid_response(ctx, view=updated_card, ephemeral=True)


    @commands.command(name="rebellion", aliases=["rebel"])
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def rebellion(self, ctx: commands.Context) -> None:
        """Cause a rebellion in the entire lobby, ending the discussion phase immediately. (Lelouch Lamperouge, Once per game)"""
        game_manager = getattr(self.bot, "game_manager", None)
        game_engine = getattr(self.bot, "game_engine", None)
        if not game_manager or not game_engine:
            await ctx.send("Game manager is not ready.")
            return

        active = await game_manager.get_game_by_guild(ctx.guild.id if ctx.guild is not None else 0)
        if not active:
            await ctx.send("No active game in this server.")
            return

        session = await game_engine.get_session(active.game_id)
        if not session:
            await ctx.send("No active game session.")
            return

        player_state = session.players.get(ctx.author.id)
        if not player_state or not player_state.alive:
            await ctx.send("Only living players in this game can use this command.")
            return

        if player_state.role_key != "lelouch":
            await ctx.send("Only Lelouch Lamperouge can command the Black Knights!")
            return

        if player_state.metadata.get("rebellion_used"):
            await ctx.send("You have already used your Rebellion once this game.")
            return

        if session.phase != GamePhase.DISCUSSION:
            await ctx.send("You can only cause a Rebellion during the Discussion Phase.")
            return

        # Mark as used and trigger rebellion
        player_state.metadata["rebellion_used"] = True
        session.metadata["rebellion_triggered"] = True
        
        await ctx.send(
            f"{get_emoji('crown')} **Lelouch Lamperouge has commanded the Black Knights!**\n"
            f"📢 *'I, Lelouch vi Britannia, command you: REBEL!'*\n"
            f"{get_emoji('fire')} **The discussion phase is cut short. Skipped directly to the Nomination Phase!**"
        )

    @commands.command(name="newrelease")
    @commands.cooldown(1, 10, commands.BucketType.guild)
    async def newrelease(self, ctx: commands.Context, image_path: str = None) -> None:
        """Sends an update release embed for Mafioso. (Owner only)"""
        # Only accessible to the user with discord user id "744831273406824449"
        if str(ctx.author.id) != "744831273406824449":
            await ctx.send(f"{get_emoji('cross')} **Unauthorized:** Only the developer can use this command.", delete_after=5)
            return

        import os
        import discord

        # If no path provided, check project root or default downloads location
        if not image_path:
            root_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "VersionUpdate1.0.0.png")
            if os.path.exists(root_path):
                image_path = root_path
            else:
                default_path = r"C:\MafiosoImgs\VersionUpdate1.0.0.png"
                if os.path.exists(default_path):
                    image_path = default_path

        newrelease_layout = build_v2_layout(
            title="Mafioso",
            description=(
                f"We are thrilled to announce the official release of **Mafioso**, "
                f"the ultimate anime-themed Mafia Discord bot! Here's a brief overview "
                f"of what this bot brings to the arena:\n\n"
                f"**What Makes Mafioso Different?**\n"
                f"• **Unique Anime Roles** — Play as characters from across anime, each designed around their actual powers and personalities.\n\n"
                f"• **Powerful Abilities** — Manipulate votes, investigate players, deceive the town, protect allies, assassinate enemies, and completely turn the game around.\n\n"
                f"• **No Two Games Are the Same** — Different roles, players, strategies, and interactions make every lobby unpredictable.\n\n\n"
                f"**How the Game Works**\n"
                f"• Players are assigned roles, each with unique abilities and objectives. The game progresses through day and night phases, where players discuss, vote, and execute their strategies.\n\n"
                f"• You can do ``help`` for a list of available commands or ``tutorial`` for a detailed guide of course.\n\n"
                f"• ``lobby`` to jump right into the game, ``lobby_create`` to actually host one, this bot operates just like our traditional mafia bots\n\n"
                f"• If you do not understand some roles you can always do ``roleinfo`` for information on every character"
            ),
            color=discord.Color.from_rgb(0, 0, 0),
            thumbnail_url=ctx.guild.icon.url if (ctx.guild and ctx.guild.icon) else None,
            footer_text="Mafioso Patch Note • Version 1.0.0",
        )

        if image_path and os.path.exists(image_path):
            file = discord.File(image_path, filename="release_image.png")
            await ctx.send(file=file, view=newrelease_layout)
        else:
            await ctx.send(view=newrelease_layout)

    @commands.hybrid_command(name="resume", description="Resume the active game from database state")
    @commands.cooldown(1, 30, commands.BucketType.user)
    async def resume(self, ctx: commands.Context) -> None:
        import config
        import logging
        logger = logging.getLogger(__name__)
        has_perm = ctx.author.id in config.ADMIN_IDS or (ctx.guild and ctx.author.guild_permissions.manage_guild)
        if not has_perm:
            await send_hybrid_response(ctx, f"{get_emoji('cross')} **Unauthorized:** You do not have permission to use this command.", ephemeral=True)
            return

        guild_id = ctx.guild.id if ctx.guild else 0
        if not guild_id:
            await send_hybrid_response(ctx, "This command must be used in a server.", ephemeral=True)
            return

        game_manager = getattr(self.bot, "game_manager", None)
        game_engine = getattr(self.bot, "game_engine", None)
        db = getattr(self.bot, "db", None)

        if not game_manager or not game_engine or not db:
            await send_hybrid_response(ctx, "Game system is not fully loaded.", ephemeral=True)
            return

        # Check if server already has an active game in manager
        existing_handle = await game_manager.get_game_by_guild(guild_id)
        if existing_handle:
            session = await game_engine.get_session(existing_handle.game_id)
            if session:
                await send_hybrid_response(
                    ctx,
                    f"{get_emoji('warning')} There is already a live active game session (`{existing_handle.game_id}`) running in this server.",
                    ephemeral=True
                )
                return

        # Load active state dictionary from database
        state_dict = await db.get_active_game_by_guild(guild_id)
        if not state_dict:
            await send_hybrid_response(ctx, f"{get_emoji('cross')} No saved active game state found for this server.", ephemeral=True)
            return

        try:
            from game_engine import deserialize_session
            session = deserialize_session(state_dict)
            
            # Register in game_manager
            await game_manager.register_game(session.game_handle)
            
            # Put session in engine cache
            async with game_engine._lock:
                game_engine._sessions[session.game_handle.game_id] = session
            
            # Run the loop!
            await game_engine.run_game_loop_from_resume(session.game_handle.game_id)
            
            await send_hybrid_response(
                ctx,
                f"{get_emoji('refresh')} **Success:** Active game (`{session.game_handle.game_id}`) has been successfully resumed from state `{session.phase.value}`!",
                ephemeral=False
            )
        except Exception:
            logger.exception("Failed to deserialize and resume game.")
            await send_hybrid_response(ctx, f"{get_emoji('cross')} Failed to resume game. Check bot logs for details.", ephemeral=True)

    @commands.hybrid_command(name="tutorial", description="Open the interactive Mafioso tutorial guide")
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def tutorial(self, ctx: commands.Context) -> None:
        from views.tutorial_view import TutorialView
        view = TutorialView()
        await send_hybrid_response(ctx, view=view, ephemeral=True)


    @commands.hybrid_command(name="roles", description="View the interactive directory of every role in the game")
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def roles(self, ctx: commands.Context) -> None:
        from views.roles_view import RolesView
        view = RolesView(ctx.author.id)
        await send_hybrid_response(ctx, view=view, ephemeral=True)


    @commands.hybrid_command(name="invite", description="Generate the bot's invite link with calculated permissions")
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def invite(self, ctx: commands.Context) -> None:
        # Programmatic permissions calculation based on required bot operations
        perms = discord.Permissions()
        perms.view_channel = True
        perms.send_messages = True
        perms.embed_links = True
        perms.attach_files = True
        perms.manage_channels = True
        perms.manage_messages = True
        perms.add_reactions = True
        perms.use_external_emojis = True
        perms.read_message_history = True
        
        # Scopes: bot and applications.commands
        client_id = self.bot.user.id if self.bot.user else 0
        invite_url = discord.utils.oauth_url(
            client_id=client_id,
            permissions=perms,
            scopes=("bot", "applications.commands")
        )

        invite_button = discord.ui.Button(
            label="Invite Bot",
            url=invite_url,
            style=discord.ButtonStyle.link,
            emoji=get_emoji("lobby")
        )

        invite_action_view = MafiosoLayoutView()
        invite_avatar_url = self.bot.user.display_avatar.url if self.bot.user else None
        invite_layout = build_v2_layout(
            title=f"{get_emoji('link')} Summon Mafioso",
            description=(
                "Invoke the ultimate anime-themed social deduction bot to your server!\n"
                "Unleash characters like Frieza, Lelouch, and Ayanokoji in intense faction battles."
            ),
            color=discord.Color.purple(),
            thumbnail_url=invite_avatar_url,
            view=invite_action_view,
        )
        # Add the invite link button inside the layout
        container = invite_layout.children[0]
        container.add_item(discord.ui.ActionRow(invite_button))

        await send_hybrid_response(ctx, view=invite_layout, ephemeral=True)


    @commands.hybrid_command(name="patchnotes", description="Browse Mafioso version patch notes")
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def patchnotes(self, ctx: commands.Context) -> None:
        from views.patchnotes_view import PatchNotesView
        index = len(PatchNotesView.PATCHES) - 1  # start at latest
        view = PatchNotesView.build_layout_view(index)
        await send_hybrid_response(ctx, view=view, ephemeral=False)

    @commands.hybrid_command(name="priorities", aliases=["priority", "rolepriorities"], description="View role action execution order and priorities")
    async def priorities(self, ctx: commands.Context) -> None:
        from views.priorities_view import PrioritiesView
        view = PrioritiesView.build_layout()
        await send_hybrid_response(ctx, view=view, ephemeral=False)



async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GameCog(bot))
