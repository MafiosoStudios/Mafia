from __future__ import annotations

import random
from typing import ClassVar, Any
from utils.roles import BaseRole, RoleContext, RoleCategory, role_registry
from utils.constants import RoleFaction

@role_registry.register
class Blackbeard(BaseRole):
    role_key: ClassVar[str] = "blackbeard"
    priority: ClassVar[int] = 1  # Runs first to apply roleblock
    tags: ClassVar[tuple[str, ...]] = (RoleCategory.CONTROL,)

    async def night_action(self, context: RoleContext) -> None:
        session = context.payload.get("session")
        player_state = session.players[context.user_id]
        
        # Check for Tremor Fruit (Max Ability)
        action_type = context.payload.get("action_type")
        if action_type == "tremor":
            if player_state.metadata.get("tremor_used"):
                context.payload["error"] = "You have already used the Tremor Fruit."
                return
            player_state.metadata["tremor_used"] = True
            
            # Roleblock all non-mafia (town and neutral)
            blocked_count = 0
            for pid, pstate in session.players.items():
                if pstate.alive and pstate.faction != RoleFaction.VILLAIN.value:
                    pstate.metadata["roleblocked"] = True
                    blocked_count += 1
            
            context.payload["log"] = f"Blackbeard triggered the Tremor Fruit! An earthquake roleblocked {blocked_count} players."
            return

        # Normal Darkness Logia roleblock
        target_id = context.target_id
        if not target_id:
            return

        # Cooldown check
        last_used_night = player_state.metadata.get("last_block_night", -1)
        current_night = session.metadata.get("night_num", 1)
        if last_used_night == current_night - 1:
            context.payload["error"] = "Darkness Logia is on cooldown."
            return

        player_state.metadata["last_block_night"] = current_night
        target_player = session.players.get(target_id)
        if target_player:
            target_player.metadata["roleblocked"] = True
            context.payload["log"] = f"Blackbeard roleblocked <@{target_id}>."

    def win_condition_met(self, alive_factions: frozenset[str], context: RoleContext) -> bool:
        return RoleFaction.VILLAIN.value in alive_factions


@role_registry.register
class LightYagami(BaseRole):
    role_key: ClassVar[str] = "light_yagami"
    priority: ClassVar[int] = 4
    tags: ClassVar[tuple[str, ...]] = (RoleCategory.KILLING,)

    async def night_action(self, context: RoleContext) -> None:
        session = context.payload.get("session")
        player_state = session.players[context.user_id]
        action_type = context.payload.get("action_type")

        # 1. Devil's Pen (Max Ability)
        if action_type == "devils_pen":
            target_id = context.target_id
            if not target_id:
                return

            last_used_night = player_state.metadata.get("last_pen_night", -10)
            current_night = session.metadata.get("night_num", 1)
            if current_night - last_used_night < 3:
                context.payload["error"] = f"Devil's Pen is on cooldown (needs {3 - (current_night - last_used_night)} more nights)."
                return

            player_state.metadata["last_pen_night"] = current_night
            
            # Queue unpreventable death on 3rd night
            death_queue = session.metadata.setdefault("devils_pen_deaths", {})
            death_queue[str(target_id)] = current_night + 3
            
            context.payload["log"] = f"Light Yagami wrote <@{target_id}>'s name in the Death Note. They will die in 3 nights."
            return

        # 2. Death Note (Ritualist Role Guess)
        target_id = context.target_id
        guessed_role = context.payload.get("guessed_role")
        if not target_id or not guessed_role:
            context.payload["error"] = "Must select a target and guess their role."
            return

        target_player = session.players.get(target_id)
        if not target_player:
            return

        if target_player.role_key == guessed_role:
            # Correct guess: target dies
            kills = session.metadata.setdefault("pending_kills", {})
            kills[target_id] = kills.get(target_id, []) + ["light_guess"]
            context.payload["log"] = f"Light Yagami guessed the role of <@{target_id}> correctly!"
        else:
            context.payload["log"] = f"Light Yagami guessed <@{target_id}>'s role incorrectly as '{guessed_role}'."

    def win_condition_met(self, alive_factions: frozenset[str], context: RoleContext) -> bool:
        return RoleFaction.VILLAIN.value in alive_factions


