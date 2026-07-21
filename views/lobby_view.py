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
            emoji=get_emoji("join"),
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
            await lobby_manager.join_lobby(
                guild_id=interaction.guild_id or lobby.guild_id,
                user_id=interaction.user.id,
            )
        except Exception as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return


class LeaveLobbyButton(ui.Button):
    def __init__(self, view_ref: LobbyView) -> None:
        super().__init__(
            label="Leave Lobby",
            style=discord.ButtonStyle.secondary,
            custom_id="lobby:leave",
            emoji=get_emoji("leave"),
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
        await lobby_manager.leave_lobby(
            guild_id=interaction.guild_id or lobby.guild_id,
            user_id=interaction.user.id,
        )


class StartMatchButton(ui.Button):
    def __init__(self, view_ref: LobbyView) -> None:
        super().__init__(
            label="Begin Match",
            style=discord.ButtonStyle.danger,
            custom_id="lobby:start",
            emoji=get_emoji("sword"),
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
