from __future__ import annotations

import random

from utils.constants import RoleFaction
from utils.roles import RoleCategory, role_registry

# Roles that only ever appear via another role's ability (Muzan's infection)
# and should never be handed out directly at game setup.
SPAWN_ONLY_ROLES = frozenset({"demon", "lower_moon", "upper_moon"})


def _roles_with_tag(tag: str, faction: RoleFaction) -> list[str]:
    return [
        cls.role_key
        for cls in role_registry.all()
        if cls.faction == faction
        and tag in getattr(cls, "tags", ())
        and cls.role_key not in SPAWN_ONLY_ROLES
    ]


def _all_faction_roles(faction: RoleFaction, *, unique_only: bool = False) -> list[str]:
    return [
        cls.role_key
        for cls in role_registry.all()
        if cls.faction == faction
        and cls.role_key not in SPAWN_ONLY_ROLES
        and (not unique_only or getattr(cls, "is_unique", True))
    ]


def _pick_town(count: int) -> list[str]:
    """Guarantees 1 Protective, >=1 Investigative, >=1 Council/Utility (as slots allow),
    then fills remaining slots with unused unique town roles, padding with the
    Default Villager filler role if the roster runs out."""
    if count <= 0:
        return []

    protective = _roles_with_tag(RoleCategory.PROTECTIVE, RoleFaction.HERO)
    investigative = _roles_with_tag(RoleCategory.INVESTIGATIVE, RoleFaction.HERO)
    council_utility = list(dict.fromkeys(
        _roles_with_tag(RoleCategory.COUNCIL, RoleFaction.HERO)
        + _roles_with_tag(RoleCategory.UTILITY, RoleFaction.HERO)
    ))

    picks: list[str] = []
    used: set[str] = set()
    remaining = count

    def take_one(candidates: list[str]) -> None:
        nonlocal remaining
        if remaining <= 0:
            return
        options = [c for c in candidates if c not in used]
        if not options:
            return
        choice = random.choice(options)
        used.add(choice)
        picks.append(choice)
        remaining -= 1

    take_one(protective)
    take_one(investigative)
    take_one(council_utility)

    # Fill remaining town slots with any other unused unique town roles first.
    unique_pool = [k for k in _all_faction_roles(RoleFaction.HERO, unique_only=True) if k not in used]
    random.shuffle(unique_pool)
    while remaining > 0:
        if unique_pool:
            picks.append(unique_pool.pop())
        else:
            picks.append("villager")
        remaining -= 1

    return picks


def _pick_mafia(count: int) -> list[str]:
    """Guarantees goon_lord is always present, then adds support and other
    mafia roles as slots allow."""
    if count <= 0:
        return []

    picks: list[str] = []
    remaining = count

    # Always guarantee goon_lord
    picks.append("goon_lord")
    remaining -= 1

    if remaining <= 0:
        return picks

    # Pick a support role (Deception, Control, or Utility) if there is room.
    support_pool: list[str] = []
    for cat in RoleCategory.MAFIA_SUPPORT:
        support_pool.extend(_roles_with_tag(cat, RoleFaction.VILLAIN))
    support_pool = list(dict.fromkeys(support_pool))

    support_choices = [k for k in support_pool if k != "goon_lord"]
    if support_choices:
        support_choice = random.choice(support_choices)
        picks.append(support_choice)
        remaining -= 1

    # Extra mafia slots: fill with unused unique mafia roles, then pad with goon_lord.
    unique_pool = [
        k for k in _all_faction_roles(RoleFaction.VILLAIN, unique_only=True)
        if k not in picks
    ]
    random.shuffle(unique_pool)
    while remaining > 0:
        if unique_pool:
            picks.append(unique_pool.pop())
        else:
            picks.append("goon_lord")
        remaining -= 1

    return picks


def _pick_neutral(count: int) -> list[str]:
    """0-2+ Neutrals (count comes from the balance table for the lobby size).
    Prefers variety — no repeated neutral role unless the roster is exhausted."""
    if count <= 0:
        return []

    unique_pool = _all_faction_roles(RoleFaction.NEUTRAL, unique_only=True)
    random.shuffle(unique_pool)
    fallback_pool = _all_faction_roles(RoleFaction.NEUTRAL, unique_only=False) or ["mahoraga"]

    picks: list[str] = []
    for _ in range(count):
        if unique_pool:
            picks.append(unique_pool.pop())
        else:
            picks.append(random.choice(fallback_pool))
    return picks


def build_role_pool(player_count: int) -> list[str]:
    """Builds a shuffled list of role_keys for the given player count, guaranteeing
    category coverage (protective/investigative/council-utility for town, exactly
    one killing + one support role for mafia) instead of a purely random draw."""
    from roles import get_role_balance  # local import: avoids circular import at package load time

    balance = get_role_balance(player_count)
    assigned = (
        _pick_town(balance.get("town", 0))
        + _pick_mafia(balance.get("mafia", 0))
        + _pick_neutral(balance.get("neutral", 0))
    )
    random.shuffle(assigned)
    return assigned
