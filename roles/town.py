from __future__ import annotations

from typing import ClassVar, Any
from utils.roles import BaseRole, RoleContext, RoleCategory, role_registry, NightAction
from utils.constants import RoleFaction
from config import get_emoji


# =============================================================================
# Kenzo Tenma (Miracle Doctor)
# =============================================================================

class TenmaEmergencySurgery(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Emergency Surgery",
            description="Heal/protect a player from attacks. Cooldown: 1 Night.",
            priority=1
        )

    def can_use(self, session: Any, player_state: Any) -> tuple[bool, str | None]:
        last_used = player_state.metadata.get("tenma_surgery_last_used")
        if last_used is not None and session.night_num - last_used < 2:
            return False, f"Emergency Surgery is on cooldown until Night {last_used + 2}."
        return True, None

    async def execute(self, context: RoleContext) -> None:
        target_id = context.target_id
        session = context.payload.get("session")
        if not target_id or not session:
            return

        player_state = session.players[context.user_id]
        player_state.metadata["tenma_surgery_last_used"] = session.night_num

        session.metadata.setdefault("doctor_heals", {})[target_id] = context.user_id
        context.payload["result"] = f"🩺 **Emergency Surgery:** You prepared to protect <@{target_id}> tonight."


class TenmaLifeSupport(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Life Support",
            description="Connect a player to life support. If they would die tonight, they survive but become Wounded. (1 use)",
            priority=1
        )

    def can_use(self, session: Any, player_state: Any) -> tuple[bool, str | None]:
        uses = player_state.metadata.setdefault("tenma_life_support_uses", 1)
        if uses <= 0:
            return False, "Life Support has no uses left."
        return True, None

    async def execute(self, context: RoleContext) -> None:
        target_id = context.target_id
        session = context.payload.get("session")
        if not target_id or not session:
            return

        player_state = session.players[context.user_id]
        uses = player_state.metadata.get("tenma_life_support_uses", 1)
        player_state.metadata["tenma_life_support_uses"] = max(0, uses - 1)

        session.metadata.setdefault("life_supports", {})[target_id] = context.user_id
        context.payload["result"] = f"🩺 **Life Support:** You connected <@{target_id}> to life support tonight."


@role_registry.register
class DoctorTenma(BaseRole):
    role_key: ClassVar[str] = "doctor_tenma"
    priority: ClassVar[int] = 1
    tags: ClassVar[tuple[str, ...]] = (RoleCategory.PROTECTIVE,)
    cooldown_text: ClassVar[str] = "Emergency Surgery: 1 Night"
    limitations_text: ClassVar[str] = "Life Support: 1 use per game"

    def __init__(self) -> None:
        super().__init__()
        self.abilities = [TenmaEmergencySurgery(), TenmaLifeSupport()]

    async def get_night_feedback(self, context: RoleContext) -> str | None:
        return context.payload.get("result")


# =============================================================================
# Ayanokoji Kiyotaka (Hidden Genius)
# =============================================================================

class AyanokojiObservation(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Observation",
            description="Observe a player. Learn whether they: Used an ability / Did not use an ability.",
            priority=9
        )

    def get_eligible_targets(self, session: Any, actor_id: int) -> list[int]:
        return [pid for pid in super().get_eligible_targets(session, actor_id) if pid != actor_id]

    async def execute(self, context: RoleContext) -> None:
        target_id = context.target_id
        session = context.payload.get("session")
        if not target_id or not session:
            return

        target_action = session.night_actions.get(target_id)
        target_state = session.players.get(target_id)

        used_ability = False
        if target_action and target_state:
            if not target_state.metadata.get("roleblocked"):
                used_ability = True

        context.payload["result"] = f"🧠 **Observation Result:** <@{target_id}> **{'used' if used_ability else 'did not use'}** an ability tonight."


class AyanokojiPsychological(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Psychological Analysis",
            description="Analyze a player. Learn whether they: Visited another player / Stayed home.",
            priority=9
        )

    def get_eligible_targets(self, session: Any, actor_id: int) -> list[int]:
        return [pid for pid in super().get_eligible_targets(session, actor_id) if pid != actor_id]

    async def execute(self, context: RoleContext) -> None:
        target_id = context.target_id
        session = context.payload.get("session")
        if not target_id or not session:
            return

        target_action = session.night_actions.get(target_id)
        target_state = session.players.get(target_id)

        visited = False
        if target_action and target_state:
            if not target_state.metadata.get("roleblocked"):
                t_id = target_action.get("target_id")
                if t_id is not None and t_id != target_id:
                    visited = True
                elif target_action.get("controlled_vote_target") is not None:
                    visited = True
                elif target_action.get("targets"):
                    visited = True

        context.payload["result"] = f"🧠 **Psychological Analysis:** <@{target_id}> **{'visited another player' if visited else 'stayed home'}** tonight."


