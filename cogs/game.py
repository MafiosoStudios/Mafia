from __future__ import annotations

import discord
from discord.ext import commands

from views.vote_view import VoteView
from utils.constants import GameState
from utils.embeds import build_status_embed
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
            embed = build_status_embed(
                f"Game {active.game_id}",
                f"State: `{active.state}`\nUse the lobby controls to manage the match.",
            )
            await send_hybrid_response(ctx, embed=embed, view=VoteView(), ephemeral=True)
            return

        player_lines = [f"<@{user_id}>: {state.role_key or 'Unassigned'}" for user_id, state in session.players.items()]
        embed = build_status_embed(
            f"Game {active.game_id}",
            "\n".join(player_lines) if player_lines else "No players registered.",
        )
        if session.state == GameState.ENDED:
            embed.color = discord.Color.red()
        embed.add_field(name="State", value=str(session.state), inline=True)
        embed.add_field(name="Phase", value=str(session.phase), inline=True)
        embed.add_field(name="Players", value=str(len(session.players)), inline=True)
        await send_hybrid_response(ctx, embed=embed, view=VoteView(), ephemeral=True)

    @commands.hybrid_group(name="settings", description="Configure game settings for this server")
    async def settings(self, ctx: commands.Context) -> None:
        import config
        has_perm = ctx.author.id in config.ADMIN_IDS or (ctx.guild and ctx.author.guild_permissions.manage_guild)
        if not has_perm:
            await send_hybrid_response(ctx, "❌ **Unauthorized:** You do not have permission to use this command.", ephemeral=True)
            return
        if ctx.invoked_subcommand is None:
            await send_hybrid_response(ctx, "Try `/settings list` or `/settings set <key> <value>`.", ephemeral=True)

    @settings.command(name="list", description="List current game settings")
    async def list_settings(self, ctx: commands.Context) -> None:
        import config
        has_perm = ctx.author.id in config.ADMIN_IDS or (ctx.guild and ctx.author.guild_permissions.manage_guild)
        if not has_perm:
            await send_hybrid_response(ctx, "❌ **Unauthorized:** You do not have permission to use this command.", ephemeral=True)
            return
        guild_id = ctx.guild.id if ctx.guild else 0
        db = getattr(self.bot, "db", None)
        if not db:
            await send_hybrid_response(ctx, "Database not available.", ephemeral=True)
            return
        current = await db.get_guild_settings(guild_id)
        
        embed = discord.Embed(title=f"{get_emoji('settings')} Server Game Settings", color=discord.Color.blue())
        for key, val in current.items():
            embed.add_field(name=key, value=f"`{val}`", inline=True)
        await send_hybrid_response(ctx, embed=embed, ephemeral=True)

    @settings.command(name="set", description="Set a game setting value")
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
            await send_hybrid_response(ctx, "❌ **Unauthorized:** You do not have permission to use this command.", ephemeral=True)
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
        await send_hybrid_response(ctx, f"{get_emoji('check')} Setting `{key}` successfully updated to `{parsed_value}`.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GameCog(bot))
