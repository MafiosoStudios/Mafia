from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True, frozen=True)
class PlayerProfileRecord:
    user_id: int
    guild_id: int
    username: str
    discriminator: str
    level: int = 1
    xp: int = 0
    coins: int = 0
    rank: str = "Bronze"
    wins: int = 0
    losses: int = 0
    draws: int = 0
    games_played: int = 0
    favorite_character: str | None = None
    most_played_character: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass(slots=True, frozen=True)
class RoleRecord:
    role_key: str
    character_name: str
    faction: str
    win_condition: str
    description: str
    passive_ability: str
    active_ability: str
    priority: int
    cooldown: int | None = None
    is_unique: bool = True
    tags: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class GameRecord:
    game_id: str
    guild_id: int
    channel_id: int
    host_id: int
    state: str
    invite_code: str | None = None
    is_private: bool = False
    min_players: int = 5
    max_players: int = 15
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    ended_at: datetime | None = None
    winner_faction: str | None = None
    draw_reason: str | None = None


@dataclass(slots=True, frozen=True)
class GamePlayerRecord:
    game_id: str
    user_id: int
    guild_id: int
    character_key: str | None = None
    faction: str | None = None
    alive: bool = True
    disconnected: bool = False
    vote_weight: int = 1
    joined_at: datetime = field(default_factory=datetime.utcnow)
    eliminated_at: datetime | None = None
    death_cause: str | None = None


@dataclass(slots=True, frozen=True)
class StatisticsRecord:
    user_id: int
    guild_id: int
    games_played: int = 0
    wins: int = 0
    losses: int = 0
    draws: int = 0
    executions: int = 0
    night_kills: int = 0
    votes_cast: int = 0
    achievements_unlocked: int = 0
    mvp_titles: int = 0


@dataclass(slots=True, frozen=True)
class CharacterStatisticsRecord:
    user_id: int
    guild_id: int
    character_key: str
    games_played: int = 0
    wins: int = 0
    losses: int = 0
    eliminations: int = 0
    assists: int = 0
    favorite: bool = False


@dataclass(slots=True, frozen=True)
class AchievementRecord:
    achievement_key: str
    name: str
    description: str
    requirement: str
    icon: str | None = None
    rarity: str = "Common"


@dataclass(slots=True, frozen=True)
class InventoryItemRecord:
    item_key: str
    owner_id: int
    guild_id: int
    item_type: str
    name: str
    description: str
    unlocked: bool = False
    quantity: int = 1
    cosmetic_payload: dict[str, Any] | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass(slots=True, frozen=True)
class MatchHistoryRecord:
    game_id: str
    guild_id: int
    winner_faction: str | None
    duration_seconds: int
    players: tuple[int, ...]
    roles: dict[int, str]
    votes: dict[int, int]
    deaths: dict[int, str]
    mvp_user_id: int | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass(slots=True, frozen=True)
class LeaderboardEntry:
    user_id: int
    guild_id: int
    metric: str
    value: int
    rank: int