@role_registry.register
class AyanokojiKiyotaka(BaseRole):
    role_key: ClassVar[str] = "ayanokoji_kiyotaka"
    priority: ClassVar[int] = 9
    tags: ClassVar[tuple[str, ...]] = (RoleCategory.INVESTIGATIVE,)
    cooldown_text: ClassVar[str] = "None"
    limitations_text: ClassVar[str] = "None"

    def __init__(self) -> None:
        super().__init__()
        self.abilities = [AyanokojiObservation(), AyanokojiPsychological()]

    async def get_night_feedback(self, context: RoleContext) -> str | None:
        return context.payload.get("result")


# =============================================================================
# L (World's Greatest Detective)
# =============================================================================

class LDeduction(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Deduction",
            description="Investigate a player to learn their alignment. Scan them twice to learn exact role.",
            priority=5
        )

    def get_eligible_targets(self, session: Any, actor_id: int) -> list[int]:
        return [pid for pid in super().get_eligible_targets(session, actor_id) if pid != actor_id]

    async def execute(self, context: RoleContext) -> None:
        target_id = context.target_id
        session = context.payload.get("session")
        if not target_id or not session:
            return

        target_player = session.players.get(target_id)
        if not target_player:
            return

        player_state = session.players[context.user_id]
        scans = player_state.metadata.setdefault("l_scans", {})
        scan_count = scans.get(str(target_id), 0) + 1
        scans[str(target_id)] = scan_count

        faction = target_player.faction
        if target_player.metadata.get("framed"):
            faction = RoleFaction.VILLAIN.value

        if scan_count >= 2:
            role_display = target_player.role_key.replace('_', ' ').title()
            context.payload["result"] = f"🕵️ **Deduction (Scan {scan_count}):** <@{target_id}>'s exact role is **{role_display}**."
        else:
            align_emoji = "🍏 Protagonist" if faction == RoleFaction.HERO.value else ("🍎 Antagonist" if faction == RoleFaction.VILLAIN.value else "🟡 Neutral")
            context.payload["result"] = f"🕵️ **Deduction (Scan 1):** <@{target_id}>'s alignment is **{align_emoji}**."


class LCrossExamination(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Cross Examination",
            description="Compare two players' factions. (2 uses)",
            priority=5
        )
        self.num_targets = 2

    def can_use(self, session: Any, player_state: Any) -> tuple[bool, str | None]:
        uses = player_state.metadata.setdefault("l_cross_uses", 2)
        if uses <= 0:
            return False, "Cross Examination has no uses left."
        return True, None

    async def execute(self, context: RoleContext) -> None:
        targets = context.targets
        session = context.payload.get("session")
        if len(targets) < 2 or not session:
            return

        player_state = session.players[context.user_id]
        uses = player_state.metadata.get("l_cross_uses", 2)
        player_state.metadata["l_cross_uses"] = max(0, uses - 1)

        t1, t2 = targets[0], targets[1]
        p1 = session.players.get(t1)
        p2 = session.players.get(t2)
        if not p1 or not p2:
            return

        f1 = RoleFaction.VILLAIN.value if p1.metadata.get("framed") else p1.faction
        f2 = RoleFaction.VILLAIN.value if p2.metadata.get("framed") else p2.faction

        same = (f1 == f2)
        context.payload["result"] = f"🕵️ **Cross Examination:** <@{t1}> and <@{t2}> belong to **{'the same faction' if same else 'different factions'}**."


@role_registry.register
class L(BaseRole):
    role_key: ClassVar[str] = "l"
    priority: ClassVar[int] = 5
    tags: ClassVar[tuple[str, ...]] = (RoleCategory.INVESTIGATIVE,)
    cooldown_text: ClassVar[str] = "None"
    limitations_text: ClassVar[str] = "Cross Examination: 2 uses"

    def __init__(self) -> None:
        super().__init__()
        self.abilities = [LDeduction(), LCrossExamination()]

    async def get_night_feedback(self, context: RoleContext) -> str | None:
        return context.payload.get("result")


# =============================================================================
# Tobirama Senju (Master Sensor)
# =============================================================================

