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
            description="Choose 2 players tonight. If one survives and the other dies, both survive. You cannot pick the same 2 people again next night.",
            priority=1
        )
        self.num_targets = 2

    def get_eligible_targets(self, session: Any, actor_id: int) -> list[int]:
        return [pid for pid, pstate in session.players.items() if pstate.alive and pid != actor_id]

    async def execute(self, context: RoleContext) -> None:
        targets = context.targets
        session = context.payload.get("session")
        if len(targets) < 2 or not session:
            return

        player_state = session.players[context.user_id]
        player_state.metadata["tenma_last_pair"] = list(targets)

        session.metadata["tenma_surgery"] = list(targets)
        session.metadata["tenma_doctor_id"] = context.user_id

        context.payload["result"] = f"🩺 **Emergency Surgery:** You established a medical link between <@{targets[0]}> and <@{targets[1]}>."


@role_registry.register
class DoctorTenma(BaseRole):
    role_key: ClassVar[str] = "doctor_tenma"
    priority: ClassVar[int] = 1
    tags: ClassVar[tuple[str, ...]] = (RoleCategory.PROTECTIVE,)
    cooldown_text: ClassVar[str] = "None"
    limitations_text: ClassVar[str] = "Cannot select the same 2 players on consecutive nights"

    def __init__(self) -> None:
        super().__init__()
        self.abilities = [TenmaEmergencySurgery()]

    async def get_night_feedback(self, context: RoleContext) -> str | None:
        return context.payload.get("result")


# =============================================================================
# Ayanokoji Kiyotaka (Hidden Genius)
# =============================================================================

class AyanokojiObservation(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Observation",
            description="Observe a player during the Night. Learn who they visited and who visited them.",
            priority=9
        )

    def get_eligible_targets(self, session: Any, actor_id: int) -> list[int]:
        return [pid for pid in super().get_eligible_targets(session, actor_id) if pid != actor_id]

    async def execute(self, context: RoleContext) -> None:
        target_id = context.target_id
        session = context.payload.get("session")
        if not target_id or not session:
            return

        target_state = session.players.get(target_id)
        if not target_state:
            return

        # 1. Who they visited (successful actions)
        visited_ids = []
        target_action = session.night_actions.get(target_id)
        if target_action and not target_state.metadata.get("roleblocked") and not target_state.metadata.get("nullified") and not target_state.metadata.get("black_divider_nullified"):
            t_id = target_action.get("target_id")
            if t_id:
                visited_ids.append(t_id)
            targets = target_action.get("targets", ())
            for t in targets:
                if t not in visited_ids:
                    visited_ids.append(t)
            ctrl_target = target_action.get("controlled_vote_target")
            if ctrl_target and ctrl_target not in visited_ids:
                visited_ids.append(ctrl_target)

        # 2. Who visited them
        visitors = []
        for pid, action in session.night_actions.items():
            pstate = session.players.get(pid)
            if not pstate or pstate.metadata.get("roleblocked") or pstate.metadata.get("nullified") or pstate.metadata.get("black_divider_nullified"):
                continue
            t_id = action.get("target_id")
            targets = action.get("targets", ())
            if t_id == target_id or target_id in targets or action.get("controlled_vote_target") == target_id:
                visitors.append(pid)

        visited_str = ", ".join([f"<@{v}>" for v in visited_ids]) if visited_ids else "nobody"
        visitors_str = ", ".join([f"<@{v}>" for v in visitors]) if visitors else "nobody"

        context.payload["result"] = (
            f"🧠 **Observation Result:** <@{target_id}> visited **{visited_str}**.\n"
            f"{get_emoji('detective')} They were visited by: **{visitors_str}**.\n"
            f'*"People reveal more through their actions than their words."*'
        )


