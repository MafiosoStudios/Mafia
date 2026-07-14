from __future__ import annotations

import random
from typing import ClassVar, Any
from utils.roles import BaseRole, RoleContext, RoleCategory, role_registry, NightAction, PassiveEffect, WinCondition
from utils.constants import RoleFaction
from config import get_emoji


# --- Hisoka ---

class HisokaWinCondition(WinCondition):
    def __init__(self) -> None:
        super().__init__("WinCondition 1: Get voted out before Night 5 (revive for 3 days). WinCondition 2: Correctly predict two players visiting one another 3 times using Bungee Gum.")

    def check(self, alive_factions: frozenset[str], context: RoleContext) -> bool:
        session = context.payload.get("session")
        if not session:
            return False
        player_state = session.players.get(context.user_id)
        if not player_state:
            return False
        
        # Win Condition 1: Voted out before/on night 5 and revived
        if player_state.metadata.get("post_mortem_win"):
            return True
            
        # Win Condition 2: Bungee gum 3 points
        points = player_state.metadata.get("bungee_points", 0)
        if points >= 3:
            player_state.metadata["won_via_bungee"] = True
            return True

        return False


class HisokaBungee(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Bungee Gum",
            description="Bungee Gum (Link two players. If one visits the other, gain 1 point. Need 3 points). Or Post-Mortem Nen abilities.",
            priority=4
        )

    async def execute(self, context: RoleContext) -> None:
        session = context.payload.get("session")
        if not session:
            return
            
        player_state = session.players[context.user_id]
        
        # Check if Hisoka is revived (Post Mortem Nen active)
        if player_state.metadata.get("revived"):
            days_left = player_state.metadata.get("revived_days_left", 0)
            target_id = context.target_id
            if not target_id:
                return

            if days_left == 3:
                # 1st Night after revival: BM (roleblock)
                target_player = session.players.get(target_id)
                if target_player:
                    target_player.metadata["roleblocked"] = True
                    context.payload["log"] = f"Hisoka blackmailed/roleblocked <@{target_id}>!"
            elif days_left == 2:
                # 2nd Night after revival: Farm (steal/reveal role)
                target_player = session.players.get(target_id)
                if target_player:
                    context.payload["result"] = f"Hisoka farmed <@{target_id}>: Their role is **{target_player.role_key}**."
            elif days_left == 1:
                # 3rd Night after revival: Kill
                kills = session.metadata.setdefault("pending_kills", {})
                kills[target_id] = kills.get(target_id, []) + ["hisoka_nen_kill"]
                context.payload["log"] = f"Hisoka unleashed Post-Mortem Nen and attacked <@{target_id}>!"
            return

        # Normal Bungee Gum Action: Link two players
        target1 = context.target_id
        target2 = context.payload.get("controlled_vote_target")
        if not target1 or not target2:
            context.payload["error"] = "Must select two players to Bungee Gum."
            return

        links = session.metadata.setdefault("bungee_gum_links", {})
        links[context.user_id] = (target1, target2)
        context.payload["log"] = f"Hisoka bungee gummed <@{target1}> and <@{target2}>."


@role_registry.register
class Hisoka(BaseRole):
    role_key: ClassVar[str] = "hisoka"
    priority: ClassVar[int] = 4
    tags: ClassVar[tuple[str, ...]] = (RoleCategory.NEUTRAL, "chaos")
    continues_game_after_win: ClassVar[bool] = True
    cooldown_text: ClassVar[str] = "None"
    limitations_text: ClassVar[str] = "Bungee Gum requires two targets. Post-Mortem Nen is active for exactly 3 days."

    def __init__(self) -> None:
        super().__init__()
        self.abilities = [HisokaBungee()]
        self.win_condition_obj = HisokaWinCondition()

    async def get_night_feedback(self, context: RoleContext) -> str | None:
        target_id = context.payload.get("target_id")
        player_state = context.payload.get("session").players.get(context.user_id) if context.payload.get("session") else None
        
        if player_state and player_state.metadata.get("revived"):
            days_left = player_state.metadata.get("revived_days_left", 0)
            if days_left == 3:
                return f"🃏 **Post-Mortem Nen: You successfully roleblocked <@{target_id}> tonight!**"
            elif days_left == 1:
                return f"🃏 **Post-Mortem Nen: You unleashed Bungee Gum and killed <@{target_id}>!**"
        return None


# --- Gilgamesh ---

