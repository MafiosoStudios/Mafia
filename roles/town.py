from __future__ import annotations

from typing import ClassVar, Any
from utils.roles import BaseRole, RoleContext, role_registry
from utils.constants import RoleFaction

@role_registry.register
class DoctorTenma(BaseRole):
    role_key: ClassVar[str] = "doctor_tenma"
    priority: ClassVar[int] = 3

    async def night_action(self, context: RoleContext) -> None:
        target_id = context.target_id
        if not target_id:
            return

        # Hand of Compassion
        session = context.payload.get("session")
        player_state = session.players[context.user_id]
        
        # Check consecutive heals
        last_healed = player_state.metadata.get("last_healed_id")
        if last_healed == target_id:
            context.payload["error"] = "Cannot heal the same player consecutively."
            return

        # Check if doing Scalpel of Justice (revive)
        action_type = context.payload.get("action_type")
        if action_type == "revive":
            saves = player_state.metadata.get("saves_count", 0)
            if saves < 3:
                context.payload["error"] = "You must save at least 3 people first."
                return
            
            target_player = session.players.get(target_id)
            if not target_player or target_player.alive:
                context.payload["error"] = "Target is not dead."
                return
            
            if target_player.faction != RoleFaction.VILLAIN.value:
                context.payload["error"] = "Can only revive dead mafia members."
                return
            
            # Perform revive
            target_player.alive = True
            target_player.role_key = "villager"
            target_player.faction = RoleFaction.HERO.value
            target_player.metadata["revived_by_tenma"] = True
            
            # Reset saves
            player_state.metadata["saves_count"] = 0
            player_state.metadata["revive_used"] = True
            
            context.payload["log"] = f"Doctor Tenma used Scalpel of Justice to revive <@{target_id}> as a Default Villager!"
            return

        # Normal heal action
        player_state.metadata["last_healed_id"] = target_id
        heals = session.metadata.setdefault("healed_players", {})
        heals[target_id] = heals.get(target_id, 0) + 1
        heals[target_id + 1000000] = context.user_id  # Keep track of who healed who
        context.payload["log"] = f"Doctor Tenma protected <@{target_id}> tonight."

    def win_condition_met(self, alive_factions: frozenset[str], context: RoleContext) -> bool:
        return RoleFaction.HERO.value in alive_factions


@role_registry.register
class AyanokojiKiyotaka(BaseRole):
    role_key: ClassVar[str] = "ayanokoji_kiyotaka"
    priority: ClassVar[int] = 5

    async def night_action(self, context: RoleContext) -> None:
        target_id = context.target_id
        if not target_id:
            return

        session = context.payload.get("session")
        target_player = session.players.get(target_id)
        if not target_player:
            return

        # Return true faction - cannot be altered by redirects or frames
        faction = target_player.faction
        context.payload["result"] = f"Investigation Result: <@{target_id}>'s true faction is **{faction}**."

    def win_condition_met(self, alive_factions: frozenset[str], context: RoleContext) -> bool:
        return RoleFaction.HERO.value in alive_factions


@role_registry.register
class L(BaseRole):
    role_key: ClassVar[str] = "l"
    priority: ClassVar[int] = 5

    async def night_action(self, context: RoleContext) -> None:
        target_id = context.target_id
        if not target_id:
            return

        session = context.payload.get("session")
        target_player = session.players.get(target_id)
        if not target_player:
            return

        player_state = session.players[context.user_id]
        scans = player_state.metadata.setdefault("scans", {})
        scan_count = scans.get(str(target_id), 0) + 1
        scans[str(target_id)] = scan_count

        if scan_count == 1:
            context.payload["result"] = f"Investigation (Scan 1): <@{target_id}> belongs to the **{target_player.faction}** faction."
        elif scan_count == 2:
            context.payload["result"] = f"Investigation (Scan 2): <@{target_id}>'s role is **{target_player.role_key}**."
        else:
            # Gather details
            max_avail = target_player.metadata.get("max_ability_available", True)
            charges = target_player.metadata.get("charges", "N/A")
            history = target_player.metadata.get("target_history", [])
            history_str = ", ".join([f"<@{tid}>" for tid in history]) if history else "None"
            
            context.payload["result"] = (
                f"Investigation (Scan 3): <@{target_id}> Details:\n"
                f"- Max Ability Available: **{max_avail}**\n"
                f"- Charges/Uses: **{charges}**\n"
                f"- Visited Targets History: **{history_str}**"
            )

    def win_condition_met(self, alive_factions: frozenset[str], context: RoleContext) -> bool:
        return RoleFaction.HERO.value in alive_factions


@role_registry.register
class DefaultVillager(BaseRole):
    role_key: ClassVar[str] = "villager"
    priority: ClassVar[int] = 5

    def win_condition_met(self, alive_factions: frozenset[str], context: RoleContext) -> bool:
        return RoleFaction.HERO.value in alive_factions
