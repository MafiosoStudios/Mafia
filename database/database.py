from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any
import json
import logging

import aiosqlite

from config import GAME_DB_PATH, PLAYER_DB_PATH, STATS_DB_PATH
from database.models import (
    AchievementRecord,
    GamePlayerRecord,
    GameRecord,
    InventoryItemRecord,
    LeaderboardEntry,
    MatchHistoryRecord,
    PlayerProfileRecord,
    StatisticsRecord,
)

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages the project's SQLite databases with one async connection per file."""

    def __init__(self) -> None:
        self._database_paths: dict[str, Path] = {
            "players": PLAYER_DB_PATH,
            "games": GAME_DB_PATH,
            "stats": STATS_DB_PATH,
        }
        self._connections: dict[str, aiosqlite.Connection] = {}

    async def initialize(self) -> None:
        for name, path in self._database_paths.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            connection = await aiosqlite.connect(path)
            connection.row_factory = aiosqlite.Row
            await connection.execute("PRAGMA foreign_keys = ON;")
            await connection.execute("PRAGMA journal_mode = WAL;")
            await connection.execute("PRAGMA synchronous = NORMAL;")
            self._connections[name] = connection

        await self._create_schema()
        logger.info("Database layer initialized for %s databases.", len(self._connections))

    async def close(self) -> None:
        for connection in self._connections.values():
            await connection.commit()
            await connection.close()
        self._connections.clear()

    def connection(self, name: str) -> aiosqlite.Connection:
        try:
            return self._connections[name]
        except KeyError as exc:
            raise RuntimeError(f"Database connection '{name}' is not initialized.") from exc

    async def execute(
        self,
        database: str,
        query: str,
        parameters: tuple[Any, ...] = (),
    ) -> aiosqlite.Cursor:
        connection = self.connection(database)
        cursor = await connection.execute(query, parameters)
        await connection.commit()
        return cursor

    async def fetchone(
        self,
        database: str,
        query: str,
        parameters: tuple[Any, ...] = (),
    ) -> aiosqlite.Row | None:
        cursor = await self.connection(database).execute(query, parameters)
        return await cursor.fetchone()

    async def fetchall(
        self,
        database: str,
        query: str,
        parameters: tuple[Any, ...] = (),
    ) -> list[aiosqlite.Row]:
        cursor = await self.connection(database).execute(query, parameters)
        rows = await cursor.fetchall()
        return list(rows)

    @asynccontextmanager
    async def transaction(self, database: str) -> AsyncIterator[aiosqlite.Connection]:
        connection = self.connection(database)
        try:
            await connection.execute("BEGIN")
            yield connection
        except Exception:
            await connection.rollback()
            raise
        else:
            await connection.commit()

    async def upsert_player_profile(self, profile: PlayerProfileRecord) -> None:
        await self.execute(
            "players",
            """
            INSERT INTO players (
                user_id, guild_id, username, discriminator, level, xp, coins, rank,
                wins, losses, draws, games_played, favorite_character,
                most_played_character, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, guild_id) DO UPDATE SET
                username = excluded.username,
                discriminator = excluded.discriminator,
                level = excluded.level,
                xp = excluded.xp,
                coins = excluded.coins,
                rank = excluded.rank,
                wins = excluded.wins,
                losses = excluded.losses,
                draws = excluded.draws,
                games_played = excluded.games_played,
                favorite_character = excluded.favorite_character,
                most_played_character = excluded.most_played_character,
                updated_at = excluded.updated_at
            """,
            _profile_parameters(profile),
        )

    async def get_player_profile(
        self,
        user_id: int,
        guild_id: int,
    ) -> PlayerProfileRecord | None:
        row = await self.fetchone(
            "players",
            "SELECT * FROM players WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id),
        )
        return _row_to_profile(row) if row is not None else None

    async def upsert_statistics(self, statistics: StatisticsRecord) -> None:
        await self.execute(
            "stats",
            """
            INSERT INTO statistics (
                user_id, guild_id, games_played, wins, losses, draws, executions,
                night_kills, votes_cast, achievements_unlocked, mvp_titles
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, guild_id) DO UPDATE SET
                games_played = excluded.games_played,
                wins = excluded.wins,
                losses = excluded.losses,
                draws = excluded.draws,
                executions = excluded.executions,
                night_kills = excluded.night_kills,
                votes_cast = excluded.votes_cast,
                achievements_unlocked = excluded.achievements_unlocked,
                mvp_titles = excluded.mvp_titles
            """,
            _statistics_parameters(statistics),
        )

    async def update_statistics_for_match(
        self,
        user_id: int,
        guild_id: int,
        player_faction: str | None,
        winner_faction: str | None,
    ) -> StatisticsRecord:
        current = await self.get_statistics(user_id, guild_id)
        statistics = current or StatisticsRecord(user_id=user_id, guild_id=guild_id)

        games_played = statistics.games_played + 1
        if winner_faction is None or winner_faction == "Draw":
            wins = statistics.wins
            losses = statistics.losses
            draws = statistics.draws + 1
        elif player_faction == winner_faction:
            wins = statistics.wins + 1
            losses = statistics.losses
            draws = statistics.draws
        else:
            wins = statistics.wins
            losses = statistics.losses + 1
            draws = statistics.draws

        updated = StatisticsRecord(
            user_id=user_id,
            guild_id=guild_id,
            games_played=games_played,
            wins=wins,
            losses=losses,
            draws=draws,
            executions=statistics.executions,
            night_kills=statistics.night_kills,
            votes_cast=statistics.votes_cast,
            achievements_unlocked=statistics.achievements_unlocked,
            mvp_titles=statistics.mvp_titles,
        )
        await self.upsert_statistics(updated)
        await self.upsert_leaderboard_entry(
            "wins",
            LeaderboardEntry(user_id=user_id, guild_id=guild_id, metric="wins", value=updated.wins, rank=0),
        )
        await self.upsert_leaderboard_entry(
            "games_played",
            LeaderboardEntry(
                user_id=user_id,
                guild_id=guild_id,
                metric="games_played",
                value=updated.games_played,
                rank=0,
            ),
        )
        return updated

    async def get_statistics(self, user_id: int, guild_id: int) -> StatisticsRecord | None:
        row = await self.fetchone(
            "stats",
            "SELECT * FROM statistics WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id),
        )
        return _row_to_statistics(row) if row is not None else None

    async def upsert_game(self, game: GameRecord) -> None:
        await self.execute(
            "games",
            """
            INSERT INTO games (
                game_id, guild_id, channel_id, host_id, state, invite_code,
                is_private, min_players, max_players, created_at, started_at,
                ended_at, winner_faction, draw_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(game_id) DO UPDATE SET
                guild_id = excluded.guild_id,
                channel_id = excluded.channel_id,
                host_id = excluded.host_id,
                state = excluded.state,
                invite_code = excluded.invite_code,
                is_private = excluded.is_private,
                min_players = excluded.min_players,
                max_players = excluded.max_players,
                created_at = excluded.created_at,
                started_at = excluded.started_at,
                ended_at = excluded.ended_at,
                winner_faction = excluded.winner_faction,
                draw_reason = excluded.draw_reason
            """,
            _game_parameters(game),
        )

    async def upsert_game_player(self, player: GamePlayerRecord) -> None:
        await self.execute(
            "games",
            """
            INSERT INTO game_players (
                game_id, user_id, guild_id, character_key, faction, alive,
                disconnected, vote_weight, joined_at, eliminated_at, death_cause
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(game_id, user_id) DO UPDATE SET
                guild_id = excluded.guild_id,
                character_key = excluded.character_key,
                faction = excluded.faction,
                alive = excluded.alive,
                disconnected = excluded.disconnected,
                vote_weight = excluded.vote_weight,
                joined_at = excluded.joined_at,
                eliminated_at = excluded.eliminated_at,
                death_cause = excluded.death_cause
            """,
            _game_player_parameters(player),
        )

    async def mark_player_disconnected(self, game_id: str, user_id: int, guild_id: int) -> None:
        await self.execute(
            "games",
            """
            UPDATE game_players
            SET disconnected = 1
            WHERE game_id = ? AND user_id = ? AND guild_id = ?
            """,
            (game_id, user_id, guild_id),
        )

    async def delete_guild_data(self, guild_id: int) -> None:
        async with self.transaction("players"):
            await self.connection("players").execute("DELETE FROM unlocked_achievements WHERE guild_id = ?", (guild_id,))
            await self.connection("players").execute("DELETE FROM inventory WHERE guild_id = ?", (guild_id,))
            await self.connection("players").execute("DELETE FROM unlocked_characters WHERE guild_id = ?", (guild_id,))
            await self.connection("players").execute("DELETE FROM players WHERE guild_id = ?", (guild_id,))

        async with self.transaction("games"):
            await self.connection("games").execute("DELETE FROM game_players WHERE guild_id = ?", (guild_id,))
            await self.connection("games").execute("DELETE FROM match_history WHERE guild_id = ?", (guild_id,))
            await self.connection("games").execute("DELETE FROM games WHERE guild_id = ?", (guild_id,))

        async with self.transaction("stats"):
            await self.connection("stats").execute("DELETE FROM character_statistics WHERE guild_id = ?", (guild_id,))
            await self.connection("stats").execute("DELETE FROM statistics WHERE guild_id = ?", (guild_id,))
            await self.connection("stats").execute("DELETE FROM leaderboards WHERE guild_id = ?", (guild_id,))

    async def save_match_history(self, history: MatchHistoryRecord) -> None:
        await self.execute(
            "games",
            """
            INSERT INTO match_history (
                game_id, guild_id, winner_faction, duration_seconds, players,
                roles, votes, deaths, mvp_user_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(game_id) DO UPDATE SET
                guild_id = excluded.guild_id,
                winner_faction = excluded.winner_faction,
                duration_seconds = excluded.duration_seconds,
                players = excluded.players,
                roles = excluded.roles,
                votes = excluded.votes,
                deaths = excluded.deaths,
                mvp_user_id = excluded.mvp_user_id,
                created_at = excluded.created_at
            """,
            _match_history_parameters(history),
        )

    async def upsert_achievement(self, achievement: AchievementRecord) -> None:
        await self.execute(
            "players",
            """
            INSERT INTO achievements (
                achievement_key, name, description, requirement, icon, rarity
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(achievement_key) DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                requirement = excluded.requirement,
                icon = excluded.icon,
                rarity = excluded.rarity
            """,
            (
                achievement.achievement_key,
                achievement.name,
                achievement.description,
                achievement.requirement,
                achievement.icon,
                achievement.rarity,
            ),
        )

    async def unlock_achievement(self, user_id: int, guild_id: int, achievement_key: str) -> None:
        await self.execute(
            "players",
            """
            INSERT OR IGNORE INTO unlocked_achievements (
                user_id, guild_id, achievement_key, unlocked_at
            ) VALUES (?, ?, ?, ?)
            """,
            (user_id, guild_id, achievement_key, _timestamp_now()),
        )

    async def add_inventory_item(self, item: InventoryItemRecord) -> None:
        payload = json.dumps(item.cosmetic_payload or {}, separators=(",", ":"))
        await self.execute(
            "players",
            """
            INSERT INTO inventory (
                item_key, owner_id, guild_id, item_type, name, description,
                unlocked, quantity, cosmetic_payload, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(item_key, owner_id, guild_id) DO UPDATE SET
                item_type = excluded.item_type,
                name = excluded.name,
                description = excluded.description,
                unlocked = excluded.unlocked,
                quantity = excluded.quantity,
                cosmetic_payload = excluded.cosmetic_payload,
                created_at = excluded.created_at
            """,
            (
                item.item_key,
                item.owner_id,
                item.guild_id,
                item.item_type,
                item.name,
                item.description,
                int(item.unlocked),
                item.quantity,
                payload,
                item.created_at.isoformat(),
            ),
        )

    async def get_inventory_items(self, owner_id: int, guild_id: int) -> list[InventoryItemRecord]:
        rows = await self.fetchall(
            "players",
            """
            SELECT *
            FROM inventory
            WHERE owner_id = ? AND guild_id = ?
            ORDER BY created_at DESC
            """,
            (owner_id, guild_id),
        )
        return [_row_to_inventory_item(row) for row in rows]

    async def unlock_character(self, user_id: int, guild_id: int, character_key: str) -> None:
        await self.execute(
            "players",
            """
            INSERT OR IGNORE INTO unlocked_characters (
                user_id, guild_id, character_key, unlocked_at
            ) VALUES (?, ?, ?, ?)
            """,
            (user_id, guild_id, character_key, _timestamp_now()),
        )

    async def get_unlocked_characters(self, user_id: int, guild_id: int) -> list[str]:
        rows = await self.fetchall(
            "players",
            """
            SELECT character_key
            FROM unlocked_characters
            WHERE user_id = ? AND guild_id = ?
            ORDER BY unlocked_at DESC
            """,
            (user_id, guild_id),
        )
        return [str(row["character_key"]) for row in rows]

    async def add_cosmetic(self, cosmetic_key: str, name: str, cosmetic_type: str, description: str, payload: dict[str, Any], rarity: str = "Common") -> None:
        await self.execute(
            "players",
            """
            INSERT INTO cosmetics (
                cosmetic_key, name, cosmetic_type, description, payload, rarity
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(cosmetic_key) DO UPDATE SET
                name = excluded.name,
                cosmetic_type = excluded.cosmetic_type,
                description = excluded.description,
                payload = excluded.payload,
                rarity = excluded.rarity
            """,
            (cosmetic_key, name, cosmetic_type, description, json.dumps(payload, separators=(",", ":")), rarity),
        )

    async def list_cosmetics(self, cosmetic_type: str | None = None) -> list[dict[str, Any]]:
        if cosmetic_type is None:
            rows = await self.fetchall("players", "SELECT * FROM cosmetics ORDER BY rarity, name")
        else:
            rows = await self.fetchall(
                "players",
                "SELECT * FROM cosmetics WHERE cosmetic_type = ? ORDER BY rarity, name",
                (cosmetic_type,),
            )
        return [dict(row) for row in rows]

    async def get_leaderboard(
        self,
        database: str,
        metric: str,
        guild_id: int,
        limit: int = 10,
    ) -> list[LeaderboardEntry]:
        rows = await self.fetchall(
            database,
            """
            SELECT user_id, guild_id, metric, value, rank
            FROM leaderboards
            WHERE metric = ? AND guild_id = ?
            ORDER BY value DESC, user_id ASC
            LIMIT ?
            """,
            (metric, guild_id, limit),
        )
        return [
            _row_to_leaderboard_entry(row, index + 1)
            for index, row in enumerate(rows)
        ]

    async def upsert_leaderboard_entry(self, leaderboard_key: str, entry: LeaderboardEntry) -> None:
        await self.execute(
            "stats",
            """
            INSERT INTO leaderboards (
                leaderboard_key, user_id, guild_id, metric, value, rank, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(leaderboard_key, user_id, guild_id) DO UPDATE SET
                metric = excluded.metric,
                value = excluded.value,
                rank = excluded.rank,
                updated_at = excluded.updated_at
            """,
            (
                leaderboard_key,
                entry.user_id,
                entry.guild_id,
                entry.metric,
                entry.value,
                entry.rank,
                _timestamp_now(),
            ),
        )

    async def _create_schema(self) -> None:
        await self.connection("players").executescript(_PLAYERS_SCHEMA)
        await self.connection("games").executescript(_GAMES_SCHEMA)
        await self.connection("stats").executescript(_STATS_SCHEMA)
        await self.connection("players").commit()
        await self.connection("games").commit()
        await self.connection("stats").commit()