class GilgameshWinCondition(WinCondition):
    def __init__(self) -> None:
        super().__init__("Find all of your swords to become the Horseman of Apocalypse, then survive for 1 day to trigger the Rumbling apocalypse.")

    def check(self, alive_factions: frozenset[str], context: RoleContext) -> bool:
        session = context.payload.get("session")
        if not session:
            return False
        player_state = session.players.get(context.user_id)
        if not player_state:
            return False
        
        # If transformed, and survived 1 day without being lynched
        if player_state.metadata.get("transformed"):
            current_day = session.metadata.get("day_num", 1)
            trans_day = player_state.metadata.get("transformation_day", 1)
            if current_day > trans_day and player_state.alive:
                player_state.metadata["apocalypse_triggered"] = True
                return True
        return False


class GilgameshGate(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Gate of Babylon",
            description="Visit a player to search for your sword.",
            priority=5
        )

    async def execute(self, context: RoleContext) -> None:
        session = context.payload.get("session")
        if not session:
            return
            
        player_state = session.players[context.user_id]
        target_id = context.target_id
        if not target_id:
            return

        if player_state.metadata.get("transformed"):
            context.payload["error"] = "You have already transformed! Prepare for the apocalypse."
            return

        swords_owners = session.metadata.get("gilgamesh_swords", [])
        found_swords = player_state.metadata.setdefault("swords_found", [])

        if target_id in swords_owners and target_id not in found_swords:
            found_swords.append(target_id)
            context.payload["result"] = f"You found one of your swords in <@{target_id}>'s possession! ({len(found_swords)}/{len(swords_owners)})"
            
            if len(found_swords) == len(swords_owners):
                player_state.metadata["transformed"] = True
                player_state.metadata["transformation_day"] = session.metadata.get("day_num", 1)
                context.payload["result"] += "\n**You have found all your swords! You will transform into the Horseman of Apocalypse tomorrow!**"
        else:
            context.payload["result"] = f"No sword found with <@{target_id}>."


