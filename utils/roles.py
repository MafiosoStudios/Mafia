from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar

from utils.constants import RoleFaction


class RoleCategory:
    """Category tags used by the balanced role-selection algorithm (see roles/balance.py).

    Town categories: PROTECTIVE, INVESTIGATIVE, COUNCIL, UTILITY.
    Mafia categories: KILLING (exactly one per game), and the "support" trio
    DECEPTION / CONTROL / UTILITY (exactly one of these per game).
    Neutral roles use NEUTRAL plus whatever descriptive tag they like.
    """

    PROTECTIVE = "protective"
    INVESTIGATIVE = "investigative"
    COUNCIL = "council"
    UTILITY = "utility"
    KILLING = "killing"
    DECEPTION = "deception"
    CONTROL = "control"
    NEUTRAL = "neutral"

    MAFIA_SUPPORT = (DECEPTION, CONTROL, UTILITY)


@dataclass(slots=True)
class RoleContext:
    game_id: str
    guild_id: int
    user_id: int
    target_id: int | None = None
    targets: tuple[int, ...] = ()
    payload: dict[str, object] = field(default_factory=dict)


class BaseRole(ABC):
    role_key: ClassVar[str]
    character_name: ClassVar[str]
    faction: ClassVar[RoleFaction]
    win_condition: ClassVar[str]
    description: ClassVar[str]
    passive_ability: ClassVar[str]
    active_ability: ClassVar[str]
    action_prompt: ClassVar[str] = ""
    priority: ClassVar[int]
    cooldown: ClassVar[int | None] = None
    is_unique: ClassVar[bool] = True
    tags: ClassVar[tuple[str, ...]] = ()

    def passive(self, context: RoleContext) -> None:
        return None

    async def night_action(self, context: RoleContext) -> None:
        return None

    async def on_death(self, context: RoleContext) -> None:
        return None

    async def on_vote(self, context: RoleContext) -> None:
        return None

    async def on_trial(self, context: RoleContext) -> None:
        return None

    @abstractmethod
    def win_condition_met(self, alive_factions: frozenset[str], context: RoleContext) -> bool:
        raise NotImplementedError


class RoleRegistry:
    def __init__(self) -> None:
        self._roles: dict[str, type[BaseRole]] = {}

    def register(self, role_cls: type[BaseRole]) -> type[BaseRole]:
        self._roles[role_cls.role_key] = role_cls
        return role_cls

    def get(self, role_key: str) -> type[BaseRole]:
        return self._roles[role_key]

    def all(self) -> tuple[type[BaseRole], ...]:
        return tuple(self._roles.values())

    def contains(self, role_key: str) -> bool:
        return role_key in self._roles


role_registry = RoleRegistry()