def _timestamp_now() -> str:
    return datetime.utcnow().isoformat()


def _profile_parameters(profile: PlayerProfileRecord) -> tuple[Any, ...]:
    return (
        profile.user_id,
        profile.guild_id,
        profile.username,
        profile.discriminator,
        profile.level,
        profile.xp,
        profile.coins,
        profile.rank,
        profile.wins,
        profile.losses,
        profile.draws,
        profile.games_played,
        profile.favorite_character,
        profile.most_played_character,
        profile.created_at.isoformat(),
        profile.updated_at.isoformat(),
    )


def _statistics_parameters(statistics: StatisticsRecord) -> tuple[Any, ...]:
    return (
        statistics.user_id,
        statistics.guild_id,
        statistics.games_played,
        statistics.wins,
        statistics.losses,
        statistics.draws,
        statistics.executions,
        statistics.night_kills,
        statistics.votes_cast,
        statistics.achievements_unlocked,
        statistics.mvp_titles,
    )


def _game_parameters(game: GameRecord) -> tuple[Any, ...]:
    return (
        game.game_id,
        game.guild_id,
        game.channel_id,
        game.host_id,
        game.state,
        game.invite_code,
        int(game.is_private),
        game.min_players,
        game.max_players,
        game.created_at.isoformat(),
        game.started_at.isoformat() if game.started_at is not None else None,
        game.ended_at.isoformat() if game.ended_at is not None else None,
        game.winner_faction,
        game.draw_reason,
    )


