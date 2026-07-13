from __future__ import annotations

from enum import StrEnum


class RoleFaction(StrEnum):
    HERO = "Hero"
    VILLAIN = "Villain"
    NEUTRAL = "Neutral"
    CHAOS = "Chaos"
    ORDER = "Order"


class GameState(StrEnum):
    LOBBY = "lobby"
    NIGHT = "night"
    DAY = "day"
    TRIAL = "trial"
    EXECUTION = "execution"
    ENDED = "ended"


class GamePhase(StrEnum):
    JOINING = "joining"
    NIGHT_ACTIONS = "night_actions"
    DISCUSSION = "discussion"
    VOTING = "voting"
    TRIAL = "trial"
    EXECUTION = "execution"
    CLEANUP = "cleanup"