class AyanokojiPublicReveal(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Public Reveal",
            description="Starting from night 4, publicly reveal the role of your target. Cooldown: 4 Days.",
            priority=9
        )

    def get_eligible_targets(self, session: Any, actor_id: int) -> list[int]:
        return [pid for pid in super().get_eligible_targets(session, actor_id) if pid != actor_id]

    def can_use(self, session: Any, player_state: Any) -> tuple[bool, str | None]:
        current_night = session.metadata.get("night_num", 1)
        if current_night < 4:
            return False, "Public Reveal is locked until Night 4."

        last_used = player_state.metadata.get("ayanokoji_reveal_last_used")
        if last_used is not None:
            nights_passed = current_night - last_used
            if nights_passed < 4:
                return False, f"Public Reveal is on cooldown. You can use it again in {4 - nights_passed} Nights."

        return True, None

    async def execute(self, context: RoleContext) -> None:
        target_id = context.target_id
        session = context.payload.get("session")
        if not target_id or not session:
            return

        target_player = session.players.get(target_id)
        if not target_player:
            return

        player_state = session.players[context.user_id]
        player_state.metadata["ayanokoji_reveal_last_used"] = session.metadata.get("night_num", 1)

        role_key = target_player.role_key
        faction = target_player.faction

        import discord
        import roles
        role_meta = roles.ROLES_METADATA.get(role_key, {})
        role_display = role_meta.get("name", role_key.replace('_', ' ').title())

        faction_display = "Protagonist" if faction == RoleFaction.HERO.value else ("Antagonist" if faction == RoleFaction.VILLAIN.value else "Neutral")

        # Send public reveal message to the mafia channel
        mafia_ch_id = session.metadata.get("mafia_channel_id")
        if mafia_ch_id and context.bot:
            ch = context.bot.get_channel(mafia_ch_id)
            if not ch:
                try:
                    ch = await context.bot.fetch_channel(mafia_ch_id)
                except Exception:
                    pass
            if ch:
                from ui import build_v2_layout
                ayanokoji_view = build_v2_layout(
                    title=f"{get_emoji('ayanokoji')} Ayanokoji Kiyotaka — Mastermind Revelation",
                    description=(
                        f"Ayanokoji Kiyotaka has analyzed the targets from the shadows and exposed a player's true identity!\n\n"
                        f"👤 **Player:** <@{target_id}>\n"
                        f"🎭 **True Role:** **{role_display}**\n"
                        f"🍏 **Faction:** **{faction_display}**"
                    ),
                    color=discord.Color.purple(),
                    thumbnail_url=role_meta.get("image_url"),
                )
                await context.bot.message_queue.send(ch, view=ayanokoji_view)


        context.payload["result"] = f"{get_emoji('ayanokoji')} **Public Reveal:** You have publicly exposed <@{target_id}> as the **{role_display}** ({faction_display})."


@role_registry.register
class AyanokojiKiyotaka(BaseRole):
    role_key: ClassVar[str] = "ayanokoji_kiyotaka"
    priority: ClassVar[int] = 9
    tags: ClassVar[tuple[str, ...]] = (RoleCategory.INVESTIGATIVE,)
    cooldown_text: ClassVar[str] = "Public Reveal: 4 Days (Available from Night 4)"
    limitations_text: ClassVar[str] = "Unreadable: Immune to Framing, Forging, Mimicry, and other role/faction deceptions."

    def __init__(self) -> None:
        super().__init__()
        self.abilities = [AyanokojiObservation(), AyanokojiPublicReveal()]

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

        faction = target_player.metadata.get("disguised_faction", target_player.faction)
        if target_player.metadata.get("framed"):
            faction = RoleFaction.VILLAIN.value

        if scan_count >= 2:
            role_display = target_player.role_key.replace('_', ' ').title()
            context.payload["result"] = f"{get_emoji('detective')} **Deduction (Scan {scan_count}):** <@{target_id}>'s exact role is **{role_display}**."
        else:
            align_emoji = f"{get_emoji('hero')} Protagonist" if faction == RoleFaction.HERO.value else (f"{get_emoji('villain')} Antagonist" if faction == RoleFaction.VILLAIN.value else f"{get_emoji('neutral')} Neutral")
            context.payload["result"] = f"{get_emoji('detective')} **Deduction (Scan 1):** <@{target_id}>'s alignment is **{align_emoji}**."


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

        f1 = RoleFaction.VILLAIN.value if p1.metadata.get("framed") else p1.metadata.get("disguised_faction", p1.faction)
        f2 = RoleFaction.VILLAIN.value if p2.metadata.get("framed") else p2.metadata.get("disguised_faction", p2.faction)

        same = (f1 == f2)
        context.payload["result"] = f"{get_emoji('detective')} **Cross Examination:** <@{t1}> and <@{t2}> belong to **{'the same faction' if same else 'different factions'}**."


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