class TobiramaSensory(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Sensory Technique",
            description="Observe a player during the night. Learn who visited them.",
            priority=9
        )

    async def execute(self, context: RoleContext) -> None:
        target_id = context.target_id
        session = context.payload.get("session")
        if not target_id or not session:
            return

        visitors = []
        for pid, action in session.night_actions.items():
            pstate = session.players.get(pid)
            if not pstate or pstate.metadata.get("roleblocked"):
                continue
            t_id = action.get("target_id")
            targets = action.get("targets", ())
            if t_id == target_id or target_id in targets or action.get("controlled_vote_target") == target_id:
                visitors.append(pid)

        if visitors:
            visitors_str = ", ".join([f"<@{v}>" for v in visitors])
            context.payload["result"] = f"🌊 **Sensory Technique:** The players who visited <@{target_id}> tonight are: {visitors_str}."
        else:
            context.payload["result"] = f"🌊 **Sensory Technique:** Nobody visited <@{target_id}> tonight."


class TobiramaWaterWall(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Water Wall",
            description="Protect a player from the first basic attack tonight. (2 uses)",
            priority=1
        )

    def can_use(self, session: Any, player_state: Any) -> tuple[bool, str | None]:
        uses = player_state.metadata.setdefault("tobirama_wall_uses", 2)
        if uses <= 0:
            return False, "Water Wall has no uses left."
        return True, None

    async def execute(self, context: RoleContext) -> None:
        target_id = context.target_id
        session = context.payload.get("session")
        if not target_id or not session:
            return

        player_state = session.players[context.user_id]
        uses = player_state.metadata.get("tobirama_wall_uses", 2)
        player_state.metadata["tobirama_wall_uses"] = max(0, uses - 1)

        session.metadata.setdefault("water_walls", {})[target_id] = context.user_id
        context.payload["result"] = f"🌊 **Water Wall:** You placed a Water Barrier around <@{target_id}>."


@role_registry.register
class TobiramaSenju(BaseRole):
    role_key: ClassVar[str] = "tobirama_senju"
    priority: ClassVar[int] = 1
    tags: ClassVar[tuple[str, ...]] = (RoleCategory.INVESTIGATIVE,)
    cooldown_text: ClassVar[str] = "None"
    limitations_text: ClassVar[str] = "Water Wall: 2 uses"

    def __init__(self) -> None:
        super().__init__()
        self.abilities = [TobiramaSensory(), TobiramaWaterWall()]

    async def get_night_feedback(self, context: RoleContext) -> str | None:
        return context.payload.get("result")


# =============================================================================
# Hiromi Higuruma (Prosecutor)
# =============================================================================

@role_registry.register
class HiromiHiguruma(BaseRole):
    role_key: ClassVar[str] = "hiromi_higuruma"
    priority: ClassVar[int] = 5
    tags: ClassVar[tuple[str, ...]] = (RoleCategory.COUNCIL,)
    cooldown_text: ClassVar[str] = "None"
    limitations_text: ClassVar[str] = "Deadly Sentencing: 2 uses, Retrial: 2 uses"

    def __init__(self) -> None:
        super().__init__()
        self.abilities = [] # Hiromi has Day/Trial active abilities managed hook-side

    async def get_night_feedback(self, context: RoleContext) -> str | None:
        return None


# =============================================================================
# Levi Ackerman (Humanity's Strongest Soldier)
# =============================================================================

class LeviODMExecution(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="ODM Execution",
            description="Perform a lethal ODM strike on a player. (3 uses)",
            priority=4
        )

    def can_use(self, session: Any, player_state: Any) -> tuple[bool, str | None]:
        uses = player_state.metadata.setdefault("levi_execution_uses", 3)
        if uses <= 0:
            return False, "ODM Execution has no uses left."
        if player_state.metadata.get("exhausted_until_night") == session.night_num:
            return False, f"You are Exhausted tonight and cannot use ODM Execution."
        return True, None

    def get_eligible_targets(self, session: Any, actor_id: int) -> list[int]:
        return [pid for pid in super().get_eligible_targets(session, actor_id) if pid != actor_id]

    async def execute(self, context: RoleContext) -> None:
        target_id = context.target_id
        session = context.payload.get("session")
        if not target_id or not session:
            return

        player_state = session.players[context.user_id]
        uses = player_state.metadata.get("levi_execution_uses", 3)
        player_state.metadata["levi_execution_uses"] = max(0, uses - 1)

        precision = player_state.metadata.get("levi_precision_active", False)
        if precision:
            player_state.metadata["levi_precision_active"] = False

        pending_kills = session.metadata.setdefault("pending_kills", {})
        pending_kills[target_id] = pending_kills.get(target_id, []) + ["levi_kill"]
        context.payload["result"] = f"⚔️ **ODM Execution:** You launched a strike against <@{target_id}> (Precision strike active: **{precision}**)."