def _game_player_parameters(player: GamePlayerRecord) -> tuple[Any, ...]:
    return (
        player.game_id,
        player.user_id,
        player.guild_id,
        player.character_key,
        player.faction,
        int(player.alive),
        int(player.disconnected),
        player.vote_weight,
        player.joined_at.isoformat(),
        player.eliminated_at.isoformat() if player.eliminated_at is not None else None,
        player.death_cause,
    )


def _match_history_parameters(history: MatchHistoryRecord) -> tuple[Any, ...]:
    return (
        history.game_id,
        history.guild_id,
        history.winner_faction,
        history.duration_seconds,
        json.dumps(list(history.players), separators=(",", ":")),
        json.dumps(history.roles, separators=(",", ":")),
        json.dumps(history.votes, separators=(",", ":")),
        json.dumps(history.deaths, separators=(",", ":")),
        history.mvp_user_id,
        history.created_at.isoformat(),
    )


def _row_to_profile(row: aiosqlite.Row) -> PlayerProfileRecord:
    return PlayerProfileRecord(
        user_id=row["user_id"],
        guild_id=row["guild_id"],
        username=row["username"],
        discriminator=row["discriminator"],
        level=row["level"],
        xp=row["xp"],
        coins=row["coins"],
        rank=row["rank"],
        wins=row["wins"],
        losses=row["losses"],
        draws=row["draws"],
        games_played=row["games_played"],
        favorite_character=row["favorite_character"],
        most_played_character=row["most_played_character"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _row_to_statistics(row: aiosqlite.Row) -> StatisticsRecord:
    return StatisticsRecord(
        user_id=row["user_id"],
        guild_id=row["guild_id"],
        games_played=row["games_played"],
        wins=row["wins"],
        losses=row["losses"],
        draws=row["draws"],
        executions=row["executions"],
        night_kills=row["night_kills"],
        votes_cast=row["votes_cast"],
        achievements_unlocked=row["achievements_unlocked"],
        mvp_titles=row["mvp_titles"],
    )


def _row_to_leaderboard_entry(row: aiosqlite.Row, rank: int) -> LeaderboardEntry:
    return LeaderboardEntry(
        user_id=row["user_id"],
        guild_id=row["guild_id"],
        metric=row["metric"],
        value=row["value"],
        rank=rank,
    )


def _row_to_inventory_item(row: aiosqlite.Row) -> InventoryItemRecord:
    payload_raw = row["cosmetic_payload"]
    payload = json.loads(payload_raw) if payload_raw else None
    return InventoryItemRecord(
        item_key=row["item_key"],
        owner_id=row["owner_id"],
        guild_id=row["guild_id"],
        item_type=row["item_type"],
        name=row["name"],
        description=row["description"],
        unlocked=bool(row["unlocked"]),
        quantity=row["quantity"],
        cosmetic_payload=payload,
        created_at=datetime.fromisoformat(row["created_at"]),
    )


_PLAYERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
    user_id INTEGER NOT NULL,
    guild_id INTEGER NOT NULL,
    username TEXT NOT NULL,
    discriminator TEXT NOT NULL,
    level INTEGER NOT NULL DEFAULT 1,
    xp INTEGER NOT NULL DEFAULT 0,
    coins INTEGER NOT NULL DEFAULT 0,
    rank TEXT NOT NULL DEFAULT 'Bronze',
    wins INTEGER NOT NULL DEFAULT 0,
    losses INTEGER NOT NULL DEFAULT 0,
    draws INTEGER NOT NULL DEFAULT 0,
    games_played INTEGER NOT NULL DEFAULT 0,
    favorite_character TEXT,
    most_played_character TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, guild_id)
);