class TobiramaFlyingThunderCounter(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Flying Thunder Counter",
            description="Choose a player tonight. If they are attacked, completely nullify that attack even if it's unstoppable, and learn who the attackers were. (2 uses)",
            priority=1
        )

    def can_use(self, session: Any, player_state: Any) -> tuple[bool, str | None]:
        uses = player_state.metadata.setdefault("tobirama_counter_uses", 2)
        if uses <= 0:
            return False, "Flying Thunder Counter has no uses left."
        return True, None

    async def execute(self, context: RoleContext) -> None:
        target_id = context.target_id
        session = context.payload.get("session")
        if not target_id or not session:
            return

        player_state = session.players[context.user_id]
        uses = player_state.metadata.get("tobirama_counter_uses", 2)
        player_state.metadata["tobirama_counter_uses"] = max(0, uses - 1)

        session.metadata.setdefault("flying_thunder_counters", {})[target_id] = context.user_id
        context.payload["result"] = f"{get_emoji('zap')} **Flying Thunder Counter:** You have marked <@{target_id}>. You will counter any attacks against them tonight."


@role_registry.register
class TobiramaSenju(BaseRole):
    role_key: ClassVar[str] = "tobirama_senju"
    priority: ClassVar[int] = 1
    tags: ClassVar[tuple[str, ...]] = (RoleCategory.INVESTIGATIVE,)
    cooldown_text: ClassVar[str] = "None"
    limitations_text: ClassVar[str] = "Flying Thunder Counter: 2 uses"

    def __init__(self) -> None:
        super().__init__()
        self.abilities = [TobiramaSensory(), TobiramaFlyingThunderCounter()]

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
        context.payload["result"] = f"{get_emoji('sword')} **ODM Execution:** You launched a strike against <@{target_id}> (Precision strike active: **{precision}**)."


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
        context.payload["result"] = f"{get_emoji('sword')} **Precision Strike:** Your ODM Execution tonight will bypass standard protections."


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
            description="Examine a corpse to suspect 3 players, one of whom is the killer. Cooldown: 2 Nights.",
            priority=5
        )

    def can_use(self, session: Any, player_state: Any) -> tuple[bool, str | None]:
        last_used = player_state.metadata.get("maomao_postmortem_last_used")
        current_night = session.metadata.get("night_num", 1)
        if last_used is not None and current_night - last_used < 2:
            return False, f"Postmortem Analysis is on cooldown. You can use it again in {2 - (current_night - last_used)} Nights."
        
        # Check if there is any dead player to analyze
        dead_list = [pid for pid, pstate in session.players.items() if not pstate.alive]
        if not dead_list:
            return False, "No dead players to analyze."
        return True, None

    def get_eligible_targets(self, session: Any, actor_id: int) -> list[int]:
        return [pid for pid, pstate in session.players.items() if not pstate.alive]

    async def execute(self, context: RoleContext) -> None:
        target_id = context.target_id
        session = context.payload.get("session")
        if not target_id or not session:
            return

        player_state = session.players[context.user_id]
        player_state.metadata["maomao_postmortem_last_used"] = session.metadata.get("night_num", 1)

        target_player = session.players.get(target_id)
        if not target_player:
            return

        killer_id = target_player.metadata.get("killer_id")
        
        # Base pool of candidates: all other alive players excluding Maomao
        candidates = [pid for pid, pstate in session.players.items() if pid != context.user_id and pstate.alive]
        
        # If killer is not tracked or already dead, pick a fallback suspect from candidates
        if not killer_id or killer_id not in candidates:
            if candidates:
                import random
                killer_id = random.choice(candidates)
            else:
                killer_id = context.user_id  # fallback to self if absolutely nobody else

        # Check fresh corpse (killed yesterday/last night)
        # In game_engine.py, session.metadata["dead_last_night"] holds those killed last night
        dead_last_night = session.metadata.get("dead_last_night", [])
        is_fresh = target_id in dead_last_night

        import random
        guarantee_protagonist = False
        if is_fresh:
            if random.random() < 0.40:
                guarantee_protagonist = True

        other_names = []
        
        # Protagonists (alive Heroes/Protagonists excluding the killer)
        protagonists = [
            pid for pid in candidates 
            if pid != killer_id 
            and session.players[pid].faction == RoleFaction.HERO.value
        ]

        if guarantee_protagonist and protagonists:
            protag = random.choice(protagonists)
            other_names.append(protag)

        remaining_pool = [pid for pid in candidates if pid != killer_id and pid not in other_names]
        random.shuffle(remaining_pool)

        while len(other_names) < 2 and remaining_pool:
            other_names.append(remaining_pool.pop())

        final_list = [killer_id] + other_names
        random.shuffle(final_list)

        names_str = ", ".join([f"**{session.players[pid].character_name}** (<@{pid}>)" for pid in final_list])

        context.payload["result"] = (
            f"🧪 **Postmortem Analysis:** You analyzed <@{target_id}>'s corpse.\n"
            f"🔍 **Potential Suspects:** {names_str}\n"
            f"*(One of these players is the killer. The others are random.)*"
        )