@role_registry.register
class Gilgamesh(BaseRole):
    role_key: ClassVar[str] = "gilgamesh"
    priority: ClassVar[int] = 5
    tags: ClassVar[tuple[str, ...]] = (RoleCategory.NEUTRAL, "apocalypse")
    is_hostile_neutral: ClassVar[bool] = True
    cooldown_text: ClassVar[str] = "None"
    limitations_text: ClassVar[str] = "Searching is disabled once transformed."

    def __init__(self) -> None:
        super().__init__()
        self.abilities = [GilgameshGate()]
        self.win_condition_obj = GilgameshWinCondition()

    async def on_game_start(self, session: Any, user_id: int) -> None:
        num_swords = min(5, len(session.player_ids) // 3 + 1)
        sword_candidates = list(session.player_ids)
        if user_id in sword_candidates:
            sword_candidates.remove(user_id)
        swords_list = random.sample(sword_candidates, min(num_swords, len(sword_candidates)))
        session.metadata["gilgamesh_swords"] = swords_list


# --- Lelouch Lamperouge ---

class LelouchWinCondition(WinCondition):
    def __init__(self) -> None:
        super().__init__("Geass guess: Declare you will be voted out. If lynched that day, you win.")

    def check(self, alive_factions: frozenset[str], context: RoleContext) -> bool:
        session = context.payload.get("session")
        if not session:
            return False
        player_state = session.players.get(context.user_id)
        if player_state and player_state.metadata.get("zero_requiem_win"):
            return True
        return False


@role_registry.register
class LelouchLamperouge(BaseRole):
    role_key: ClassVar[str] = "lelouch_lamperouge"
    priority: ClassVar[int] = 5
    tags: ClassVar[tuple[str, ...]] = (RoleCategory.NEUTRAL, "benign")
    continues_game_after_win: ClassVar[bool] = True
    cooldown_text: ClassVar[str] = "Cannot declare on consecutive days."
    limitations_text: ClassVar[str] = "Max 3 incorrect declarations."

    def __init__(self) -> None:
        super().__init__()
        self.win_condition_obj = LelouchWinCondition()


# --- Eren Jaeger ---

class ErenWinCondition(WinCondition):
    def __init__(self) -> None:
        super().__init__("Survive until Night 8 to trigger The Rumbling, then kill everyone until you are the last one standing.")

    def check(self, alive_factions: frozenset[str], context: RoleContext) -> bool:
        session = context.payload.get("session")
        if not session:
            return False
        player_state = session.players.get(context.user_id)
        if not player_state:
            return False
            
        current_night = session.metadata.get("night_num", 1)
        if current_night >= 9:
            alive_players = [pid for pid, pstate in session.players.items() if pstate.alive]
            if len(alive_players) == 1 and alive_players[0] == context.user_id:
                player_state.metadata["rumbling_win"] = True
                return True
        return False


class ErenRumble(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Founding Vision / The Rumbling",
            description="Founding Vision: Learn player faction. The Rumbling (Night 9+): Crush and kill a target.",
            priority=4
        )

    async def execute(self, context: RoleContext) -> None:
        session = context.payload.get("session")
        if not session:
            return
            
        target_id = context.target_id
        if not target_id:
            return

        current_night = session.metadata.get("night_num", 1)

        # Active Rumbling: Kill
        if current_night >= 9:
            kills = session.metadata.setdefault("pending_kills", {})
            kills[target_id] = kills.get(target_id, []) + ["rumbling"]
            context.payload["log"] = f"Eren Jaeger's Rumbling crushed <@{target_id}>!"
            return

        # Normal Founding Vision: check side
        target_player = session.players.get(target_id)
        if target_player:
            context.payload["result"] = f"Founding Vision: <@{target_id}> belongs to **{target_player.faction}**."


@role_registry.register
class ErenJaeger(BaseRole):
    role_key: ClassVar[str] = "eren_jaeger"
    priority: ClassVar[int] = 4
    tags: ClassVar[tuple[str, ...]] = (RoleCategory.NEUTRAL, "apocalypse")
    is_hostile_neutral: ClassVar[bool] = True
    cooldown_text: ClassVar[str] = "None"
    limitations_text: ClassVar[str] = "The Rumbling kills are only active Night 9 onwards."

    def __init__(self) -> None:
        super().__init__()
        self.abilities = [ErenRumble()]
        self.win_condition_obj = ErenWinCondition()

    def is_active_threat(self, session: Any, player_state: Any) -> bool:
        return player_state.alive and session.metadata.get("night_num", 1) >= 9


# --- Mahoraga ---

class MahoragaWinCondition(WinCondition):
    def __init__(self) -> None:
        super().__init__("Survive an attack and eliminate at least 1 player who tried to kill you.")

    def check(self, alive_factions: frozenset[str], context: RoleContext) -> bool:
        session = context.payload.get("session")
        if not session:
            return False
        player_state = session.players.get(context.user_id)
        if not player_state:
            return False
            
        attackers = player_state.metadata.get("attackers", [])
        if not attackers:
            return False
            
        for attacker_id in attackers:
            attacker_state = session.players.get(attacker_id)
            if attacker_state and not attacker_state.alive:
                return True
        return False


class MahoragaAdapt(PassiveEffect):
    def __init__(self) -> None:
        super().__init__(
            name="Adaptation",
            description="75% chance to survive attacks. Upon surviving, gain permanent immunity and lynch immunity for 1 day."
        )

    async def resolve_protection(self, context: RoleContext, attack_sources: list[str]) -> bool:
        session = context.payload.get("session")
        if not session:
            return False
            
        player_state = session.players.get(context.user_id)
        if player_state:
            attacker_ids = []
            for actor_id, payload in session.night_actions.items():
                if payload.get("target_id") == context.user_id:
                    attacker_ids.append(actor_id)

            if random.random() < 0.75:
                mahoraga_attackers = player_state.metadata.setdefault("attackers", [])
                mahoraga_attackers.extend(attacker_ids)

                day_num = session.metadata.get("day_num", 1)
                player_state.metadata["lynch_immune_day"] = day_num + 1

                # Send adaptation notification
                guild = context.bot.get_guild(session.game_handle.guild_id) if (context.bot and session.game_handle) else None
                if guild:
                    mahoraga_mem = guild.get_member(context.user_id)
                    if mahoraga_mem:
                        context.bot.message_queue.send(
                            mahoraga_mem,
                            f"{get_emoji('shield')} **Adaptation triggered!** You survived the attack, adapted to their roles, "
                            "and gained lynch immunity for tomorrow!"
                        )
                return True
        return False


@role_registry.register
class Mahoraga(BaseRole):
    role_key: ClassVar[str] = "mahoraga"
    priority: ClassVar[int] = 5
    tags: ClassVar[tuple[str, ...]] = (RoleCategory.NEUTRAL, "survival")
    is_unique: ClassVar[bool] = False
    cooldown_text: ClassVar[str] = "None"
    limitations_text: ClassVar[str] = "No active night actions."

    def __init__(self) -> None:
        super().__init__()
        self.passives = [MahoragaAdapt()]
        self.win_condition_obj = MahoragaWinCondition()