CREATE TABLE IF NOT EXISTS achievements (
    achievement_key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    requirement TEXT NOT NULL,
    icon TEXT,
    rarity TEXT NOT NULL DEFAULT 'Common'
);

CREATE TABLE IF NOT EXISTS unlocked_achievements (
    user_id INTEGER NOT NULL,
    guild_id INTEGER NOT NULL,
    achievement_key TEXT NOT NULL,
    unlocked_at TEXT NOT NULL,
    PRIMARY KEY (user_id, guild_id, achievement_key),
    FOREIGN KEY (achievement_key) REFERENCES achievements (achievement_key)
);

CREATE TABLE IF NOT EXISTS inventory (
    item_key TEXT NOT NULL,
    owner_id INTEGER NOT NULL,
    guild_id INTEGER NOT NULL,
    item_type TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    unlocked INTEGER NOT NULL DEFAULT 0,
    quantity INTEGER NOT NULL DEFAULT 1,
    cosmetic_payload TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (item_key, owner_id, guild_id)
);

CREATE TABLE IF NOT EXISTS unlocked_characters (
    user_id INTEGER NOT NULL,
    guild_id INTEGER NOT NULL,
    character_key TEXT NOT NULL,
    unlocked_at TEXT NOT NULL,
    PRIMARY KEY (user_id, guild_id, character_key)
);

