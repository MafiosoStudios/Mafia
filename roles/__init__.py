from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from utils.constants import RoleFaction
from utils.roles import BaseRole, role_registry

# Load JSON configurations
ROLES_DIR = Path(__file__).resolve().parent
ROLES_JSON_PATH = ROLES_DIR / "roles.json"
BALANCE_JSON_PATH = ROLES_DIR / "balance.json"

with open(ROLES_JSON_PATH, "r", encoding="utf-8") as f:
    ROLES_METADATA: dict[str, dict[str, Any]] = json.load(f)

with open(BALANCE_JSON_PATH, "r", encoding="utf-8") as f:
    BALANCE_METADATA: dict[str, dict[str, int]] = json.load(f)


def get_role_balance(player_count: int) -> dict[str, int]:
    """Returns the count of town, mafia, and neutral roles for the given player count."""
    key = str(player_count)
    if key in BALANCE_METADATA:
        res = dict(BALANCE_METADATA[key])
    else:
        # Fallback/extrapolate if outside range
        if player_count < 5:
            res = { "town": player_count - 1, "mafia": 1, "neutral": 0 }
        else:
            res = { "town": int(player_count * 0.6), "mafia": int(player_count * 0.25), "neutral": player_count - int(player_count * 0.6) - int(player_count * 0.25) }
    
    # Guarantee at least 1 Mafia role if player count allows it
    if player_count >= 2 and res.get("mafia", 0) <= 0:
        town = res.get("town", 0)
        neutral = res.get("neutral", 0)
        if neutral > 0:
            res["neutral"] = neutral - 1
        elif town > 0:
            res["town"] = town - 1
        res["mafia"] = 1
        
    return res


def bind_metadata_to_roles() -> None:
    """Binds descriptions, names, abilities, etc. from roles.json to registered Python role classes."""
    for role_key, meta in ROLES_METADATA.items():
        if role_registry.contains(role_key):
            role_cls = role_registry.get(role_key)
            role_cls.character_name = meta.get("name", role_cls.role_key.capitalize())
            
            # Map faction string to RoleFaction enum
            faction_str = meta.get("faction", "Hero")
            if faction_str in ("Hero", "Protagonist"):
                role_cls.faction = RoleFaction.HERO
            elif faction_str in ("Villain", "Antagonist"):
                role_cls.faction = RoleFaction.VILLAIN
            else:
                role_cls.faction = RoleFaction.NEUTRAL
                
            role_cls.win_condition = meta.get("win_condition", "")
            role_cls.description = meta.get("description", "")
            role_cls.active_ability = meta.get("active_ability", "")
            role_cls.passive_ability = meta.get("passive_ability", "")
            role_cls.action_prompt = meta.get("action_prompt", "")


# Import all role classes to trigger decorators
from roles import town
from roles import mafia
from roles import neutral

# Execute bindings
bind_metadata_to_roles()

# Category-balanced role pool builder (imported last since it does a local,
# lazy `from roles import get_role_balance` at call time).
from roles.balance import build_role_pool  # noqa: E402