class LeviPrecisionStrike(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Precision Strike",
            description="Make your next ODM Execution tonight ignore standard protections. (1 use)",
            priority=1
        )
        self.num_targets = 0

    def can_use(self, session: Any, player_state: Any) -> tuple[bool, str | None]:
        uses = player_state.metadata.setdefault("levi_precision_uses", 1)
        if uses <= 0:
            return False, "Precision Strike has no uses left."
        if player_state.metadata.get("exhausted_until_night") == session.night_num:
            return False, "You are Exhausted tonight."
        return True, None

    async def execute(self, context: RoleContext) -> None:
        session = context.payload.get("session")
        if not session:
            return
        player_state = session.players[context.user_id]
        uses = player_state.metadata.get("levi_precision_uses", 1)
        player_state.metadata["levi_precision_uses"] = max(0, uses - 1)
        player_state.metadata["levi_precision_active"] = True
        context.payload["result"] = "⚔️ **Precision Strike:** Your ODM Execution tonight will bypass standard protections."


@role_registry.register
class LeviAckerman(BaseRole):
    role_key: ClassVar[str] = "levi_ackerman"
    priority: ClassVar[int] = 4
    tags: ClassVar[tuple[str, ...]] = (RoleCategory.COUNCIL,)
    cooldown_text: ClassVar[str] = "None"
    limitations_text: ClassVar[str] = "ODM Execution: 3 uses, Precision Strike: 1 use"

    def __init__(self) -> None:
        super().__init__()
        self.abilities = [LeviODMExecution(), LeviPrecisionStrike()]

    async def get_night_feedback(self, context: RoleContext) -> str | None:
        return context.payload.get("result")


# =============================================================================
# Maomao (Apothecary)
# =============================================================================

class MaomaoPostmortem(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Postmortem Analysis",
            description="Examine a player who died last night to discover all of their visitors. Cooldown: 1 Night.",
            priority=5
        )

    def can_use(self, session: Any, player_state: Any) -> tuple[bool, str | None]:
        last_used = player_state.metadata.get("maomao_postmortem_last_used")
        if last_used is not None and session.night_num - last_used < 2:
            return False, f"Postmortem Analysis is on cooldown until Night {last_used + 2}."
        
        dead_list = session.metadata.get("dead_last_night", [])
        if not dead_list:
            return False, "No players died last night to analyze."
        return True, None

    def get_eligible_targets(self, session: Any, actor_id: int) -> list[int]:
        return session.metadata.get("dead_last_night", [])

    async def execute(self, context: RoleContext) -> None:
        target_id = context.target_id
        session = context.payload.get("session")
        if not target_id or not session:
            return

        player_state = session.players[context.user_id]
        player_state.metadata["maomao_postmortem_last_used"] = session.night_num

        history = session.metadata.get("night_visits_history", {})
        prev_night = session.night_num - 1
        night_visits = history.get(prev_night, {}).get(target_id, [])

        protected = False
        prev_heals = session.metadata.get("heals_history", {}).get(prev_night, {})
        if target_id in prev_heals:
            protected = True

        visitors_str = ", ".join([f"<@{v}>" for v in night_visits]) if night_visits else "Nobody"
        result_str = f"🧪 **Postmortem Analysis:** The visitors to <@{target_id}> on the night they died were: {visitors_str}."
        if protected:
            result_str += "\n🔍 **Keen Observation:** You sensed trace remnants of protection around the body."
        
        context.payload["result"] = result_str


class MaomaoComparative(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Comparative Analysis",
            description="Compare two players to learn if they belong to the same faction. Cooldown: 1 Night.",
            priority=5
        )
        self.num_targets = 2

    def can_use(self, session: Any, player_state: Any) -> tuple[bool, str | None]:
        last_used = player_state.metadata.get("maomao_comparative_last_used")
        if last_used is not None and session.night_num - last_used < 2:
            return False, f"Comparative Analysis is on cooldown until Night {last_used + 2}."
        return True, None

    async def execute(self, context: RoleContext) -> None:
        targets = context.targets
        session = context.payload.get("session")
        if len(targets) < 2 or not session:
            return

        player_state = session.players[context.user_id]
        player_state.metadata["maomao_comparative_last_used"] = session.night_num

        t1, t2 = targets[0], targets[1]
        p1 = session.players.get(t1)
        p2 = session.players.get(t2)
        if not p1 or not p2:
            return

        f1 = RoleFaction.VILLAIN.value if p1.metadata.get("framed") else p1.faction
        f2 = RoleFaction.VILLAIN.value if p2.metadata.get("framed") else p2.faction

        same = (f1 == f2)
        context.payload["result"] = f"🧪 **Comparative Analysis:** <@{t1}> and <@{t2}> belong to **{'the same faction' if same else 'different factions'}**."


