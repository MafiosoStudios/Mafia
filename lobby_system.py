from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
import asyncio
import logging
import random

import discord
from database.database import DatabaseManager
from database.models import GamePlayerRecord, GameRecord
from game_engine import GameEngine
from game_manager import ActiveGameHandle, GameManager
from config import BotConfig, get_emoji
from utils.embeds import build_lobby_embed
from utils.helpers import utcnow

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class LobbySession:
    guild_id: int
    channel_id: int
    host_id: int
    leader_id: int
    min_players: int
    max_players: int
    created_at: datetime = field(default_factory=utcnow)
    players: list[int] = field(default_factory=list)
    join_queue: list[int] = field(default_factory=list)
    leave_queue: list[int] = field(default_factory=list)
    locked: bool = False
    message_id: int | None = None
    notes: dict[str, Any] = field(default_factory=dict)
    gamemode: str = "chaos"

    def can_join(self, user_id: int) -> bool:
        return not self.locked and user_id not in self.players and len(self.players) < self.max_players

    def can_start(self) -> bool:
        return len(self.players) >= self.min_players


class LobbyManager:
    """Keeps per-channel lobby state and hands successful games to the engine."""

    def __init__(
        self,
        bot: discord.Client,
        game_manager: GameManager,
        game_engine: GameEngine,
        database: DatabaseManager,
        config: BotConfig,
    ) -> None:
        self._bot = bot
        self._game_manager = game_manager
        self._game_engine = game_engine
        self._database = database
        self._config = config
        self._lobbies_by_guild: dict[int, LobbySession] = {}
        self._active_custom_role_lists: dict[int, list[str]] = {}
        self._debouncers: dict[int, Any] = {}
        self._lock = asyncio.Lock()

    async def create_lobby(
        self,
        guild_id: int,
        channel_id: int,
        host_id: int,
        min_players: int,
        max_players: int,
    ) -> LobbySession:
        async with self._lock:
            if await self._game_manager.get_game_by_guild(guild_id) is not None:
                raise ValueError("This server already has an active game.")
            if guild_id in self._lobbies_by_guild:
                raise ValueError("This server already has an open lobby.")

            lobby = LobbySession(
                guild_id=guild_id,
                channel_id=channel_id,
                host_id=host_id,
                leader_id=host_id,
                min_players=min_players,
                max_players=max_players,
                players=[host_id],
            )
            self._lobbies_by_guild[guild_id] = lobby
            logger.info("Created lobby for guild %s.", guild_id)
            return lobby

    async def get_lobby(self, guild_id: int) -> LobbySession | None:
        async with self._lock:
            return self._lobbies_by_guild.get(guild_id)

    async def join_lobby(self, guild_id: int, user_id: int) -> tuple[LobbySession, str]:
        status_msg = "Joined the lobby."
        async with self._lock:
            lobby = self._lobbies_by_guild.get(guild_id)
            if lobby is None:
                raise KeyError("Lobby not found.")

            if user_id in lobby.leave_queue:
                lobby.leave_queue.remove(user_id)
                status_msg = "Cancelled your request to leave after the match!"

            if lobby.locked:
                if user_id in lobby.players:
                    status_msg = "You are in the active match! Request to leave was cancelled."
                elif user_id in lobby.join_queue:
                    status_msg = "You are already in the Join Queue for the next match!"
                else:
                    lobby.join_queue.append(user_id)
                    status_msg = "Added to the **Join Queue**! You will automatically join when the match ends."
            else:
                if user_id in lobby.players:
                    raise ValueError("You are already in the lobby.")
                if len(lobby.players) >= lobby.max_players:
                    raise ValueError("Lobby is full.")
                lobby.players.append(user_id)
                if user_id in lobby.join_queue:
                    lobby.join_queue.remove(user_id)

            lobby_snapshot = lobby
        await self.refresh_lobby_message(guild_id)
        return lobby_snapshot, status_msg

    async def leave_lobby(self, guild_id: int, user_id: int) -> tuple[LobbySession | None, str]:
        status_msg = "Left the lobby."
        closed_lobby: LobbySession | None = None
        lobby_snapshot: LobbySession | None = None

        async with self._lock:
            lobby = self._lobbies_by_guild.get(guild_id)
            if lobby is None:
                return None, "No active lobby found."

            if lobby.locked:
                if user_id in lobby.join_queue:
                    lobby.join_queue.remove(user_id)
                    status_msg = "Removed from the Join Queue."
                elif user_id in lobby.players:
                    if user_id in lobby.leave_queue:
                        status_msg = "You are already in the Leave Queue for after the match!"
                    else:
                        lobby.leave_queue.append(user_id)
                        status_msg = "Added to the **Leave Queue**! You will leave the lobby when the match ends."
                else:
                    status_msg = "You are not in the active match or join queue."
                lobby_snapshot = lobby
            else:
                if user_id in lobby.join_queue:
                    lobby.join_queue.remove(user_id)

                if user_id not in lobby.players:
                    return lobby, "You are not in the lobby."

                lobby.players.remove(user_id)
                if user_id in lobby.leave_queue:
                    lobby.leave_queue.remove(user_id)

                if not lobby.players:
                    closed_lobby = self._lobbies_by_guild.pop(guild_id, None)
                else:
                    if lobby.leader_id == user_id:
                        lobby.leader_id = random.choice(lobby.players)
                    if lobby.host_id == user_id:
                        lobby.host_id = lobby.leader_id
                    lobby_snapshot = lobby

        if closed_lobby is not None:
            await self._delete_lobby_message(closed_lobby)
            return None, "Lobby was closed because all players left."

        await self.refresh_lobby_message(guild_id)
        return lobby_snapshot, status_msg

    async def start_lobby(self, guild_id: int, starter: discord.Member) -> ActiveGameHandle:
        lobby: LobbySession
        players_snapshot: tuple[int, ...]
        channel_id: int
        host_id: int
        min_players: int
        max_players: int
        async with self._lock:
            lobby = self._lobbies_by_guild.get(guild_id)
            if lobby is None:
                raise KeyError("Lobby not found.")
            if not lobby.can_start():
                raise ValueError("Not enough players to start the game.")
            if not self._can_start_lobby(lobby, starter):
                raise PermissionError("Only the lobby leader, an admin, or a bypass role can start the game.")

            lobby.locked = True
            players_snapshot = tuple(lobby.players)
            channel_id = lobby.channel_id
            host_id = lobby.host_id
            min_players = lobby.min_players
            max_players = lobby.max_players

        try:
            game_handle = await self._game_manager.create_game(
                guild_id=guild_id,
                channel_id=channel_id,
                host_id=host_id,
            )
            await self._database.upsert_game(
                GameRecord(
                    game_id=game_handle.game_id,
                    guild_id=guild_id,
                    channel_id=channel_id,
                    host_id=host_id,
                    state=game_handle.state,
                    min_players=min_players,
                    max_players=max_players,
                    created_at=game_handle.created_at,
                )
            )
            session = await self._game_engine.create_session(
                game_handle=game_handle,
                player_ids=players_snapshot,
                min_players=min_players,
                max_players=max_players,
            )
            session.metadata["gamemode"] = lobby.gamemode
            session.metadata["custom_role_list"] = self._active_custom_role_lists.get(guild_id)

            for player_id in players_snapshot:
                await self._database.upsert_game_player(
                    GamePlayerRecord(
                        game_id=game_handle.game_id,
                        user_id=player_id,
                        guild_id=guild_id,
                    )
                )
            
            # Start the setup phase (assigns roles, notifies host with Start Game button)
            asyncio.create_task(self._game_engine.setup_game(game_handle.game_id))
        except Exception:
            async with self._lock:
                if guild_id in self._lobbies_by_guild:
                    self._lobbies_by_guild[guild_id].locked = False
            raise

        await self._update_lobby_message(lobby, started=True, game_id=game_handle.game_id)
        return game_handle

    async def reset_lobby_after_game(self, guild_id: int) -> None:
        """Called when a match finishes to process leave/join queues and unlock the lobby."""
        async with self._lock:
            lobby = self._lobbies_by_guild.get(guild_id)
            if lobby is None:
                return

            # 1. Process Leave Queue first
            for uid in list(lobby.leave_queue):
                if uid in lobby.players:
                    lobby.players.remove(uid)
            lobby.leave_queue.clear()

            # Reassign leader/host if left
            if lobby.players:
                if lobby.leader_id not in lobby.players:
                    lobby.leader_id = random.choice(lobby.players)
                if lobby.host_id not in lobby.players:
                    lobby.host_id = lobby.leader_id

            # 2. Process Join Queue next
            for uid in list(lobby.join_queue):
                if uid not in lobby.players and len(lobby.players) < lobby.max_players:
                    lobby.players.append(uid)
            lobby.join_queue.clear()

            # Unlock lobby for next match
            lobby.locked = False

        await self.refresh_lobby_message(guild_id)

    async def bind_lobby_message(self, guild_id: int, message: discord.Message) -> None:
        async with self._lock:
            lobby = self._lobbies_by_guild.get(guild_id)
            if lobby is None:
                return
            lobby.message_id = message.id
            lobby.channel_id = message.channel.id
        await self.refresh_lobby_message(guild_id)

    async def refresh_lobby_message(self, guild_id: int, *, immediate: bool = False) -> None:
        async with self._lock:
            lobby = self._lobbies_by_guild.get(guild_id)
            if lobby is None:
                return

        if immediate:
            debounc = self._debouncers.get(guild_id)
            if debounc:
                await debounc.flush()
            else:
                await self._update_lobby_message(lobby)
        else:
            if guild_id not in self._debouncers:
                from utils.debouncer import DebouncedUpdater

                async def _do_update() -> None:
                    loc_lobby = await self.get_lobby(guild_id)
                    if loc_lobby:
                        await self._update_lobby_message(loc_lobby)

                self._debouncers[guild_id] = DebouncedUpdater(_do_update, delay=1.2)
            self._debouncers[guild_id].request_update()

    async def clear_lobby(self, guild_id: int, member: discord.Member) -> LobbySession:
        async with self._lock:
            lobby = self._lobbies_by_guild.get(guild_id)
            if lobby is None:
                raise KeyError("No active lobby found in this server.")
            if not self._can_clear_lobby(lobby, member):
                raise PermissionError("Only the lobby leader, host, or an admin can clear the lobby.")

            cleared_lobby = self._lobbies_by_guild.pop(guild_id, None)

        debounc = self._debouncers.pop(guild_id, None)
        if debounc:
            await debounc.flush()

        if cleared_lobby is not None:
            await self._delete_lobby_message(cleared_lobby)
        return cleared_lobby

    def _can_clear_lobby(self, lobby: LobbySession, member: discord.Member) -> bool:
        import config
        if member.id in config.ADMIN_IDS:
            return True
        if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
            return True
        if member.id in (lobby.leader_id, lobby.host_id):
            return True
        return any(role.id in self._config.lobby_leader_bypass_role_ids for role in member.roles)

    def _can_start_lobby(self, lobby: LobbySession, starter: discord.Member) -> bool:
        import config
        if starter.id in config.ADMIN_IDS:
            return True
        if starter.guild_permissions.administrator or starter.guild_permissions.manage_guild:
            return True
        if starter.id in (lobby.leader_id, lobby.host_id):
            return True
        return any(role.id in self._config.lobby_leader_bypass_role_ids for role in starter.roles)

    async def _update_lobby_message(self, lobby: LobbySession, *, started: bool = False, game_id: str | None = None) -> None:
        message = await self._fetch_lobby_message(lobby)
        if message is None:
            return
        
        from discord import ui
        from ui.components import build_lobby_card

        is_active = started or lobby.locked
        container = build_lobby_card(
            guild_name=self._guild_name(lobby.guild_id),
            leader_text=f"<@{lobby.leader_id}>",
            roster_lines=self._render_roster(lobby),
            current_players=len(lobby.players),
            min_players=lobby.min_players,
            max_players=lobby.max_players,
            started=is_active,
            gamemode=lobby.gamemode,
            join_queue_lines=self._render_join_queue(lobby),
            leave_queue_lines=self._render_leave_queue(lobby),
        )
        card_view = ui.LayoutView()
        card_view.add_item(container)

        if is_active:
            await message.edit(view=card_view)
        else:
            view = self._build_lobby_view(lobby)
            await message.edit(view=view)


    async def _delete_lobby_message(self, lobby: LobbySession) -> None:
        message = await self._fetch_lobby_message(lobby)
        if message is not None:
            await message.delete()

    async def _fetch_lobby_message(self, lobby: LobbySession) -> discord.Message | None:
        if lobby.message_id is None:
            return None
        channel = self._bot.get_channel(lobby.channel_id)
        if channel is None:
            try:
                channel = await self._bot.fetch_channel(lobby.channel_id)
            except Exception:
                return None
        if not hasattr(channel, "fetch_message"):
            return None
        try:
            return await channel.fetch_message(lobby.message_id)
        except Exception:
            return None

    def _build_lobby_view(self, lobby: LobbySession) -> discord.ui.View:
        from views.lobby_view import LobbyView

        return LobbyView(self._bot, lobby)

    def _guild_name(self, guild_id: int) -> str:
        guild = self._bot.get_guild(guild_id)
        return guild.name if guild is not None else f"Guild {guild_id}"

    def _render_roster(self, lobby: LobbySession) -> list[str]:
        guild = self._bot.get_guild(lobby.guild_id)
        roster_lines: list[str] = []
        for index, user_id in enumerate(lobby.players, start=1):
            member = guild.get_member(user_id) if guild is not None else None
            display_name = member.display_name if member is not None else f"<@{user_id}>"
            crown = f"{get_emoji('crown')} " if user_id == lobby.leader_id else ""
            roster_lines.append(f"{crown}`{index}.` {display_name}")
        return roster_lines

    def _render_join_queue(self, lobby: LobbySession) -> list[str]:
        guild = self._bot.get_guild(lobby.guild_id)
        lines: list[str] = []
        for index, user_id in enumerate(lobby.join_queue, start=1):
            member = guild.get_member(user_id) if guild is not None else None
            display_name = member.display_name if member is not None else f"<@{user_id}>"
            lines.append(f"`{index}.` {display_name}")
        return lines

    def _render_leave_queue(self, lobby: LobbySession) -> list[str]:
        guild = self._bot.get_guild(lobby.guild_id)
        lines: list[str] = []
        for index, user_id in enumerate(lobby.leave_queue, start=1):
            member = guild.get_member(user_id) if guild is not None else None
            display_name = member.display_name if member is not None else f"<@{user_id}>"
            lines.append(f"`{index}.` {display_name}")
        return lines