CREATE TABLE IF NOT EXISTS cosmetics (
    cosmetic_key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    cosmetic_type TEXT NOT NULL,
    description TEXT NOT NULL,
    payload TEXT NOT NULL,
    rarity TEXT NOT NULL DEFAULT 'Common'
);
"""

_GAMES_SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    game_id TEXT PRIMARY KEY,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    host_id INTEGER NOT NULL,
    state TEXT NOT NULL,
    invite_code TEXT,
    is_private INTEGER NOT NULL DEFAULT 0,
    min_players INTEGER NOT NULL DEFAULT 5,
    max_players INTEGER NOT NULL DEFAULT 15,
    created_at TEXT NOT NULL,
    started_at TEXT,
    ended_at TEXT,
    winner_faction TEXT,
    draw_reason TEXT
);

CREATE TABLE IF NOT EXISTS game_players (
    game_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    guild_id INTEGER NOT NULL,
    character_key TEXT,
    faction TEXT,
    alive INTEGER NOT NULL DEFAULT 1,
    disconnected INTEGER NOT NULL DEFAULT 0,
    vote_weight INTEGER NOT NULL DEFAULT 1,
    joined_at TEXT NOT NULL,
    eliminated_at TEXT,
    death_cause TEXT,
    PRIMARY KEY (game_id, user_id),
    FOREIGN KEY (game_id) REFERENCES games (game_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS roles (
    role_key TEXT PRIMARY KEY,
    character_name TEXT NOT NULL,
    faction TEXT NOT NULL,
    win_condition TEXT NOT NULL,
    description TEXT NOT NULL,
    passive_ability TEXT NOT NULL,
    active_ability TEXT NOT NULL,
    priority INTEGER NOT NULL,
    cooldown INTEGER,
    is_unique INTEGER NOT NULL DEFAULT 1,
    tags TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS match_history (
    game_id TEXT PRIMARY KEY,
    guild_id INTEGER NOT NULL,
    winner_faction TEXT,
    duration_seconds INTEGER NOT NULL,
    players TEXT NOT NULL,
    roles TEXT NOT NULL,
    votes TEXT NOT NULL,
    deaths TEXT NOT NULL,
    mvp_user_id INTEGER,
    created_at TEXT NOT NULL
);
"""

