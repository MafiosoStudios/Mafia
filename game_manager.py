from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
import asyncio
import logging
import uuid

from utils.helpers import utcnow

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ActiveGameHandle:
    game_id: str
    guild_id: int
    channel_id: int
    host_id: int
    created_at: datetime = field(default_factory=utcnow)
    state: str = "lobby"
    payload: dict[str, Any] = field(default_factory=dict)


class GameManager:
    """Tracks live game instances without depending on Discord objects directly."""

    def __init__(self) -> None:
        self._games_by_guild: dict[int, ActiveGameHandle] = {}
        self._games_by_id: dict[str, ActiveGameHandle] = {}
        self._lock = asyncio.Lock()

    async def create_game(self, guild_id: int, channel_id: int, host_id: int) -> ActiveGameHandle:
        async with self._lock:
            if guild_id in self._games_by_guild:
                raise ValueError("This server already has an active game.")
            game = ActiveGameHandle(
                game_id=uuid.uuid4().hex,
                guild_id=guild_id,
                channel_id=channel_id,
                host_id=host_id,
            )
            self._games_by_guild[guild_id] = game
            self._games_by_id[game.game_id] = game
            logger.info("Created game %s for guild %s.", game.game_id, guild_id)
            return game

    async def get_game_by_guild(self, guild_id: int) -> ActiveGameHandle | None:
        async with self._lock:
            return self._games_by_guild.get(guild_id)

    async def get_game_by_id(self, game_id: str) -> ActiveGameHandle | None:
        async with self._lock:
            return self._games_by_id.get(game_id)

    async def update_state(self, game_id: str, state: str) -> None:
        async with self._lock:
            game = self._games_by_id.get(game_id)
            if game is None:
                raise KeyError(f"Game '{game_id}' is not active.")
            game.state = state

    async def remove_game(self, game_id: str) -> ActiveGameHandle | None:
        async with self._lock:
            game = self._games_by_id.pop(game_id, None)
            if game is None:
                return None
            self._games_by_guild.pop(game.guild_id, None)
            logger.info("Removed game %s.", game_id)
            return game

    async def clear(self) -> None:
        async with self._lock:
            self._games_by_guild.clear()
            self._games_by_id.clear()
