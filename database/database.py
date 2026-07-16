from __future__ import annotations

from dataclasses import asdict, fields as dataclass_fields
from datetime import datetime
from typing import Any
import logging
import os

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

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
    """Manages the project's data layer, backed by MongoDB Atlas.

    Every public method here keeps the exact name/signature it had in the
    SQLite version, so game_engine.py, lobby_system.py, cogs, etc. do not
    need to change at all.

    NOTE: the old raw-SQL helpers (`execute`, `fetchone`, `fetchall`,
    `connection`, `transaction`) are intentionally gone -- there's no SQL
    to run against Mongo. If any cog called those directly, that call site
    needs a small rewrite (ask me and I'll fix it once I see it).
    """

    def __init__(self) -> None:
        self._client: AsyncIOMotorClient | None = None
        self._db: AsyncIOMotorDatabase | None = None
        self._global_db: AsyncIOMotorDatabase | None = None

    async def initialize(self) -> None:
        uri = os.getenv("MONGODB_URI")
        if not uri:
            raise RuntimeError(
                "MONGODB_URI is not set. Add it to your .env file, e.g. "
                "MONGODB_URI=mongodb+srv://user:pass@cluster.mongodb.net"
            )
        db_name = os.getenv("MONGODB_DB_NAME", "anime_mafia")

        self._client = AsyncIOMotorClient(uri)
        self._db = self._client[db_name]
        self._global_db = self._client[f"{db_name}_global"]

        # Fail fast on bad credentials/network instead of failing on first query.
        await self._client.admin.command("ping")

        await self._create_indexes()
        logger.info("Database layer initialized against MongoDB Atlas. Local: '%s', Global: '%s_global'", db_name, db_name)

    async def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
            self._db = None
            self._global_db = None

    @property
    def db(self) -> AsyncIOMotorDatabase:
        if self._db is None:
            raise RuntimeError("DatabaseManager.initialize() has not been awaited yet.")
        return self._db

    @property
    def global_db(self) -> AsyncIOMotorDatabase:
        if self._global_db is None:
            raise RuntimeError("DatabaseManager.initialize() has not been awaited yet.")
        return self._global_db

    # ---- Player profiles ---------------------------------------------------

    async def upsert_player_profile(self, profile: PlayerProfileRecord) -> None:
        await self.global_db.players.update_one(
            {"user_id": profile.user_id},
            {"$set": asdict(profile)},
            upsert=True,
        )

    async def get_player_profile(self, user_id: int, guild_id: int | None = None) -> PlayerProfileRecord | None:
        doc = await self.global_db.players.find_one({"user_id": user_id})
        return _doc_to_dataclass(PlayerProfileRecord, doc) if doc else None

    # ---- Statistics ---------------------------------------------------------

    async def upsert_statistics(self, statistics: StatisticsRecord) -> None:
        await self.global_db.statistics.update_one(
            {"user_id": statistics.user_id},
            {"$set": asdict(statistics)},
            upsert=True,
        )

    async def update_statistics_for_match(
        self,
        user_id: int,
        guild_id: int | None,
        player_faction: str | None,
        winner_faction: str | None,
    ) -> StatisticsRecord:
        current = await self.get_statistics(user_id)
        statistics = current or StatisticsRecord(user_id=user_id)

        games_played = statistics.games_played + 1
        if winner_faction is None or winner_faction == "Draw":
            wins, losses, draws = statistics.wins, statistics.losses, statistics.draws + 1
        elif player_faction == winner_faction:
            wins, losses, draws = statistics.wins + 1, statistics.losses, statistics.draws
        else:
            wins, losses, draws = statistics.wins, statistics.losses + 1, statistics.draws

        updated = StatisticsRecord(
            user_id=user_id,
            guild_id=0,
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
            LeaderboardEntry(user_id=user_id, guild_id=0, metric="wins", value=updated.wins, rank=0),
        )
        await self.upsert_leaderboard_entry(
            "games_played",
            LeaderboardEntry(
                user_id=user_id,
                guild_id=0,
                metric="games_played",
                value=updated.games_played,
                rank=0,
            ),
        )
        return updated

    async def get_statistics(self, user_id: int, guild_id: int | None = None) -> StatisticsRecord | None:
        doc = await self.global_db.statistics.find_one({"user_id": user_id})
        return _doc_to_dataclass(StatisticsRecord, doc) if doc else None

    # ---- Games ---------------------------------------------------------------

    async def upsert_game(self, game: GameRecord) -> None:
        await self.db.games.update_one(
            {"game_id": game.game_id},
            {"$set": asdict(game)},
            upsert=True,
        )

    async def upsert_game_player(self, player: GamePlayerRecord) -> None:
        await self.db.game_players.update_one(
            {"game_id": player.game_id, "user_id": player.user_id},
            {"$set": asdict(player)},
            upsert=True,
        )

    async def mark_player_disconnected(self, game_id: str, user_id: int, guild_id: int) -> None:
        await self.db.game_players.update_one(
            {"game_id": game_id, "user_id": user_id, "guild_id": guild_id},
            {"$set": {"disconnected": True}},
        )

    async def delete_guild_data(self, guild_id: int) -> None:
        await self.db.game_players.delete_many({"guild_id": guild_id})
        await self.db.match_history.delete_many({"guild_id": guild_id})
        await self.db.games.delete_many({"guild_id": guild_id})
        await self.db.settings.delete_many({"guild_id": guild_id})
        await self.db.custom_role_lists.delete_many({"guild_id": guild_id})

    async def save_match_history(self, history: MatchHistoryRecord) -> None:
        # dict keys must be strings in BSON, so int-keyed dicts get stringified
        # on the way in and restored to int keys on the way out.
        doc = {
            "game_id": history.game_id,
            "guild_id": history.guild_id,
            "winner_faction": history.winner_faction,
            "duration_seconds": history.duration_seconds,
            "players": list(history.players),
            "roles": {str(k): v for k, v in history.roles.items()},
            "votes": {str(k): v for k, v in history.votes.items()},
            "deaths": {str(k): v for k, v in history.deaths.items()},
            "mvp_user_id": history.mvp_user_id,
            "created_at": history.created_at,
        }
        await self.db.match_history.update_one(
            {"game_id": history.game_id}, {"$set": doc}, upsert=True
        )

    async def get_match_history(self, game_id: str) -> MatchHistoryRecord | None:
        doc = await self.db.match_history.find_one({"game_id": game_id})
        if doc is None:
            return None
        return MatchHistoryRecord(
            game_id=doc["game_id"],
            guild_id=doc["guild_id"],
            winner_faction=doc["winner_faction"],
            duration_seconds=doc["duration_seconds"],
            players=tuple(doc["players"]),
            roles={int(k): v for k, v in doc["roles"].items()},
            votes={int(k): v for k, v in doc["votes"].items()},
            deaths={int(k): v for k, v in doc["deaths"].items()},
            mvp_user_id=doc["mvp_user_id"],
            created_at=doc["created_at"],
        )

    # ---- Achievements ---------------------------------------------------------

    async def upsert_achievement(self, achievement: AchievementRecord) -> None:
        await self.global_db.achievements.update_one(
            {"achievement_key": achievement.achievement_key},
            {"$set": asdict(achievement)},
            upsert=True,
        )

    async def unlock_achievement(self, user_id: int, guild_id: int | None, achievement_key: str) -> None:
        await self.global_db.unlocked_achievements.update_one(
            {"user_id": user_id, "achievement_key": achievement_key},
            {"$setOnInsert": {"unlocked_at": datetime.utcnow()}},
            upsert=True,
        )

    # ---- Inventory ---------------------------------------------------------

    async def add_inventory_item(self, item: InventoryItemRecord) -> None:
        await self.global_db.inventory.update_one(
            {"item_key": item.item_key, "owner_id": item.owner_id},
            {"$set": asdict(item)},
            upsert=True,
        )

    async def get_inventory_items(self, owner_id: int, guild_id: int | None = None) -> list[InventoryItemRecord]:
        cursor = self.global_db.inventory.find({"owner_id": owner_id}).sort(
            "created_at", -1
        )
        return [_doc_to_dataclass(InventoryItemRecord, doc) async for doc in cursor]

    # ---- Characters ---------------------------------------------------------

    async def unlock_character(self, user_id: int, guild_id: int | None, character_key: str) -> None:
        await self.global_db.unlocked_characters.update_one(
            {"user_id": user_id, "character_key": character_key},
            {"$setOnInsert": {"unlocked_at": datetime.utcnow()}},
            upsert=True,
        )

    async def get_unlocked_characters(self, user_id: int, guild_id: int | None = None) -> list[str]:
        cursor = self.global_db.unlocked_characters.find(
            {"user_id": user_id}
        ).sort("unlocked_at", -1)
        return [doc["character_key"] async for doc in cursor]

    # ---- Cosmetics ---------------------------------------------------------

    async def add_cosmetic(
        self,
        cosmetic_key: str,
        name: str,
        cosmetic_type: str,
        description: str,
        payload: dict[str, Any],
        rarity: str = "Common",
    ) -> None:
        await self.global_db.cosmetics.update_one(
            {"cosmetic_key": cosmetic_key},
            {
                "$set": {
                    "cosmetic_key": cosmetic_key,
                    "name": name,
                    "cosmetic_type": cosmetic_type,
                    "description": description,
                    "payload": payload,
                    "rarity": rarity,
                }
            },
            upsert=True,
        )

    async def list_cosmetics(self, cosmetic_type: str | None = None) -> list[dict[str, Any]]:
        query = {} if cosmetic_type is None else {"cosmetic_type": cosmetic_type}
        cursor = self.global_db.cosmetics.find(query).sort([("rarity", 1), ("name", 1)])
        return [_strip_id(doc) async for doc in cursor]

    # ---- Leaderboards ---------------------------------------------------------

    async def get_leaderboard(
        self,
        database: str,
        metric: str,
        guild_id: int | None = None,
        limit: int = 10,
    ) -> list[LeaderboardEntry]:
        cursor = (
            self.global_db.leaderboards.find({"metric": metric})
            .sort([("value", -1), ("user_id", 1)])
            .limit(limit)
        )
        entries: list[LeaderboardEntry] = []
        async for doc in cursor:
            entries.append(
                LeaderboardEntry(
                    user_id=doc["user_id"],
                    guild_id=0,
                    metric=doc["metric"],
                    value=doc["value"],
                    rank=len(entries) + 1,
                )
            )
        return entries

    async def upsert_leaderboard_entry(self, leaderboard_key: str, entry: LeaderboardEntry) -> None:
        await self.global_db.leaderboards.update_one(
            {
                "leaderboard_key": leaderboard_key,
                "user_id": entry.user_id,
            },
            {
                "$set": {
                    "leaderboard_key": leaderboard_key,
                    "user_id": entry.user_id,
                    "metric": entry.metric,
                    "value": entry.value,
                    "rank": entry.rank,
                    "updated_at": datetime.utcnow(),
                }
            },
            upsert=True,
        )

    async def get_guild_settings(self, guild_id: int) -> dict[str, Any]:
        doc = await self.db.settings.find_one({"guild_id": guild_id})
        defaults = {
            "night_duration": 90,
            "day_duration": 120,
            "vote_duration": 60,
            "plea_duration": 60,
            "verdict_duration": 30,
            "anonymous_voting": True,
        }
        if doc and "settings" in doc:
            defaults.update(doc["settings"])
        return defaults

    async def update_guild_setting(self, guild_id: int, key: str, value: Any) -> None:
        await self.db.settings.update_one(
            {"guild_id": guild_id},
            {"$set": {f"settings.{key}": value}},
            upsert=True,
        )

    # ---- Active Game Recovery -----------------------------------------------

    async def save_active_game_state(self, game_id: str, state_dict: dict[str, Any]) -> None:
        await self.db.games.update_one(
            {"game_id": game_id},
            {"$set": {"active_state": state_dict}},
            upsert=True
        )

    async def load_active_game_state(self, game_id: str) -> dict[str, Any] | None:
        doc = await self.db.games.find_one({"game_id": game_id})
        return doc.get("active_state") if doc else None

    async def get_active_game_by_guild(self, guild_id: int) -> dict[str, Any] | None:
        doc = await self.db.games.find_one({"active_state.game_handle.guild_id": guild_id})
        return doc.get("active_state") if doc else None

    async def clear_active_game_state(self, game_id: str) -> None:
        await self.db.games.update_one(
            {"game_id": game_id},
            {"$unset": {"active_state": ""}}
        )

    # ---- Custom Role Lists --------------------------------------------------

    async def save_custom_role_list(self, guild_id: int, name: str, roles: list[str]) -> None:
        await self.db.custom_role_lists.update_one(
            {"guild_id": guild_id, "name": name},
            {"$set": {
                "guild_id": guild_id,
                "name": name,
                "roles": roles,
                "updated_at": datetime.utcnow()
            }},
            upsert=True
        )

    async def load_custom_role_list(self, guild_id: int, name: str) -> list[str] | None:
        doc = await self.db.custom_role_lists.find_one({"guild_id": guild_id, "name": name})
        return doc["roles"] if doc else None

    async def delete_custom_role_list(self, guild_id: int, name: str) -> bool:
        res = await self.db.custom_role_lists.delete_one({"guild_id": guild_id, "name": name})
        return res.deleted_count > 0

    async def list_custom_role_lists(self, guild_id: int) -> list[dict[str, Any]]:
        cursor = self.db.custom_role_lists.find({"guild_id": guild_id}).sort("name", 1)
        return [{"name": doc["name"], "roles": doc["roles"]} async for doc in cursor]

    # ---- Indexes ---------------------------------------------------------

    async def _create_indexes(self) -> None:
        # Transient DB
        await self.db.games.create_index("game_id", unique=True)
        await self.db.game_players.create_index([("game_id", 1), ("user_id", 1)], unique=True)
        await self.db.match_history.create_index("game_id", unique=True)
        await self.db.settings.create_index("guild_id", unique=True)
        await self.db.custom_role_lists.create_index([("guild_id", 1), ("name", 1)], unique=True)

        # Global DB
        await self.global_db.players.create_index("user_id", unique=True)
        await self.global_db.achievements.create_index("achievement_key", unique=True)
        await self.global_db.unlocked_achievements.create_index(
            [("user_id", 1), ("achievement_key", 1)], unique=True
        )
        await self.global_db.inventory.create_index(
            [("item_key", 1), ("owner_id", 1)], unique=True
        )
        await self.global_db.unlocked_characters.create_index(
            [("user_id", 1), ("character_key", 1)], unique=True
        )
        await self.global_db.cosmetics.create_index("cosmetic_key", unique=True)
        await self.global_db.statistics.create_index("user_id", unique=True)
        await self.global_db.character_statistics.create_index(
            [("user_id", 1), ("character_key", 1)], unique=True
        )
        await self.global_db.leaderboards.create_index(
            [("leaderboard_key", 1), ("user_id", 1)], unique=True
        )


def _strip_id(doc: dict[str, Any]) -> dict[str, Any]:
    doc = dict(doc)
    doc.pop("_id", None)
    return doc


def _doc_to_dataclass(cls: type, doc: dict[str, Any]) -> Any:
    doc = _strip_id(doc)
    valid_fields = {f.name for f in dataclass_fields(cls)}
    return cls(**{k: v for k, v in doc.items() if k in valid_fields})