from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import ClassVar, Any

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
    bot: Any = None


# --- Modular Components ---

@dataclass
class Alignment:
    faction: RoleFaction
    display_name: str


class Ability:
    def __init__(self, name: str, description: str, cooldown: int | None = None) -> None:
        self.name = name
        self.description = description
        self.cooldown = cooldown


class NightAction(Ability):
    def __init__(self, name: str, description: str, priority: int = 5, cooldown: int | None = None) -> None:
        super().__init__(name, description, cooldown)
        self.priority = priority
        self.num_targets = 1

    async def execute(self, context: RoleContext) -> None:
        pass

    def can_use(self, session: Any, player_state: Any) -> tuple[bool, str | None]:
        return True, None

    def get_eligible_targets(self, session: Any, actor_id: int) -> list[int]:
        targets = []
        for pid, pstate in session.players.items():
            if pstate.alive:
                if pstate.metadata.get("hidden_until_night") == session.metadata.get("night_num"):
                    continue
                targets.append(pid)
        return targets


class DayAction(Ability):
    async def execute(self, context: RoleContext) -> None:
        pass


class PassiveEffect:
    def __init__(self, name: str, description: str) -> None:
        self.name = name
        self.description = description

    async def on_death(self, context: RoleContext) -> None:
        pass

    async def on_vote(self, context: RoleContext) -> None:
        pass

    async def on_trial(self, context: RoleContext) -> None:
        pass

    async def resolve_protection(self, context: RoleContext, attack_sources: list[str]) -> bool:
        return False


class WinCondition:
    def __init__(self, description: str) -> None:
        self.description = description

    def check(self, alive_factions: frozenset[str], context: RoleContext) -> bool:
        return False


# --- Reusable Win Conditions ---

class TownWinCondition(WinCondition):
    def __init__(self) -> None:
        super().__init__("Help the town win. (Wins with Town)")

    def check(self, alive_factions: frozenset[str], context: RoleContext) -> bool:
        return RoleFaction.HERO.value in alive_factions


class MafiaWinCondition(WinCondition):
    def __init__(self) -> None:
        super().__init__("Eliminate all threats to the Mafia. (Wins with Mafia)")

    def check(self, alive_factions: frozenset[str], context: RoleContext) -> bool:
        return RoleFaction.VILLAIN.value in alive_factions


# --- Base Role Class ---

class BaseRole(ABC):
    role_key: ClassVar[str]
    character_name: ClassVar[str] = ""
    faction: ClassVar[RoleFaction] = RoleFaction.HERO
    win_condition: ClassVar[str] = ""
    description: ClassVar[str] = ""
    passive_ability: ClassVar[str] = ""
    active_ability: ClassVar[str] = ""
    action_prompt: ClassVar[str] = ""
    priority: ClassVar[int] = 5
    cooldown: ClassVar[int | None] = None
    is_unique: ClassVar[bool] = True
    tags: ClassVar[tuple[str, ...]] = ()

    # Limitations & UI descriptive fields
    cooldown_text: ClassVar[str] = "None"
    limitations_text: ClassVar[str] = "None"
    is_hostile_neutral: ClassVar[bool] = False
    continues_game_after_win: ClassVar[bool] = False

    def __init__(self) -> None:
        self.alignment = Alignment(self.faction, self.faction.value)
        self.abilities: list[Ability] = []
        self.passives: list[PassiveEffect] = []
        
        # Assign default win condition based on faction
        if self.faction == RoleFaction.HERO:
            self.win_condition_obj: WinCondition = TownWinCondition()
        elif self.faction == RoleFaction.VILLAIN:
            self.win_condition_obj = MafiaWinCondition()
        else:
            self.win_condition_obj = WinCondition("Neutral win condition.")

    def passive(self, context: RoleContext) -> None:
        pass

    async def night_action(self, context: RoleContext) -> None:
        # Execute any active NightAction component
        for ability in self.abilities:
            if isinstance(ability, NightAction):
                await ability.execute(context)

    async def day_action(self, context: RoleContext) -> None:
        # Execute any active DayAction component
        for ability in self.abilities:
            if isinstance(ability, DayAction):
                await ability.execute(context)

    async def on_death(self, context: RoleContext) -> None:
        for passive in self.passives:
            await passive.on_death(context)

    async def on_vote(self, context: RoleContext) -> None:
        for passive in self.passives:
            await passive.on_vote(context)

    async def on_trial(self, context: RoleContext) -> None:
        for passive in self.passives:
            await passive.on_trial(context)

    def win_condition_met(self, alive_factions: frozenset[str], context: RoleContext) -> bool:
        return self.win_condition_obj.check(alive_factions, context)

    async def resolve_protection(self, context: RoleContext, attack_sources: list[str]) -> bool:
        # Call passives to check for active protection/regen/adaptation shields
        for passive in self.passives:
            if await passive.resolve_protection(context, attack_sources):
                return True
        return False

    async def get_night_feedback(self, context: RoleContext) -> str | None:
        return None

    def can_act_tonight(self, session: Any, player_state: Any) -> tuple[bool, str | None]:
        return True, None

    async def on_game_start(self, session: Any, user_id: int) -> None:
        pass

    def is_active_threat(self, session: Any, player_state: Any) -> bool:
        return False


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