@role_registry.register
class MuzanKibutsuji(BaseRole):
    role_key: ClassVar[str] = "muzan_kibutsuji"
    priority: ClassVar[int] = 4
    tags: ClassVar[tuple[str, ...]] = (RoleCategory.DECEPTION,)

    async def night_action(self, context: RoleContext) -> None:
        session = context.payload.get("session")
        player_state = session.players[context.user_id]
        
        # Initialize regeneration passive
        if "muzan_regen" not in player_state.metadata:
            player_state.metadata["muzan_regen"] = True

        current_night = session.metadata.get("night_num", 1)
        if current_night < 3 or current_night % 3 != 0:
            context.payload["error"] = "Blood Demon Art can only be used starting from Night 3, every 3 nights."
            return

        target_id = context.target_id
        if not target_id:
            return

        target_player = session.players.get(target_id)
        if not target_player or not target_player.alive:
            return

        if target_player.faction != RoleFaction.HERO.value:
            context.payload["error"] = "You can only transform town members into demons."
            return

        # 85% basic demon, 10% lower moon, 5% upper moon
        rand = random.random()
        if rand < 0.85:
            target_player.role_key = "demon"
            new_role_name = "Demon"
        elif rand < 0.95:
            target_player.role_key = "lower_moon"
            new_role_name = "Lower Moon Demon"
        else:
            target_player.role_key = "upper_moon"
            new_role_name = "Upper Moon Demon"

        target_player.faction = RoleFaction.VILLAIN.value
        context.payload["log"] = f"Muzan Kibutsuji infected <@{target_id}>, transforming them into a **{new_role_name}**!"

    def win_condition_met(self, alive_factions: frozenset[str], context: RoleContext) -> bool:
        return RoleFaction.VILLAIN.value in alive_factions


@role_registry.register
class Makima(BaseRole):
    role_key: ClassVar[str] = "makima"
    priority: ClassVar[int] = 5
    tags: ClassVar[tuple[str, ...]] = (RoleCategory.CONTROL,)

    async def night_action(self, context: RoleContext) -> None:
        session = context.payload.get("session")
        player_state = session.players[context.user_id]
        
        current_night = session.metadata.get("night_num", 1)
        if current_night % 2 != 0:
            context.payload["error"] = "Control Devil can only be used every 2nd night (Night 2, 4, etc.)."
            return

        controls_left = player_state.metadata.setdefault("controls_left", 2)
        if controls_left <= 0:
            context.payload["error"] = "No control charges left."
            return

        # Target 1 (to be controlled) and Target 2 (whom they will vote for)
        target1 = context.target_id
        target2 = context.payload.get("controlled_vote_target")
        if not target1 or not target2:
            context.payload["error"] = "Must select two players."
            return

        player_state.metadata["controls_left"] = controls_left - 1
        
        # Store vote redirection for the next day
        redirections = session.metadata.setdefault("vote_redirections", {})
        redirections[target1] = target2
        
        context.payload["log"] = f"Makima controlled <@{target1}> to vote for <@{target2}> next day."

    def win_condition_met(self, alive_factions: frozenset[str], context: RoleContext) -> bool:
        return RoleFaction.VILLAIN.value in alive_factions


