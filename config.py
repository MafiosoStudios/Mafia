from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


PROJECT_ROOT = Path(__file__).resolve().parent
DATABASE_DIR = PROJECT_ROOT / "db"
ASSETS_DIR = PROJECT_ROOT / "assets"
ROLES_ASSETS_DIR = ASSETS_DIR / "roles"

PLAYER_DB_PATH = DATABASE_DIR / "players.sqlite"
GAME_DB_PATH = DATABASE_DIR / "games.sqlite"
STATS_DB_PATH = DATABASE_DIR / "stats.sqlite"


@dataclass(slots=True, frozen=True)
class BotConfig:
    token: str
    command_prefix: str = "!"
    min_players: int = 5
    max_players: int = 15
    lobby_timeout_seconds: int = 300
    night_timeout_seconds: int = 120
    day_timeout_seconds: int = 180
    lobby_leader_bypass_role_ids: tuple[int, ...] = ()

    @classmethod
    def from_env(cls) -> "BotConfig":
        return cls(
            token=os.getenv("DISCORD_TOKEN", ""),
            command_prefix=os.getenv("COMMAND_PREFIX", "!"),
            min_players=int(os.getenv("MIN_PLAYERS", "5")),
            max_players=int(os.getenv("MAX_PLAYERS", "15")),
            lobby_timeout_seconds=int(os.getenv("LOBBY_TIMEOUT_SECONDS", "300")),
            night_timeout_seconds=int(os.getenv("NIGHT_TIMEOUT_SECONDS", "120")),
            day_timeout_seconds=int(os.getenv("DAY_TIMEOUT_SECONDS", "180")),
            lobby_leader_bypass_role_ids=_parse_int_tuple(os.getenv("LOBBY_LEADER_BYPASS_ROLE_IDS", "")),
        )


def _parse_int_tuple(value: str) -> tuple[int, ...]:
    if not value.strip():
        return ()
    return tuple(int(item.strip()) for item in value.split(",") if item.strip())


EMOJIS: dict[str, str] = {
    # Factions
    "Hero": "🛡️",
    "Villain": "🩸",
    "Neutral": "🎭",

    # Roles
    "doctor_tenma": "🩺",
    "ayanokoji_kiyotaka": "🧠",
    "l": "🕵️",
    "blackbeard": "🌋",
    "light_yagami": "📓",
    "muzan_kibutsuji": "👹",
    "makima": "👁️",
    "orochimaru": "🐍",
    "hisoka": "🃏",
    "gilgamesh": "🔱",
    "lelouch_lamperouge": "👑",
    "eren_jaeger": "🕊️",
    "mahoraga": "🌀",
    "villager": "🧑",
    "demon": "👿",
    "lower_moon": "🌙",
    "upper_moon": "💀",
    "default_villain": "👤",

    # System / UI elements
    "death": "💀",
    "alive": "🟢",
    "night": "🌙",
    "day": "☀️",
    "trial": "⚖️",
    "vote": "🗳️",
    "verdict": "🔨",
    "victory": "🏆",
    "warning": "⚠️",
    "lobby": "🎮",
    "clock": "⏰",
    "check": "✅",
    "peace": "🕊️",
    "chat": "💬",
    "draw": "🤝",
}


def get_emoji(key: str) -> str:
    """Returns the configured emoji for the given key, falling back to an empty string or default if not found."""
    return EMOJIS.get(key, "")

