from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import random


PROJECT_ROOT = Path(__file__).resolve().parent
DATABASE_DIR = PROJECT_ROOT / "db"
ASSETS_DIR = PROJECT_ROOT / "assets"
ROLES_ASSETS_DIR = ASSETS_DIR / "roles"

PLAYER_DB_PATH = DATABASE_DIR / "players.sqlite"
GAME_DB_PATH = DATABASE_DIR / "games.sqlite"
STATS_DB_PATH = DATABASE_DIR / "stats.sqlite"


ADMIN_IDS: set[int] = {839182501091344444, 744831273406824449}



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


# =============================================================================
# EMOJIS — every emoji used anywhere in the bot is defined here. Nothing is
# hardcoded in game logic or UI files; everything calls get_emoji("key").
# Swap any value for a custom Discord emoji string (e.g. "<:name:id>" or
# "<a:name:id>" for animated) once you have your own emoji assets uploaded.
# =============================================================================
EMOJIS: dict[str, str] = {
    # Factions
    "Hero": "🛡️",
    "Villain": "🩸",
    "Protagonist": "🛡️",
    "Antagonist": "🩸",
    "Neutral": "🎭",

    # Roles
    "doctor_tenma": "🩺",
    "ayanokoji_kiyotaka": "🧠",
    "l": "🕵️",
    "blackbeard": "🌋",
    "light_yagami": "📓",
    "muzan_kibutsuji": "👹",
    "makima": "👁️",
    "hisoka": "🃏",
    "gilgamesh": "🔱",
    "eren_jaeger": "🕊️",
    "mahoraga": "🌀",
    "villager": "🧑",
    "demon": "👿",
    "lower_moon": "🌙",
    "upper_moon": "💀",
    "goon_lord": "👤",
    "tobirama_senju": "🌊",
    "hiromi_higuruma": "⚖️",
    "levi_ackerman": "⚔️",
    "maomao": "🧪",
    "frieren": "✨",

    # Role categories (used for role-reveal / role-list UI)
    "category_protective": "🩹",
    "category_investigative": "🔍",
    "category_council": "🏛️",
    "category_utility": "🧰",
    "category_killing": "🗡️",
    "category_deception": "🎭",
    "category_control": "🕹️",
    "category_neutral": "🎲",

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
    "cross": "❌",
    "peace": "🕊️",
    "chat": "💬",
    "draw": "🤝",
    "target": "🎯",
    "zap": "⚡",
    "group": "👥",
    "settings": "⚙️",
    "search": "🔎",
    "shield": "🛡️",
    "sword": "⚔️",
    "join": "➕",
    "leave": "➖",
    "crown": "👑",
    "skull": "☠️",
    "inactive": "💤",
}


def get_emoji(key: str) -> str:
    """Returns the configured emoji for the given key, falling back to an empty string if not found."""
    return EMOJIS.get(key, "")


# =============================================================================
# MEDIA — thumbnails / banners / gifs used across embeds. All fully optional:
# leave a value as "" to skip it. Point these at your own CDN/Discord CDN
# links once you have art assets; nothing else in the codebase needs to change.
# =============================================================================
ROLE_IMAGES: dict[str, str] = {
    # role_key -> thumbnail image URL shown on role-reveal DMs / role info embeds
}

EVENT_IMAGES: dict[str, str] = {
    # event key -> banner image/gif URL shown in the big phase-transition embeds
    "lobby": "https://64.media.tumblr.com/f2386762aac81419a3decc778f2e297b/a0df0d9c512e5ce7-d8/s1280x1920/6480417570fc98118a1b7ab0ef3b92cf75ac555e.png",
    "rules": "https://gifdb.com/images/thumbnail/vinland-saga-thorfinn-windy-avx39h7njdsilwic.gif",
    "match_start": "",
    "night": "https://img.magnific.com/premium-photo/nighttime-scene-farm-with-barn-tree_1034062-92937.jpg?semt=ais_test_b&w=740&q=80",
    "day": "",
    "trial": "https://i.pinimg.com/originals/47/56/f5/4756f512ea5c34641e9aa005699f978c.jpg",
    "verdict": "https://www.voicesinthevoid.com/wp-content/uploads/2026/02/Higuruma-in-the-courtroom-in-Jujutsu-kaisen-Season-3.jpg",
    "death": "https://i.kym-cdn.com/entries/icons/facebook/000/029/198/Dark_Souls_You_Died_Screen_-_Completely_Black_Screen_0-2_screenshot.jpg",
    "victory_hero": "https://media1.giphy.com/media/v1.Y2lkPTZjMDliOTUyODdzc24ydDAzb2lhY3l0MWhuam4ycm83NDRyY3UxZ295dzlldThkMCZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/nhFvzFSWaoDy4VZm2W/giphy.gif",
    "victory_villain": "",
    "victory_neutral": "",
    "draw": "",
}


