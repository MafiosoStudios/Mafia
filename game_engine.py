from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
import asyncio
import logging

from database.database import DatabaseManager
from database.models import GamePlayerRecord, GameRecord, MatchHistoryRecord
from game_manager import ActiveGameHandle
from utils.constants import GamePhase, GameState, RoleFaction
from utils.helpers import utcnow
from utils.roles import BaseRole, RoleContext, role_registry

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class GamePlayerState:
    user_id: int
    role_key: str | None = None
    faction: str | None = None
    alive: bool = True
    disconnected: bool = False
    vote_weight: int = 1
    votes_cast: int = 0
    night_actions_used: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class GameSession:
    game_handle: ActiveGameHandle
    player_ids: tuple[int, ...]
    min_players: int
    max_players: int
    created_at: datetime = field(default_factory=utcnow)
    state: GameState = GameState.LOBBY
    phase: GamePhase = GamePhase.JOINING
    players: dict[int, GamePlayerState] = field(default_factory=dict)
    role_history: dict[int, str] = field(default_factory=dict)
    votes: dict[int, int] = field(default_factory=dict)
    night_actions: dict[int, dict[str, Any]] = field(default_factory=dict)
    winner_faction: str | None = None
    draw_reason: str | None = None


class GameEngine:
    """Owns gameplay state and resolves roles and votes."""

    def __init__(self, database: DatabaseManager) -> None:
        self._database = database
        self._sessions: dict[str, GameSession] = {}
        self._lock = asyncio.Lock()

    async def create_session(
        self,
        game_handle: ActiveGameHandle,
        player_ids: tuple[int, ...],
        min_players: int,
        max_players: int,
    ) -> GameSession:
        async with self._lock:
            session = GameSession(
                game_handle=game_handle,
                player_ids=player_ids,
                min_players=min_players,
                max_players=max_players,
                players={user_id: GamePlayerState(user_id=user_id) for user_id in player_ids},
            )
            self._sessions[game_handle.game_id] = session
            logger.info("Created game session %s.", game_handle.game_id)
            return session

    async def get_session(self, game_id: str) -> GameSession | None:
        async with self._lock:
            return self._sessions.get(game_id)

    async def assign_roles(self, game_id: str, role_keys: tuple[str, ...]) -> dict[int, str]:
        async with self._lock:
            session = self._require_session(game_id)
            player_ids = list(session.players)
            if len(role_keys) < len(player_ids):
                raise ValueError("Not enough roles for all players.")

            for index, user_id in enumerate(player_ids):
                role_key = role_keys[index]
                role_cls = role_registry.get(role_key)
                session.players[user_id].role_key = role_key
                session.players[user_id].faction = role_cls.faction.value
                session.role_history[user_id] = role_key
                await self._database.upsert_game_player(
                    GamePlayerRecord(
                        game_id=game_id,
                        user_id=user_id,
                        guild_id=session.game_handle.guild_id,
                        character_key=role_key,
                        faction=role_cls.faction.value,
                    )
                )
            session.state = GameState.NIGHT
            session.phase = GamePhase.NIGHT_ACTIONS
            return dict(session.role_history)

    async def register_vote(self, game_id: str, voter_id: int, target_id: int | None) -> None:
        async with self._lock:
            session = self._require_session(game_id)
            if voter_id not in session.players:
                raise KeyError("Voter is not part of the session.")
            if target_id is None:
                session.votes.pop(voter_id, None)
            else:
                session.votes[voter_id] = target_id
                session.players[voter_id].votes_cast += 1

    async def queue_night_action(
        self,
        game_id: str,
        user_id: int,
        payload: dict[str, Any],
    ) -> None:
        async with self._lock:
            session = self._require_session(game_id)
            if user_id not in session.players:
                raise KeyError("Actor is not part of the session.")
            session.night_actions[user_id] = payload
            session.players[user_id].night_actions_used += 1

    async def resolve_night(self, game_id: str) -> None:
        async with self._lock:
            session = self._require_session(game_id)
            session.phase = GamePhase.DISCUSSION
            session.state = GameState.DAY
            session.night_actions.clear()

    async def resolve_day(self, game_id: str) -> None:
        async with self._lock:
            session = self._require_session(game_id)
            self._apply_votes(session)
            victory = self._evaluate_victory(session)
            if victory is not None:
                session.state = GameState.ENDED
                session.phase = GamePhase.CLEANUP
                session.winner_faction = victory
            else:
                session.phase = GamePhase.NIGHT_ACTIONS
                session.state = GameState.NIGHT

    async def eliminate_player(self, game_id: str, user_id: int, cause: str) -> None:
        async with self._lock:
            session = self._require_session(game_id)
            player = session.players[user_id]
            player.alive = False
            player.metadata["death_cause"] = cause
            await self._database.upsert_game_player(
                GamePlayerRecord(
                    game_id=game_id,
                    user_id=user_id,
                    guild_id=session.game_handle.guild_id,
                    character_key=player.role_key,
                    faction=player.faction,
                    alive=False,
                    disconnected=player.disconnected,
                    vote_weight=player.vote_weight,
                    eliminated_at=utcnow(),
                    death_cause=cause,
                )
            )

    async def mark_disconnected(self, game_id: str, user_id: int) -> None:
        async with self._lock:
            session = self._require_session(game_id)
            player = session.players[user_id]
            player.disconnected = True
            await self._database.mark_player_disconnected(game_id, user_id, session.game_handle.guild_id)

    async def end_game(self, game_id: str, winner_faction: str | None, draw_reason: str | None = None) -> MatchHistoryRecord:
        async with self._lock:
            session = self._require_session(game_id)
            session.state = GameState.ENDED
            session.phase = GamePhase.CLEANUP
            session.winner_faction = winner_faction
            session.draw_reason = draw_reason
            history = MatchHistoryRecord(
                game_id=game_id,
                guild_id=session.game_handle.guild_id,
                winner_faction=winner_faction,
                duration_seconds=0,
                players=tuple(session.players),
                roles=dict(session.role_history),
                votes=dict(session.votes),
                deaths={
                    user_id: str(player.metadata.get("death_cause", "unknown"))
                    for user_id, player in session.players.items()
                    if not player.alive
                },
                mvp_user_id=None,
            )
            await self._database.upsert_game(
                GameRecord(
                    game_id=game_id,
                    guild_id=session.game_handle.guild_id,
                    channel_id=session.game_handle.channel_id,
                    host_id=session.game_handle.host_id,
                    state=session.state.value,
                    created_at=session.created_at,
                    ended_at=utcnow(),
                    winner_faction=winner_faction,
                    draw_reason=draw_reason,
                )
            )
            for user_id, player in session.players.items():
                await self._database.update_statistics_for_match(
                    user_id=user_id,
                    guild_id=session.game_handle.guild_id,
                    player_faction=player.faction,
                    winner_faction=winner_faction,
                )
            await self._database.save_match_history(history)
            self._sessions.pop(game_id, None)
            return history

    def _apply_votes(self, session: GameSession) -> None:
        if not session.votes:
            return
        tally: dict[int, int] = {}
        for target_id in session.votes.values():
            tally[target_id] = tally.get(target_id, 0) + 1
        if not tally:
            return
        target_id = max(tally, key=tally.get)
        if target_id in session.players:
            session.players[target_id].alive = False
            session.players[target_id].metadata["death_cause"] = "execution"

    def _evaluate_victory(self, session: GameSession) -> str | None:
        alive_factions = {
            player.faction
            for player in session.players.values()
            if player.alive and player.faction is not None
        }
        if not alive_factions:
            return "Draw"
        if alive_factions == {RoleFaction.HERO.value}:
            return RoleFaction.HERO.value
        if alive_factions == {RoleFaction.VILLAIN.value}:
            return RoleFaction.VILLAIN.value
        if len(alive_factions) == 1:
            return next(iter(alive_factions))
        return None

    def _require_session(self, game_id: str) -> GameSession:
        try:
            return self._sessions[game_id]
        except KeyError as exc:
            raise KeyError(f"Game session '{game_id}' does not exist.") from exc
