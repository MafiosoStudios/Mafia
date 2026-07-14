from __future__ import annotations

import discord
from discord import Interaction

from lobby_system import LobbySession
from config import get_emoji


class LobbyView(discord.ui.View):
    def __init__(self, bot: discord.Client, lobby: LobbySession) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.lobby = lobby
        # Emojis are set here (rather than in the decorator) so they stay
        # fully configurable from config.EMOJIS without touching this file.
        self.join_button.emoji = get_emoji("join")
        self.leave_button.emoji = get_emoji("leave")
        self.start_button.emoji = get_emoji("sword")

    @discord.ui.button(label="Join Lobby", style=discord.ButtonStyle.success)
    async def join_button(
        self,
        interaction: Interaction,
        button: discord.ui.Button["LobbyView"],
    ) -> None:
        lobby_manager = getattr(self.bot, "lobby_manager", None)
        if lobby_manager is None:
            await interaction.response.send_message("Lobby system is not ready yet.", ephemeral=True)
            return
        try:
            await lobby_manager.join_lobby(
                guild_id=interaction.guild_id or self.lobby.guild_id,
                user_id=interaction.user.id,
            )
        except Exception as exc:  # pragma: no cover - UI feedback path
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_message("You joined the lobby.", ephemeral=True)

    @discord.ui.button(label="Leave Lobby", style=discord.ButtonStyle.secondary)
    async def leave_button(
        self,
        interaction: Interaction,
        button: discord.ui.Button["LobbyView"],
    ) -> None:
        lobby_manager = getattr(self.bot, "lobby_manager", None)
        if lobby_manager is None:
            await interaction.response.send_message("Lobby system is not ready yet.", ephemeral=True)
            return
        await lobby_manager.leave_lobby(
            guild_id=interaction.guild_id or self.lobby.guild_id,
            user_id=interaction.user.id,
        )
        await interaction.response.send_message("You left the lobby.", ephemeral=True)

    @discord.ui.button(label="Begin Match", style=discord.ButtonStyle.danger)
    async def start_button(
        self,
        interaction: Interaction,
        button: discord.ui.Button["LobbyView"],
    ) -> None:
        lobby_manager = getattr(self.bot, "lobby_manager", None)
        if lobby_manager is None:
            await interaction.response.send_message("Lobby system is not ready yet.", ephemeral=True)
            return
        try:
            member = interaction.user if isinstance(interaction.user, discord.Member) else None
            if member is None:
                await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
                return
            # Strict Host/Admin Check
            is_admin = member.guild_permissions.administrator
            if member.id != self.lobby.host_id and not is_admin:
                await interaction.response.send_message("Only the lobby host (who created it) or an admin can start the match!", ephemeral=True)
                return
            await lobby_manager.start_lobby(interaction.guild_id or self.lobby.guild_id, member)
        except Exception as exc:  # pragma: no cover - UI feedback path
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await interaction.response.send_message("The game is beginning.", ephemeral=True)
