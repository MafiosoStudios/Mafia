from __future__ import annotations

import discord
from discord import Interaction, ui

from config import get_emoji
from lobby_system import LobbySession
from ui.base import MafiosoLayoutView
from ui.components import build_lobby_card


class JoinLobbyButton(ui.Button):
    def __init__(self, view_ref: LobbyView) -> None:
        super().__init__(
            label="Join Lobby",
            style=discord.ButtonStyle.success,
            custom_id="lobby:join",
        )
        self.view_ref = view_ref

    async def callback(self, interaction: Interaction) -> None:
        bot = self.view_ref.bot
        lobby = self.view_ref.lobby
        lobby_manager = getattr(bot, "lobby_manager", None)
        if lobby_manager is None:
            await interaction.response.send_message("Lobby system is not ready yet.", ephemeral=True)
            return

        guild_id = interaction.guild_id or lobby.guild_id
        try:
            lobby_snapshot, status_msg = await lobby_manager.join_lobby(
                guild_id=guild_id,
                user_id=interaction.user.id,
            )
        except Exception as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        if not interaction.response.is_done():
            await interaction.response.defer()

        # Send public join notification card to channel matching the media screenshot
        channel = interaction.channel
        if channel and lobby_snapshot:
            user = interaction.user
            user_name = user.display_name
            title = f"{user_name} has joined the party."
            party_size = len(lobby_snapshot.players)
            gamemode = getattr(lobby_snapshot, "gamemode", "classic")
            description = (
                f"🥳 Party Size: **{party_size}**\n"
                f"🎲 Current Mode : **{gamemode}**"
            )
            avatar_url = user.display_avatar.url if hasattr(user, "display_avatar") else (user.avatar.url if getattr(user, "avatar", None) else None)
            footer_text = "Current Patch: 1.0.7\nType /party to see who's in the party!"

            from ui import build_v2_layout
            join_layout = build_v2_layout(
                title=title,
                description=description,
                color=discord.Color.from_rgb(46, 204, 113),
                thumbnail_url=avatar_url,
                footer_text=footer_text,
            )
            try:
                await channel.send(view=join_layout)
            except Exception:
                pass


class LeaveLobbyButton(ui.Button):
    def __init__(self, view_ref: LobbyView) -> None:
        super().__init__(
            label="Leave Lobby",
            style=discord.ButtonStyle.secondary,
            custom_id="lobby:leave",
        )
        self.view_ref = view_ref

    async def callback(self, interaction: Interaction) -> None:
        bot = self.view_ref.bot
        lobby = self.view_ref.lobby
        lobby_manager = getattr(bot, "lobby_manager", None)
        if lobby_manager is None:
            await interaction.response.send_message("Lobby system is not ready yet.", ephemeral=True)
            return

        guild_id = interaction.guild_id or lobby.guild_id
        user = interaction.user
        lobby_snapshot, status_msg = await lobby_manager.leave_lobby(
            guild_id=guild_id,
            user_id=user.id,
        )

        if not interaction.response.is_done():
            await interaction.response.defer()

        channel = interaction.channel
        if channel:
            bot_name = bot.user.display_name if bot and bot.user else "Mafia Remastered"
            from ui import build_v2_layout
            leave_layout = build_v2_layout(
                description=f"**{bot_name}**\n\n{user.display_name} left the party.",
                color=discord.Color.from_rgb(231, 76, 60),
            )
            try:
                await channel.send(view=leave_layout)
            except Exception:
                pass


class StartMatchButton(ui.Button):
    def __init__(self, view_ref: LobbyView) -> None:
        super().__init__(
            label="Begin Match",
            style=discord.ButtonStyle.danger,
            custom_id="lobby:start",
        )
        self.view_ref = view_ref

    async def callback(self, interaction: Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        bot = self.view_ref.bot
        lobby = self.view_ref.lobby
        lobby_manager = getattr(bot, "lobby_manager", None)
        if lobby_manager is None:
            await interaction.followup.send("Lobby system is not ready yet.", ephemeral=True)
            return
        try:
            member = interaction.user if isinstance(interaction.user, discord.Member) else None
            if member is None:
                await interaction.followup.send("This command must be used in a server.", ephemeral=True)
                return

            is_admin = member.guild_permissions.administrator
            if member.id != lobby.host_id and not is_admin:
                await interaction.followup.send(
                    "Only the lobby host (who created it) or an admin can start the match!",
                    ephemeral=True,
                )
                return
            await lobby_manager.start_lobby(interaction.guild_id or lobby.guild_id, member)
        except Exception as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        await interaction.followup.send("The game is beginning.", ephemeral=True)



class LobbyView(MafiosoLayoutView):
    """Components V2 LayoutView for Game Lobbies."""

    def __init__(self, bot: discord.Client, lobby: LobbySession) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.lobby = lobby

        guild = bot.get_guild(lobby.guild_id) if bot is not None else None
        guild_name = guild.name if guild is not None else f"Guild {lobby.guild_id}"

        lobby_manager = getattr(bot, "lobby_manager", None)
        roster_lines = lobby_manager._render_roster(lobby) if lobby_manager else []

        container = build_lobby_card(
            guild_name=guild_name,
            leader_text=f"<@{lobby.leader_id}>",
            roster_lines=roster_lines,
            current_players=len(lobby.players),
            min_players=lobby.min_players,
            max_players=lobby.max_players,
            started=False,
            gamemode=lobby.gamemode,
        )

        buttons_row = ui.ActionRow(
            JoinLobbyButton(self),
            LeaveLobbyButton(self),
            StartMatchButton(self),
        )
        container.add_item(buttons_row)
        self.add_item(container)