class MaomaoBrewPotion(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Brew Potion",
            description="Brew a potion of your choice tonight. Cooldown: 2 Nights.",
            priority=1
        )

    def can_use(self, session: Any, player_state: Any) -> tuple[bool, str | None]:
        last_used = player_state.metadata.get("maomao_potion_last_used")
        current_night = session.metadata.get("night_num", 1)
        if last_used is not None and current_night - last_used < 2:
            return False, f"Brew Potion is on cooldown. You can use it again in {2 - (current_night - last_used)} Nights."
        return True, None

    def get_eligible_targets(self, session: Any, actor_id: int) -> list[int]:
        return [pid for pid, pstate in session.players.items() if pstate.alive]

    async def execute(self, context: RoleContext) -> None:
        target_id = context.target_id
        session = context.payload.get("session")
        if not target_id or not session:
            return

        potion_choice = context.payload.get("potion_choice")
        if not potion_choice:
            return

        player_state = session.players[context.user_id]
        player_state.metadata["maomao_potion_last_used"] = session.metadata.get("night_num", 1)

        target_player = session.players.get(target_id)
        if not target_player:
            return

        # Reset any existing visibility flag just in case
        target_player.metadata.pop("invisible", None)

        if potion_choice == "truth":
            faction = target_player.metadata.get("disguised_faction", target_player.faction)
            faction_display = "Protagonist" if faction == RoleFaction.HERO.value else ("Antagonist" if faction == RoleFaction.VILLAIN.value else "Neutral")
            context.payload["result"] = f"🧪 **Potion of Truth:** <@{target_id}>'s faction is **{faction_display}**."
            
        elif potion_choice == "invisibility":
            target_player.metadata["invisible"] = True
            context.payload["result"] = f"🧪 **Potion of Invisibility:** You made <@{target_id}> invisible. They are immune to all night actions tonight."
            
        elif potion_choice == "happiness":
            target_player.metadata["roleblocked"] = True
            context.payload["result"] = f"🧪 **Potion of Happiness:** You distracted (roleblocked) <@{target_id}>."
            
        elif potion_choice == "revitalization":
            cooldown_keys = [
                "last_surgery_night", "last_kamehameha_night", "dazai_nullify_last_used",
                "asta_divider_last_used", "ayanokoji_reveal_last_used", "maomao_postmortem_last_used",
                "last_block_night", "maomao_potion_last_used"
            ]
            for key in cooldown_keys:
                target_player.metadata.pop(key, None)
            context.payload["result"] = f"🧪 **Potion of Revitalization:** Restored all ability cooldowns for <@{target_id}>."
            
        elif potion_choice == "intelligence":
            target_player.vote_weight = 2
            context.payload["result"] = f"🧪 **Potion of Intelligence:** <@{target_id}> gains +1 vote (total weight: 2) for the next day."


@role_registry.register
class Maomao(BaseRole):
    role_key: ClassVar[str] = "maomao"
    priority: ClassVar[int] = 5
    tags: ClassVar[tuple[str, ...]] = (RoleCategory.UTILITY,)
    cooldown_text: ClassVar[str] = "Postmortem Analysis: 2 Nights, Brew Potion: 2 Nights"
    limitations_text: ClassVar[str] = "None"

    def __init__(self) -> None:
        super().__init__()
        self.abilities = [MaomaoPostmortem(), MaomaoBrewPotion()]

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