@role_registry.register
class Orochimaru(BaseRole):
    role_key: ClassVar[str] = "orochimaru"
    priority: ClassVar[int] = 2  # Runs early to execute reanimated abilities
    tags: ClassVar[tuple[str, ...]] = (RoleCategory.UTILITY,)

    async def night_action(self, context: RoleContext) -> None:
        session = context.payload.get("session")
        player_state = session.players[context.user_id]
        
        target_id = context.target_id  # Dead player to reanimate
        if not target_id:
            return

        # Verify target is dead
        target_player = session.players.get(target_id)
        if not target_player or target_player.alive:
            context.payload["error"] = "Cannot reanimate a living player."
            return

        used_reanimations = player_state.metadata.setdefault("reanimated_dead_ids", [])
        if target_id in used_reanimations:
            context.payload["error"] = "You have already reanimated this player."
            return

        used_reanimations.append(target_id)

        # Get target's role class
        dead_role_key = target_player.role_key
        if not dead_role_key:
            return
        
        dead_role_cls = role_registry.get(dead_role_key)
        if not dead_role_cls:
            return

        # Pick random target from all living players excluding Orochimaru and fellow mafias
        eligible_targets = [
            pid for pid, pstate in session.players.items()
            if pstate.alive and pstate.user_id != context.user_id and pstate.faction != RoleFaction.VILLAIN.value
        ]
        if not eligible_targets:
            context.payload["log"] = f"Orochimaru reanimated <@{target_id}> but no eligible targets were found."
            return

        random_target = random.choice(eligible_targets)
        
        # Instantiate dead role context and run its night action
        new_ctx = RoleContext(
            game_id=context.game_id,
            guild_id=context.guild_id,
            user_id=context.user_id,
            target_id=random_target,
            payload=context.payload
        )
        
        dead_role_inst = dead_role_cls()
        await dead_role_inst.night_action(new_ctx)
        
        context.payload["log"] = f"Orochimaru reanimated <@{target_id}> to use their ability on <@{random_target}>!"

    def win_condition_met(self, alive_factions: frozenset[str], context: RoleContext) -> bool:
        return RoleFaction.VILLAIN.value in alive_factions


# Muzan's Demon Minion roles logic:
@role_registry.register
class Demon(BaseRole):
    role_key: ClassVar[str] = "demon"
    priority: ClassVar[int] = 5

    def win_condition_met(self, alive_factions: frozenset[str], context: RoleContext) -> bool:
        return RoleFaction.VILLAIN.value in alive_factions


@role_registry.register
class LowerMoon(BaseRole):
    role_key: ClassVar[str] = "lower_moon"
    priority: ClassVar[int] = 1  # Roleblock is priority 1
    tags: ClassVar[tuple[str, ...]] = (RoleCategory.CONTROL,)

    async def night_action(self, context: RoleContext) -> None:
        target_id = context.target_id
        if not target_id:
            return
        session = context.payload.get("session")
        target_player = session.players.get(target_id)
        if target_player:
            target_player.metadata["roleblocked"] = True
            context.payload["log"] = f"Lower Moon Demon distracted <@{target_id}>."

    def win_condition_met(self, alive_factions: frozenset[str], context: RoleContext) -> bool:
        return RoleFaction.VILLAIN.value in alive_factions


@role_registry.register
class UpperMoon(BaseRole):
    role_key: ClassVar[str] = "upper_moon"
    priority: ClassVar[int] = 4  # Kill is priority 4
    tags: ClassVar[tuple[str, ...]] = (RoleCategory.KILLING,)

    async def night_action(self, context: RoleContext) -> None:
        target_id = context.target_id
        if not target_id:
            return
        session = context.payload.get("session")
        kills = session.metadata.setdefault("pending_kills", {})
        kills[target_id] = kills.get(target_id, []) + ["demon_strike"]
        context.payload["log"] = f"Upper Moon Demon attacked <@{target_id}>."

    def win_condition_met(self, alive_factions: frozenset[str], context: RoleContext) -> bool:
        return RoleFaction.VILLAIN.value in alive_factions


@role_registry.register
class DefaultVillain(BaseRole):
    role_key: ClassVar[str] = "default_villain"
    priority: ClassVar[int] = 4  # Kill is priority 4
    tags: ClassVar[tuple[str, ...]] = (RoleCategory.KILLING,)
    is_unique: ClassVar[bool] = False

    async def night_action(self, context: RoleContext) -> None:
        target_id = context.target_id
        if not target_id:
            return
        session = context.payload.get("session")
        kills = session.metadata.setdefault("pending_kills", {})
        kills[target_id] = kills.get(target_id, []) + ["mafia_strike"]
        context.payload["log"] = f"Default Villain attacked <@{target_id}>."

    def win_condition_met(self, alive_factions: frozenset[str], context: RoleContext) -> bool:
        return RoleFaction.VILLAIN.value in alive_factions

