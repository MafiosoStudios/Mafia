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
    command_prefix: str = ","
    min_players: int = 5
    max_players: int = 15
    lobby_timeout_seconds: int = 300
    night_timeout_seconds: int = 120
    day_timeout_seconds: int = 180
    lobby_leader_bypass_role_ids: tuple[int, ...] = ()

    @classmethod
    def from_env(cls) -> "BotConfig":
        # Validate token first
        token = os.getenv("DISCORD_TOKEN", "")
        if not token or not token.strip():
            raise RuntimeError(
                "DISCORD_TOKEN environment variable is required but not set.\n"
                "Please create a .env file with DISCORD_TOKEN=your_bot_token_here"
            )

        # Parse integer config values with validation
        def _parse_int_env(key: str, default: str, min_val: int = 1, max_val: int = 10000) -> int:
            try:
                value = int(os.getenv(key, default))
                if not (min_val <= value <= max_val):
                    raise ValueError(f"{key} must be between {min_val} and {max_val}, got {value}")
                return value
            except ValueError as e:
                raise RuntimeError(f"Invalid {key} configuration: {e}")

        return cls(
            token=token.strip(),
            command_prefix=os.getenv("COMMAND_PREFIX", ","),
            min_players=_parse_int_env("MIN_PLAYERS", "5", min_val=2, max_val=50),
            max_players=_parse_int_env("MAX_PLAYERS", "15", min_val=2, max_val=50),
            lobby_timeout_seconds=_parse_int_env("LOBBY_TIMEOUT_SECONDS", "300", min_val=30, max_val=3600),
            night_timeout_seconds=_parse_int_env("NIGHT_TIMEOUT_SECONDS", "120", min_val=30, max_val=3600),
            day_timeout_seconds=_parse_int_env("DAY_TIMEOUT_SECONDS", "180", min_val=30, max_val=3600),
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
    "Hero": "<:protagonist:1527264556697780304>",
    "Villain": "<:antagonist:1527264705838846105>",
    "Protagonist": "<:protagonist:1527264556697780304>",
    "Antagonist": "<:antagonist:1527264705838846105>",
    "Neutral": "<:neutral:1527264748217962637>",

    # Roles
    "doctor_tenma": "<:tenma:1527169096481902762>",
    "ayanokoji_kiyotaka": "<:ayanokoji:1527168724233097246>",
    "l": "<:L_:1527176987473477774>",
    "blackbeard": "<:blackbeard:1527265466777600000>",
    "light_yagami": "<:light:1527265685091385455>",
    "muzan_kibutsuji": "<:muzan:1527265283956408320>",
    "makima": "<:makima:1527265391146176622>",
    "hisoka": "<:hisoka:1527265824782422106>",
    "gilgamesh": "<:gilgamesh:1527266223593750680>",
    "eren_jaeger": "<:eren:1527265746260983838>",
    "mahoraga": "<:mahoraga:1527266009776394320>",
    "villager": "🧑",
    "demon": "👿",
    "lower_moon": "🌙",
    "upper_moon": "💀",
    "frieza": "<:freiza:1527179281812160695>",
    "antagonist_base_killer": "<:antagonist:1527264705838846105>",
    "tobirama_senju": "<:tobirama:1527169451383066736>",
    "hiromi_higuruma": "<:higuruma:1527177235667353690>",
    "levi_ackerman": "<:levi:1527168891904856085>",
    "maomao": "<:maomao:1527176838424825959>",
    "frieren": "<:frieren:1527177319171625081>",
    "kishibe": "<:kishibe:1527177158571855902>",
    "tosen": "<:tosen:1527177472561385572>",
    "dazai": "<:osamu:1527178345484259338>",
    "asta": "<:asta:1527177095292129352>",
    "lelouch": "<:lelouch:1527266110339285093>",

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
    "save": "💾",
    "trash": "🗑️",
    "back": "◀️",
    "roster": "🎭",
    "book": "📖",
    "star": "⭐",
    "coin": "🪙",
    "dna": "🧬",
    "fire": "🔥",
    "pushpin": "📌",
    "moneybag": "💰",
    "sun": "☀️",
    "milky_way": "🌌",
    "card": "🎴",
    "bag": "🎒",
    "level": "📈",
    "next": "▶️",
    "prev": "◀️",
    "package": "📦",
    "refresh": "🔄",
    "ban": "🔨",
    "download": "📥",
    "empty": "📭",
    "link": "🔗",
    "court": "🏛️",
    "trial": "⚖️",
    "meteor": "☄️",
    "detective": "🕵️‍♂️",
    "wave": "🌊",
    "web": "🕸️",

    # Ranks & Progression
    "rank_bronze": "🥉",
    "rank_silver": "🥈",
    "rank_gold": "🥇",
    "rank_platinum": "💎",
    "rank_diamond": "💠",
    "rank_master": "🔮",
    "rank_grandmaster": "🔥",
    "rank_legend": "🌌",
    "gold": "🪙",
    "xp": "✨",
    "level_up": "⚡",
    "rank_up": "👑",
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
    "victory_villain": "https://media1.giphy.com/media/v1.Y2lkPTZjMDliOTUyODdzc24ydDAzb2lhY3l0MWhuam4ycm83NDRyY3UxZ295dzlldThkMCZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/nhFvzFSWaoDy4VZm2W/giphy.gif",
    "victory_neutral": "https://media1.giphy.com/media/v1.Y2lkPTZjMDliOTUyODdzc24ydDAzb2lhY3l0MWhuam4ycm83NDRyY3UxZ295dzlldThkMCZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/nhFvzFSWaoDy4VZm2W/giphy.gif",
    "draw": "",
}


def get_role_image(role_key: str) -> str | None:
    """Returns the configured thumbnail URL for a role, checking roles.json/emojis fallback."""
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

    # Fallback to EMOJIS conversion
    emoji = get_emoji(role_key)
    if emoji:
        import re
        # 1. Custom Discord emoji check (<:name:id> or <a:name:id>)
        custom_match = re.match(r"<(a?):[^:]+:([0-9]+)>", emoji)
        if custom_match:
            is_animated = bool(custom_match.group(1))
            emoji_id = custom_match.group(2)
            ext = "gif" if is_animated else "png"
            return f"https://cdn.discordapp.com/emojis/{emoji_id}.{ext}"

        # 2. Unicode emoji check (convert to Twemoji CDN link)
        # Strip variation selector-16 (fe0f) if present
        chars = [c for c in emoji if ord(c) != 0xfe0f]
        if chars:
            codepoints = "-".join(f"{ord(c):x}" for c in chars)
            return f"https://cdn.jsdelivr.net/gh/twitter/twemoji@latest/assets/72x72/{codepoints}.png"

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
    "tosen_kill": [
        "**{player}** was erased from existence inside Tōsen's Bankai — absolute judgment, no appeal.",
        "**{player}**'s senses were devoured by Enma Kōrogi. Kaname Tōsen's verdict was final.",
        "**{player}** was executed within Suzumushi's world — no one heard them scream.",
    ],
    "kishibe_alert_kill": [
        "**{player}** visited the wrong person tonight — Kishibe's battle instincts did the rest.",
        "**{player}** approached Kishibe's door and never left. A Veteran's Alert is not to be trifled with.",
        "**{player}** made the last mistake of their life: visiting Kishibe while he was on guard.",
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