class FrierenDemonDetection(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Demon Detection",
            description="Choose three players. You will learn how many of them belong to the antagonists faction. (No cooldown)",
            priority=5
        )
        self.num_targets = 3

    def get_eligible_targets(self, session: Any, actor_id: int) -> list[int]:
        return [pid for pid, pstate in session.players.items() if pstate.alive and pid != actor_id]

    async def execute(self, context: RoleContext) -> None:
        targets = context.targets
        session = context.payload.get("session")
        if len(targets) < 3 or not session:
            return

        antag_count = 0
        for pid in targets:
            pstate = session.players.get(pid)
            if pstate:
                f = RoleFaction.VILLAIN.value if pstate.metadata.get("framed") else pstate.metadata.get("disguised_faction", pstate.faction)
                if f == RoleFaction.VILLAIN.value:
                    antag_count += 1

        context.payload["result"] = f"✨ **Demon Detection:** Out of the three chosen players, exactly **{antag_count}** belong to the antagonists."


class FrierenZoltraakSpecialist(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Zoltraak Specialist",
            description="Disable the passives of all opposing faction members (Villains and Neutrals) tonight. Cooldown: 2 Nights.",
            priority=1
        )
        self.num_targets = 0

    def can_use(self, session: Any, player_state: Any) -> tuple[bool, str | None]:
        last_used = player_state.metadata.get("zoltraak_last_used")
        current_night = session.metadata.get("night_num", 1)
        if last_used is not None and current_night - last_used < 2:
            return False, f"Zoltraak Specialist is on cooldown. You can use it again in {2 - (current_night - last_used)} Nights."
          
        return True, None

    async def execute(self, context: RoleContext) -> None:
        session = context.payload.get("session")
        if not session:
            return

        player_state = session.players[context.user_id]
        player_state.metadata["zoltraak_last_used"] = session.metadata.get("night_num", 1)

        session.metadata["zoltraak_active"] = True
        context.payload["result"] = "✨ **Zoltraak Specialist:** You have activated Zoltraak Specialist. Passives of all antagonists and neutrals are disabled tonight."


@role_registry.register
class Frieren(BaseRole):
    role_key: ClassVar[str] = "frieren"
    priority: ClassVar[int] = 1
    tags: ClassVar[tuple[str, ...]] = (RoleCategory.UTILITY,)
    cooldown_text: ClassVar[str] = "Ancient Binding: 2 Days on success, Zoltraak Specialist: 2 Nights"
    limitations_text: ClassVar[str] = "None"

    def __init__(self) -> None:
        super().__init__()
        self.abilities = [FrierenAncientBinding(), FrierenDemonDetection(), FrierenZoltraakSpecialist()]

    async def get_night_feedback(self, context: RoleContext) -> str | None:
        return context.payload.get("result")


# =============================================================================
# Villager
# =============================================================================

@role_registry.register
class DefaultVillager(BaseRole):
    role_key: ClassVar[str] = "villager"
    priority: ClassVar[int] = 5
    tags: ClassVar[tuple[str, ...]] = (RoleCategory.COUNCIL,)
    is_unique: ClassVar[bool] = False
    cooldown_text: ClassVar[str] = "None"
    limitations_text: ClassVar[str] = "None"


# =============================================================================
# Kishibe (Town Killing)
# =============================================================================

class KishibeAlert(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Veteran's Instinct (Alert)",
            description="Go on Alert tonight. Anyone who visits you will be hit with a Powerful Attack (3 charges total).",
            priority=1
        )

    def can_use(self, session, player_state):
        alerts = player_state.metadata.get("alerts_left", 3)
        if alerts <= 0:
            return False, "You have no Alert charges remaining."
        return True, None

    async def execute(self, context):
        session = context.payload.get("session")
        if not session:
            return
        pstate = session.players.get(context.user_id)
        if not pstate:
            return
        alerts = pstate.metadata.get("alerts_left", 3)
        remaining = max(0, alerts - 1)
        context.payload["log"] = f"Kishibe went on Alert. ({remaining} charges remaining after this night)"
        context.payload["result"] = (
            f"🥃 **Alert Active!** You are on guard tonight. Anyone who visits you will be attacked with a Powerful Attack.\n"
            f"Alert charges after tonight: **{remaining}/3**."
        )

    async def get_night_feedback(self, context):
        return context.payload.get("result")