_STATS_SCHEMA = """
CREATE TABLE IF NOT EXISTS statistics (
    user_id INTEGER NOT NULL,
    guild_id INTEGER NOT NULL,
    games_played INTEGER NOT NULL DEFAULT 0,
    wins INTEGER NOT NULL DEFAULT 0,
    losses INTEGER NOT NULL DEFAULT 0,
    draws INTEGER NOT NULL DEFAULT 0,
    executions INTEGER NOT NULL DEFAULT 0,
    night_kills INTEGER NOT NULL DEFAULT 0,
    votes_cast INTEGER NOT NULL DEFAULT 0,
    achievements_unlocked INTEGER NOT NULL DEFAULT 0,
    mvp_titles INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, guild_id)
);

CREATE TABLE IF NOT EXISTS character_statistics (
    user_id INTEGER NOT NULL,
    guild_id INTEGER NOT NULL,
    character_key TEXT NOT NULL,
    games_played INTEGER NOT NULL DEFAULT 0,
    wins INTEGER NOT NULL DEFAULT 0,
    losses INTEGER NOT NULL DEFAULT 0,
    eliminations INTEGER NOT NULL DEFAULT 0,
    assists INTEGER NOT NULL DEFAULT 0,
    favorite INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, guild_id, character_key)
);

CREATE TABLE IF NOT EXISTS leaderboards (
    leaderboard_key TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    guild_id INTEGER NOT NULL,
    metric TEXT NOT NULL,
    value INTEGER NOT NULL,
    rank INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (leaderboard_key, user_id, guild_id)
);
"""
