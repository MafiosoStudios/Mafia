from __future__ import annotations

from typing import ClassVar, Any
from utils.roles import BaseRole, RoleContext, RoleCategory, role_registry, NightAction, WinCondition
from utils.constants import RoleFaction
from config import get_emoji


class TenmaHeal(NightAction):
    def __init__(self, role: BaseRole) -> None:
        super().__init__(
            name="Hand of Compassion",
            description="Heal/protect a player, cannot target same player consecutively. Max Ability: Scalpel of Justice (Revive a dead mafia member as a Default Villager after successfully saving at least 3 players).",
            priority=3
        )
        self.role = role

    async def execute(self, context: RoleContext) -> None:
        target_id = context.target_id
        if not target_id:
            return

        session = context.payload.get("session")
        if not session:
            return
            
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


@role_registry.register
class DoctorTenma(BaseRole):
    role_key: ClassVar[str] = "doctor_tenma"
    priority: ClassVar[int] = 3
    tags: ClassVar[tuple[str, ...]] = (RoleCategory.PROTECTIVE,)
    cooldown_text: ClassVar[str] = "None"
    limitations_text: ClassVar[str] = "Cannot heal the same player consecutively. Reviving a dead Mafia teammate as a Villager requires saving at least 3 players first."

    def __init__(self) -> None:
        super().__init__()
        self.abilities = [TenmaHeal(self)]

    async def get_night_feedback(self, context: RoleContext) -> str | None:
        target_id = context.payload.get("target_id")
        action_type = context.payload.get("action_type")
        if not target_id:
            return None
            
        if action_type == "revive":
            return f"{get_emoji('doctor_tenma')} **You used your Scalpel of Justice to revive <@{target_id}> as a Default Villager!**"

        # Check if heal successfully saved someone
        session = context.payload.get("session")
        if session:
            pending_kills = session.metadata.get("pending_kills", {})
            healed_players = session.metadata.get("healed_players", {})
            doc_id = healed_players.get(target_id + 1000000)
            was_attacked = target_id in pending_kills
            
            if was_attacked and doc_id == context.user_id:
                player_state = session.players[context.user_id]
                doc_saves = player_state.metadata.get("saves_count", 0)
                return f"{get_emoji('shield')} **Compassion Successful!** You saved <@{target_id}> from an attack! Saves: **{doc_saves}/3**."
            
            return f"{get_emoji('doctor_tenma')} **You decided to heal <@{target_id}> tonight. They were not attacked.**"
        return None


class ShadowAnalysis(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Shadow Analysis",
            description="Investigate a player's true faction; result is immune to framing/diversion.",
            priority=5
        )

    async def execute(self, context: RoleContext) -> None:
        target_id = context.target_id
        if not target_id:
            return

        session = context.payload.get("session")
        if not session:
            return
            
        target_player = session.players.get(target_id)
        if not target_player:
            return

        # Return true faction - cannot be altered by redirects or frames
        faction = target_player.faction
        context.payload["result"] = f"Investigation Result: <@{target_id}>'s true faction is **{faction}**."


@role_registry.register
class AyanokojiKiyotaka(BaseRole):
    role_key: ClassVar[str] = "ayanokoji_kiyotaka"
    priority: ClassVar[int] = 5
    tags: ClassVar[tuple[str, ...]] = (RoleCategory.INVESTIGATIVE,)
    cooldown_text: ClassVar[str] = "None"
    limitations_text: ClassVar[str] = "None"

    def __init__(self) -> None:
        super().__init__()
        self.abilities = [ShadowAnalysis()]


class JusticesEye(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Justice's Eye",
            description="Investigate a player. 1st scan: Faction. 2nd scan: Role. 3rd scan: Target history, charges, and Max Ability status.",
            priority=5
        )

    async def execute(self, context: RoleContext) -> None:
        target_id = context.target_id
        if not target_id:
            return

        session = context.payload.get("session")
        if not session:
            return
            
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


@role_registry.register
class L(BaseRole):
    role_key: ClassVar[str] = "l"
    priority: ClassVar[int] = 5
    tags: ClassVar[tuple[str, ...]] = (RoleCategory.INVESTIGATIVE,)
    cooldown_text: ClassVar[str] = "None"
    limitations_text: ClassVar[str] = "None"

    def __init__(self) -> None:
        super().__init__()
        self.abilities = [JusticesEye()]


@role_registry.register
class DefaultVillager(BaseRole):
    role_key: ClassVar[str] = "villager"
    priority: ClassVar[int] = 5
    tags: ClassVar[tuple[str, ...]] = (RoleCategory.COUNCIL,)
    is_unique: ClassVar[bool] = False
    cooldown_text: ClassVar[str] = "None"
    limitations_text: ClassVar[str] = "None"
