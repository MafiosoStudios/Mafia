from __future__ import annotations

import random
from typing import ClassVar, Any
from utils.roles import BaseRole, RoleContext, role_registry
from utils.constants import RoleFaction

@role_registry.register
class Hisoka(BaseRole):
    role_key: ClassVar[str] = "hisoka"
    priority: ClassVar[int] = 4

    async def night_action(self, context: RoleContext) -> None:
        session = context.payload.get("session")
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
        target2 = context.payload.get("controlled_vote_target")  # reuse payload key for 2nd target
        if not target1 or not target2:
            context.payload["error"] = "Must select two players to Bungee Gum."
            return

        # Store bungee links for night resolution check
        links = session.metadata.setdefault("bungee_gum_links", {})
        links[context.user_id] = (target1, target2)
        context.payload["log"] = f"Hisoka bungee gummed <@{target1}> and <@{target2}>."

    def win_condition_met(self, alive_factions: frozenset[str], context: RoleContext) -> bool:
        session = context.payload.get("session")
        player_state = session.players[context.user_id]
        
        # Win Condition 1: Voted out before/on night 5 and revived
        if player_state.metadata.get("post_mortem_win"):
            return True
            
        # Win Condition 2: Bungee gum 3 points
        points = player_state.metadata.get("bungee_points", 0)
        if points >= 3:
            player_state.metadata["won_via_bungee"] = True
            return True

        return False


@role_registry.register
class Gilgamesh(BaseRole):
    role_key: ClassVar[str] = "gilgamesh"
    priority: ClassVar[int] = 5

    async def night_action(self, context: RoleContext) -> None:
        session = context.payload.get("session")
        player_state = session.players[context.user_id]
        target_id = context.target_id
        if not target_id:
            return

        # Gilgamesh is transformed: Gates of Babylon destroys everyone
        if player_state.metadata.get("transformed"):
            context.payload["error"] = "You have already transformed! Prepare for the apocalypse."
            return

        # Search target for sword
        swords_owners = session.metadata.get("gilgamesh_swords", [])
        found_swords = player_state.metadata.setdefault("swords_found", [])

        if target_id in swords_owners and target_id not in found_swords:
            found_swords.append(target_id)
            context.payload["result"] = f"You found one of your swords in <@{target_id}>'s possession! ({len(found_swords)}/{len(swords_owners)})"
            
            # Check for transformation
            if len(found_swords) == len(swords_owners):
                player_state.metadata["transformed"] = True
                player_state.metadata["transformation_day"] = session.metadata.get("day_num", 1)
                context.payload["result"] += "\n**You have found all your swords! You will transform into the Horseman of Apocalypse tomorrow!**"
        else:
            context.payload["result"] = f"No sword found with <@{target_id}>."

    def win_condition_met(self, alive_factions: frozenset[str], context: RoleContext) -> bool:
        session = context.payload.get("session")
        player_state = session.players[context.user_id]
        
        # If transformed, and survived 1 day without being lynched
        if player_state.metadata.get("transformed"):
            current_day = session.metadata.get("day_num", 1)
            trans_day = player_state.metadata.get("transformation_day", 1)
            if current_day > trans_day and player_state.alive:
                player_state.metadata["apocalypse_triggered"] = True
                return True
        return False


@role_registry.register
class LelouchLamperouge(BaseRole):
    role_key: ClassVar[str] = "lelouch_lamperouge"
    priority: ClassVar[int] = 5

    def win_condition_met(self, alive_factions: frozenset[str], context: RoleContext) -> bool:
        session = context.payload.get("session")
        player_state = session.players[context.user_id]
        
        # If successfully lynched on the day he guessed he would be voted out
        if player_state.metadata.get("zero_requiem_win"):
            return True
        return False


@role_registry.register
class ErenJaeger(BaseRole):
    role_key: ClassVar[str] = "eren_jaeger"
    priority: ClassVar[int] = 4

    async def night_action(self, context: RoleContext) -> None:
        session = context.payload.get("session")
        player_state = session.players[context.user_id]
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

    def win_condition_met(self, alive_factions: frozenset[str], context: RoleContext) -> bool:
        session = context.payload.get("session")
        player_state = session.players[context.user_id]
        
        # Rumbling must be active (night >= 9) and Eren must be the only survivor
        current_night = session.metadata.get("night_num", 1)
        if current_night >= 9:
            alive_players = [pid for pid, pstate in session.players.items() if pstate.alive]
            if len(alive_players) == 1 and alive_players[0] == context.user_id:
                player_state.metadata["rumbling_win"] = True
                return True
        return False


@role_registry.register
class Mahoraga(BaseRole):
    role_key: ClassVar[str] = "mahoraga"
    priority: ClassVar[int] = 5

    def win_condition_met(self, alive_factions: frozenset[str], context: RoleContext) -> bool:
        session = context.payload.get("session")
        player_state = session.players[context.user_id]
        
        # Kill at least 1 player who tried to kill you
        attackers = player_state.metadata.get("attackers", [])
        if not attackers:
            return False
            
        for attacker_id in attackers:
            attacker_state = session.players.get(attacker_id)
            if attacker_state and not attacker_state.alive:
                # Attacker died (could be voted out or killed by anyone)
                return True
        return False