class KishibeBrokenScrew(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Broken Screw",
            description="(Once per game) Choose a player. If they visit you tonight while on Alert, your Alert charge is not consumed.",
            priority=1
        )

    def can_use(self, session, player_state):
        alerts = player_state.metadata.get("alerts_left", 3)
        if alerts <= 0:
            return False, "You have no Alert charges remaining."
        if player_state.metadata.get("broken_screw_used"):
            return False, "You have already used Broken Screw."
        return True, None

    async def execute(self, context):
        target_id = context.target_id
        if not target_id:
            return
        session = context.payload.get("session")
        if not session:
            return
        pstate = session.players.get(context.user_id)
        if not pstate:
            return
        pstate.metadata["broken_screw_used"] = True
        context.payload["log"] = f"Kishibe used Broken Screw on <@{target_id}>."
        context.payload["result"] = (
            f"🥃 **Broken Screw Active!** You are on Alert. If <@{target_id}> visits you tonight, "
            f"your Alert charge will be saved."
        )

    async def get_night_feedback(self, context):
        return context.payload.get("result")


@role_registry.register
class Kishibe(BaseRole):
    role_key = "kishibe"
    priority = 1
    tags = (RoleCategory.KILLING,)
    is_unique = True
    cooldown_text = "None"
    limitations_text = "Alert has 3 charges. Broken Screw is once per game."

    def __init__(self) -> None:
        super().__init__()
        self.abilities = [KishibeAlert(), KishibeBrokenScrew()]


# =============================================================================
# Kaname Tosen (Vanguard / Town Killing)
# =============================================================================

import asyncio as _asyncio_town


class TosenBankai(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Bankai: Enma Korogi",
            description=(
                "Detain a player inside your Bankai. They cannot act and cannot be targeted by others tonight. "
                "Communicate privately via DM (prefix with '.'). Next night: release or execute them."
            ),
            priority=1
        )

    async def execute(self, context):
        target_id = context.target_id
        if not target_id:
            return
        session = context.payload.get("session")
        if not session:
            return
        tosen_state = session.players.get(context.user_id)
        if not tosen_state:
            return

        prev_id = tosen_state.metadata.get("detained_player_id")
        if prev_id and prev_id != target_id:
            prev = session.players.get(prev_id)
            if prev:
                prev.metadata.pop("detained", None)

        tosen_state.metadata["detained_player_id"] = target_id
        prisoner_state = session.players.get(target_id)
        if prisoner_state:
            prisoner_state.metadata["detained"] = True

        context.payload["log"] = f"Tosen detained <@{target_id}> inside Enma Korogi."
        context.payload["result"] = (
            f"🌑 **Bankai Active!** You have detained <@{target_id}> inside Enma Korogi.\n"
            f"They cannot act or be targeted tonight. Communicate via DM by prefixing with **'.'**\n"
            f"Next night: choose to **release** and detain someone new, or **execute** them."
        )

        import asyncio
        async def _notify(s=session, p_id=target_id, bot=context.bot):
            if not bot:
                return
            guild = bot.get_guild(s.game_handle.guild_id)
            if not guild:
                return
            p_member = guild.get_member(p_id)
            if p_member:
                try:
                    bot.message_queue.send(
                        p_member,
                        "🌑 **Enma Korogi - You Have Been Detained!**\n"
                        "Kaname Tosen has imprisoned you inside his Bankai tonight.\n"
                        "- You **cannot** perform your night ability.\n"
                        "- You **cannot** be targeted by other players.\n"
                        "- You **may** privately message Tosen by sending a DM starting with a dot (e.g. `.hello`)."
                    )
                except Exception:
                    pass
        asyncio.create_task(_notify())

    async def get_night_feedback(self, context):
        return context.payload.get("result")