@role_registry.register
class Maomao(BaseRole):
    role_key: ClassVar[str] = "maomao"
    priority: ClassVar[int] = 5
    tags: ClassVar[tuple[str, ...]] = (RoleCategory.UTILITY,)
    cooldown_text: ClassVar[str] = "Postmortem Analysis: 1 Night, Comparative Analysis: 1 Night"
    limitations_text: ClassVar[str] = "None"

    def __init__(self) -> None:
        super().__init__()
        self.abilities = [MaomaoPostmortem(), MaomaoComparative()]

    async def get_night_feedback(self, context: RoleContext) -> str | None:
        return context.payload.get("result")


# =============================================================================
# Frieren (Mage)
# =============================================================================

class FrierenAncientBinding(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Ancient Binding",
            description="Bind two players. If one dies tonight, the survivor becomes Hidden. Cooldown: 2 Days after success.",
            priority=1
        )
        self.num_targets = 2

    def can_use(self, session: Any, player_state: Any) -> tuple[bool, str | None]:
        cooldown_until = player_state.metadata.setdefault("frieren_binding_cooldown_until_day", 0)
        if session.day_num < cooldown_until:
            return False, f"Ancient Binding is on cooldown until Day {cooldown_until}."
        return True, None

    async def execute(self, context: RoleContext) -> None:
        targets = context.targets
        session = context.payload.get("session")
        if len(targets) < 2 or not session:
            return

        session.metadata.setdefault("ancient_bindings", {})[context.user_id] = list(targets)
        context.payload["result"] = f"✨ **Ancient Binding:** You bound <@{targets[0]}> and <@{targets[1]}> together."


class FrierenMagicalBarrier(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Magical Barrier",
            description="Protect a player from attacks of the opposite faction tonight.",
            priority=1
        )

    async def execute(self, context: RoleContext) -> None:
        target_id = context.target_id
        session = context.payload.get("session")
        if not target_id or not session:
            return

        session.metadata.setdefault("magical_barriers", {})[target_id] = context.user_id
        context.payload["result"] = f"✨ **Magical Barrier:** You placed a magical shield around <@{target_id}>."


class FrierenAgeOfMagic(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Age of Magic",
            description="Reduce a player's ability cooldowns by 1 Night.",
            priority=1
        )

    async def execute(self, context: RoleContext) -> None:
        target_id = context.target_id
        session = context.payload.get("session")
        if not target_id or not session:
            return

        target_player = session.players.get(target_id)
        if target_player:
            for key in ["tenma_surgery_last_used", "maomao_postmortem_last_used", "maomao_comparative_last_used"]:
                if key in target_player.metadata:
                    target_player.metadata[key] -= 1
            if "frieren_binding_cooldown_until_day" in target_player.metadata:
                target_player.metadata["frieren_binding_cooldown_until_day"] -= 1

        context.payload["result"] = f"✨ **Age of Magic:** You reduced <@{target_id}>'s ability cooldowns by 1 Night."


@role_registry.register
class Frieren(BaseRole):
    role_key: ClassVar[str] = "frieren"
    priority: ClassVar[int] = 1
    tags: ClassVar[tuple[str, ...]] = (RoleCategory.UTILITY,)
    cooldown_text: ClassVar[str] = "Ancient Binding: 2 Days on success"
    limitations_text: ClassVar[str] = "None"

    def __init__(self) -> None:
        super().__init__()
        self.abilities = [FrierenAncientBinding(), FrierenMagicalBarrier(), FrierenAgeOfMagic()]

    async def get_night_feedback(self, context: RoleContext) -> str | None:
        return context.payload.get("result")


# =============================================================================
# Default Villager
# =============================================================================

@role_registry.register
class DefaultVillager(BaseRole):
    role_key: ClassVar[str] = "villager"
    priority: ClassVar[int] = 5
    tags: ClassVar[tuple[str, ...]] = (RoleCategory.COUNCIL,)
    is_unique: ClassVar[bool] = False
    cooldown_text: ClassVar[str] = "None"
    limitations_text: ClassVar[str] = "None"