def get_role_image(role_key: str) -> str | None:
    """Returns the configured thumbnail URL for a role, checking roles.json fallback."""
    url = ROLE_IMAGES.get(role_key or "", "")
    if url:
        return url
    try:
        import roles
        meta = roles.ROLES_METADATA.get(role_key or "", {})
        url = meta.get("image_url", "")
        if url:
            return url
    except Exception:
        pass
    return None


def get_event_image(event_key: str) -> str | None:
    """Returns the configured banner/gif URL for an event, or None if not set."""
    url = EVENT_IMAGES.get(event_key, "")
    return url or None


# =============================================================================
# DEATH MESSAGES — flavor text shown when a player dies. Fully data-driven so
# adding a new role's kill only means adding an entry here, never touching
# game_engine.py. Each key is a "kill source" tag set by a role's night_action
# (e.g. roles/mafia.py sets "mafia_strike"); each value is a list of possible
# lines and one is picked at random for variety. Use {player} as a placeholder.
# Any source tag without an entry here automatically falls back to
# GENERIC_DEATH_MESSAGES, so new roles never "break" and always show *some*
# flavor text instead of silently reusing one hardcoded fallback line.
# =============================================================================
DEATH_MESSAGES: dict[str, list[str]] = {
    "mafia_strike": [
        "**{player}** was cornered in the dark and struck down by the Mafia.",
        "**{player}** never saw the blade coming. The Mafia claimed another life.",
        "**{player}** was found lifeless — the Mafia's mark left behind.",
    ],
    "demon_strike": [
        "**{player}** was torn apart by a demon's claws in the night.",
        "**{player}** let out a scream before a demon silenced them forever.",
        "**{player}** was hunted down and devoured under the moonlight.",
    ],
    "light_guess": [
        "**{player}**'s true identity was written in the Death Note — their heart gave out instantly.",
        "**{player}** clutched their chest and collapsed. Kira's judgment was absolute.",
    ],
    "devils_pen_kill": [
        "**{player}**'s name had been written three nights ago. Right on schedule, their heart stopped.",
        "**{player}** succumbed to a curse written in ink days ago — the Devil's Pen never misses.",
    ],
    "gates_of_babylon": [
        "**{player}** was obliterated in a hailstorm of a thousand golden blades.",
        "**{player}** stood no chance against the King of Heroes' treasury unleashed.",
    ],
    "hisoka_nen_kill": [
        "**{player}** felt Bungee Gum snap tight around their throat — Hisoka's Post-Mortem Nen struck true.",
        "**{player}** was ambushed by a magician who should have already been dead.",
    ],
    "rumbling": [
        "**{player}** was crushed beneath the unstoppable march of the Rumbling.",
        "**{player}** had nowhere to run as the Titans closed in.",
    ],
    "darkness": [
        "**{player}** vanished into an inescapable darkness, never to be seen again.",
    ],
    "execution": [
        "**{player}** was lynched by the town's judgment.",
    ],
    "declared_peace": [
        "**{player}** chose to step down peacefully.",
    ],
    "levi_kill": [
        "**{player}** was sliced to pieces by Levi Ackerman's dual blades.",
        "**{player}** stood no chance against the Humanity's Strongest Soldier's ODM execution.",
    ],
    "deadly_sentencing": [
        "**{player}** was immediately sentenced to execution by Hiromi Higuruma.",
    ],
    "wrongful_judgment": [
        "**{player}** wrongfully prosecuted a town member and was executed by the Hangman for their judgment.",
    ],
}

# Generic fallback lines used when a death has no specific source tag mapped above.
GENERIC_DEATH_MESSAGES: list[str] = [
    "**{player}** was found dead.",
    "**{player}** did not survive the night.",
    "**{player}** was eliminated during the night.",
]

# Sent (via DM) to alive players who took no night action at all — e.g. no
# ability, roleblocked with nothing to report, or simply chose not to act.
NIGHT_INACTION_MESSAGES: list[str] = [
    "The night passed quietly for you. Nothing to report.",
    "You kept a low profile through the night. No action was taken.",
    "Nothing happened on your end tonight — stay alert for tomorrow.",
]


def get_death_message(cause_key: str | None, player_name: str) -> str:
    """Looks up a flavored death line for the given cause tag, falling back to a generic one."""
    pool = DEATH_MESSAGES.get(cause_key or "", None) or GENERIC_DEATH_MESSAGES
    template = random.choice(pool)
    return template.format(player=player_name)


def get_inaction_message() -> str:
    return random.choice(NIGHT_INACTION_MESSAGES)


# =============================================================================
# CHANNEL / CATEGORY NAMING — used when the bot spins up a temporary category
# + text channel for each match. Both are deleted together when the game ends.
# =============================================================================
GAME_CATEGORY_NAME_TEMPLATE = "🎭 Mafia Match {game_id}"
GAME_CHANNEL_NAME_TEMPLATE = "mafia-{game_id}"