class TosenExecute(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Execute Prisoner",
            description=(
                "Execute your currently detained prisoner with absolute judgment. "
                "Vanguard prisoner: they die, you lose execution ability permanently. "
                "Abyss/Rogues prisoner: they die, you retain remaining executions. "
                "Max 3 executions. Bypasses all protection and death-evasion passives."
            ),
            priority=2
        )

    def can_use(self, session, player_state):
        if player_state.metadata.get("lost_execution_ability"):
            return False, "You have permanently lost the ability to execute (you executed a Vanguard member)."
        execs = player_state.metadata.get("executions_left", 3)
        if execs <= 0:
            return False, "You have no execution charges remaining (max 3 executions)."
        if not player_state.metadata.get("detained_player_id"):
            return False, "You have no prisoner currently detained."
        return True, None

    async def execute(self, context):
        session = context.payload.get("session")
        if not session:
            return
        tosen_state = session.players.get(context.user_id)
        if not tosen_state:
            return
        prisoner_id = tosen_state.metadata.get("detained_player_id")
        if not prisoner_id:
            context.payload["error"] = "No prisoner to execute."
            return
        prisoner_state = session.players.get(prisoner_id)
        if not prisoner_state or not prisoner_state.alive:
            tosen_state.metadata["detained_player_id"] = None
            context.payload["error"] = "Your prisoner is already dead."
            return
        kills = session.metadata.setdefault("pending_kills", {})
        kills[prisoner_id] = kills.get(prisoner_id, []) + ["tosen_kill"]
        context.payload["log"] = f"Tosen delivered absolute judgment upon <@{prisoner_id}>."
        context.payload["result"] = f"🌑 **Judgment Delivered.** You have executed <@{prisoner_id}>."

    async def get_night_feedback(self, context):
        return context.payload.get("result")


@role_registry.register
class KanameTosen(BaseRole):
    role_key = "tosen"
    priority = 1
    tags = (RoleCategory.KILLING,)
    is_unique = True
    cooldown_text = "None"
    limitations_text = (
        "Max 3 executions. Executing a Vanguard member permanently removes your execution ability. "
        "Suzumushi passive: Bankai prisoners cannot trigger death abilities or evade death."
    )

    def __init__(self) -> None:
        super().__init__()
        self.abilities = [TosenBankai(), TosenExecute()]


# =============================================================================
# Osamu Dazai (No Longer Human)
# =============================================================================

class DazaiNoLongerHuman(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="No Longer Human",
            description="Nullify target's supernatural abilities for the night. Cooldown: 1 Night.",
            priority=0  # Runs first to nullify before any action executes
        )

    def can_use(self, session, player_state):
        last_used = player_state.metadata.get("dazai_nullify_last_used")
        if last_used is not None and session.metadata.get("night_num", 1) - last_used < 2:
            return False, f"No Longer Human is on cooldown until Night {last_used + 2}."
        return True, None

    async def execute(self, context):
        target_id = context.target_id
        if not target_id:
            return
        session = context.payload.get("session")
        if not session:
            return
        
        dazai_state = session.players.get(context.user_id)
        if dazai_state:
            dazai_state.metadata["dazai_nullify_last_used"] = session.metadata.get("night_num", 1)

        target_state = session.players.get(target_id)
        if target_state:
            # Asta is immune to negative non-physical abilities (like Dazai's nullification)
            if target_state.role_key == "asta":
                context.payload["log"] = f"Dazai attempted to nullify <@{target_id}>, but their Anti-Magic resisted it!"
                context.payload["result"] = "Your target resisted your ability."
                return

            target_state.metadata["nullified"] = True
            context.payload["log"] = f"Dazai nullified <@{target_id}>'s abilities."
            context.payload["result"] = f"✋ **No Longer Human!** You have nullified <@{target_id}>'s abilities tonight."

            # Notify target
            import asyncio
            async def notify_nullified(s=session, t_id=target_id, bot=context.bot):
                if bot:
                    guild = bot.get_guild(s.game_handle.guild_id)
                    member = guild.get_member(t_id) if guild else None
                    if member:
                        try:
                            bot.message_queue.send(member, f"{get_emoji('cross')} **Your abilities were nullified tonight.**")
                        except Exception:
                            pass
            asyncio.create_task(notify_nullified())

    async def get_night_feedback(self, context):
        return context.payload.get("result")


@role_registry.register
class OsamuDazai(BaseRole):
    role_key = "dazai"
    priority = 1
    tags = (RoleCategory.UTILITY,)
    is_unique = True
    cooldown_text = "1 Night"
    limitations_text = "Unpredictable passive: Immune to redirects, control, or forced visits."

    def __init__(self) -> None:
        super().__init__()
        self.abilities = [DazaiNoLongerHuman()]


# =============================================================================
# Asta (Anti-Magic Knight)
# =============================================================================

class AstaDemonDestroyer(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Demon Destroyer Sword",
            description="Remove all negative status effects from a player.",
            priority=1  # Runs early to cleanse targets before they act if possible
        )

    async def execute(self, context):
        target_id = context.target_id
        if not target_id:
            return
        session = context.payload.get("session")
        if not session:
            return

        target_state = session.players.get(target_id)
        if target_state:
            # Cleanses negative effects
            cleansed = []
            negative_keys = ["framed", "silenced", "cursed", "hexed", "poisoned", "marked", "roleblocked", "ability_disabled", "nullified", "black_divider_nullified"]
            for key in negative_keys:
                if target_state.metadata.pop(key, None) is not None:
                    cleansed.append(key)

            context.payload["log"] = f"Asta cleansed <@{target_id}> of negative effects: {', '.join(cleansed) if cleansed else 'none'}."
            context.payload["result"] = f"{get_emoji('sword')} **Demon Destroyer Sword!** You have cleansed <@{target_id}> of all negative status effects."

            # Notify target
            if cleansed:
                import asyncio
                async def notify_cleansed(s=session, t_id=target_id, bot=context.bot):
                    if bot:
                        guild = bot.get_guild(s.game_handle.guild_id)
                        member = guild.get_member(t_id) if guild else None
                        if member:
                            try:
                                bot.message_queue.send(member, f"{get_emoji('sword')} **Asta's Demon Destroyer Sword has cleansed you of all negative effects!**")
                            except Exception:
                                pass
                asyncio.create_task(notify_cleansed())

    async def get_night_feedback(self, context):
        return context.payload.get("result")


class AstaBlackDivider(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Black Divider",
            description="Target a player. If they attempt to act, nullify their ability, bypassing immunity. Cooldown: 1 Night.",
            priority=1
        )

    def can_use(self, session, player_state):
        last_used = player_state.metadata.get("asta_divider_last_used")
        if last_used is not None and session.metadata.get("night_num", 1) - last_used < 2:
            return False, f"Black Divider is on cooldown until Night {last_used + 2}."
        return True, None

    async def execute(self, context):
        target_id = context.target_id
        if not target_id:
            return
        session = context.payload.get("session")
        if not session:
            return

        asta_state = session.players.get(context.user_id)
        if asta_state:
            asta_state.metadata["asta_divider_last_used"] = session.metadata.get("night_num", 1)

        target_state = session.players.get(target_id)
        if target_state:
            target_state.metadata["black_divider_nullified"] = True
            context.payload["log"] = f"Asta targeted <@{target_id}> with Black Divider."
            context.payload["result"] = f"{get_emoji('sword')} **Black Divider Active!** If <@{target_id}> attempts to use an ability tonight, it will be nullified."

    async def get_night_feedback(self, context):
        return context.payload.get("result")


class AstaDevilUnion(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Devil Union",
            description="For one night, every hostile ability targeting Town is nullified. (Once per game)",
            priority=1
        )
        self.num_targets = 0

    def can_use(self, session, player_state):
        if player_state.metadata.get("devil_union_used"):
            return False, "You have already used Devil Union once this game."
        return True, None

    async def execute(self, context):
        session = context.payload.get("session")
        if not session:
            return

        asta_state = session.players.get(context.user_id)
        if asta_state:
            asta_state.metadata["devil_union_used"] = True

        session.metadata["devil_union_active"] = True
        context.payload["log"] = "Asta activated Devil Union!"
        context.payload["result"] = "😈 **Devil Union Activated!** For tonight, all hostile actions targeting Town players will fail."

    async def get_night_feedback(self, context):
        return context.payload.get("result")


@role_registry.register
class Asta(BaseRole):
    role_key = "asta"
    priority = 1
    tags = (RoleCategory.UTILITY,)
    is_unique = True
    cooldown_text = "Black Divider: 1 Night. Devil Union: Once per game."
    limitations_text = "Anti-Magic passive: Immune to non-physical negative abilities and redirects."

    def __init__(self) -> None:
        super().__init__()
        self.abilities = [AstaDemonDestroyer(), AstaBlackDivider(), AstaDevilUnion()]
