from __future__ import annotations

import random
from typing import ClassVar, Any
from utils.roles import BaseRole, RoleContext, RoleCategory, role_registry, NightAction, PassiveEffect, WinCondition
from utils.constants import RoleFaction
from config import get_emoji


# --- Hisoka ---

class HisokaWinCondition(WinCondition):
    def __init__(self) -> None:
        super().__init__("Survive until the end of the game, and successfully use all abilities (Bungee Gum, Texture Surprise, Bloodlust) at least once.")

    def check(self, alive_factions: frozenset[str], context: RoleContext) -> bool:
        session = context.payload.get("session")
        if not session:
            return False
        player_state = session.players.get(context.user_id)
        if not player_state or not player_state.alive:
            return False
        
        # Must have used all three abilities
        used_bungee = player_state.metadata.get("bungee_gum_used", False)
        used_texture = player_state.metadata.get("texture_surprise_used", False)
        used_bloodlust = player_state.metadata.get("bloodlust_used", False)
        
        return used_bungee and used_texture and used_bloodlust


class HisokaBungee(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Bungee Gum",
            description="Bind two living players together. If either wins while both are alive, the other wins too.",
            priority=4
        )
        self.num_targets = 2

    async def execute(self, context: RoleContext) -> None:
        session = context.payload.get("session")
        if not session:
            return
            
        target1 = context.target_id
        target2 = context.payload.get("controlled_vote_target")
        if not target1 or not target2:
            return

        # Set the bond
        session.metadata["bungee_gum_bond"] = (target1, target2)
        
        # Mark ability as used
        hisoka_state = session.players.get(context.user_id)
        if hisoka_state:
            hisoka_state.metadata["bungee_gum_used"] = True

        # Send DMs to both linked players in the background
        import asyncio
        async def notify_bond(s=session, h_id=context.user_id, t1=target1, t2=target2):
            if context.bot:
                guild = context.bot.get_guild(s.game_handle.guild_id)
                if guild:
                    m1 = guild.get_member(t1)
                    m2 = guild.get_member(t2)
                    t1_name = m1.display_name if m1 else f"User {t1}"
                    t2_name = m2.display_name if m2 else f"User {t2}"
                    
                    msg1 = f"{get_emoji('web')} **Bound by Bungee Gum!**\nYou have been bound to **{t2_name}** (<@{t2}>) by Bungee Gum. If either of you fulfills their win condition while both are still alive, you both win!"
                    msg2 = f"{get_emoji('web')} **Bound by Bungee Gum!**\nYou have been bound to **{t1_name}** (<@{t1}>) by Bungee Gum. If either of you fulfills their win condition while both are still alive, you both win!"
                    
                    if m1:
                        try:
                            context.bot.message_queue.send(m1, msg1)
                        except Exception:
                            pass
                    if m2:
                        try:
                            context.bot.message_queue.send(m2, msg2)
                        except Exception:
                            pass
        asyncio.create_task(notify_bond())
        context.payload["log"] = f"Hisoka bound <@{target1}> and <@{target2}> with Bungee Gum."


class HisokaTextureSurprise(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Texture Surprise",
            description="Disguise a player's faction and category to alignment/category investigations until morning.",
            priority=3
        )

    def can_use(self, session: Any, player_state: Any) -> tuple[bool, str | None]:
        uses = player_state.metadata.setdefault("texture_surprise_uses", 2)
        if uses <= 0:
            return False, "Texture Surprise has no uses left."
        return True, None

    async def execute(self, context: RoleContext) -> None:
        session = context.payload.get("session")
        if not session or not context.target_id:
            return

        player_state = session.players.get(context.user_id)
        if player_state:
            uses = player_state.metadata.get("texture_surprise_uses", 2)
            player_state.metadata["texture_surprise_uses"] = max(0, uses - 1)
            player_state.metadata["texture_surprise_used"] = True

        target_player = session.players.get(context.target_id)
        if target_player:
            if target_player.role_key == "ayanokoji_kiyotaka":
                context.payload["log"] = "Hisoka attempted to disguise Ayanokoji, but Ayanokoji's Unreadable passive resisted it."
                return
            disg_faction = context.payload.get("disguised_faction", "Hero")
            disg_category = context.payload.get("disguised_category", "neutral")
            target_player.metadata["disguised_faction"] = disg_faction
            target_player.metadata["disguised_category"] = disg_category

        context.payload["log"] = f"Hisoka disguised <@{context.target_id}> using Texture Surprise."


class HisokaBloodlust(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Bloodlust",
            description="Challenge a player. Any active ability they target Hisoka with tonight is turned back onto themselves.",
            priority=1
        )

    def can_use(self, session: Any, player_state: Any) -> tuple[bool, str | None]:
        uses = player_state.metadata.setdefault("bloodlust_uses", 1)
        if uses <= 0:
            return False, "Bloodlust has already been used."
        return True, None

    async def execute(self, context: RoleContext) -> None:
        session = context.payload.get("session")
        if not session or not context.target_id:
            return

        player_state = session.players.get(context.user_id)
        if player_state:
            uses = player_state.metadata.get("bloodlust_uses", 1)
            player_state.metadata["bloodlust_uses"] = max(0, uses - 1)
            player_state.metadata["bloodlust_used"] = True

        challenges = session.metadata.setdefault("bloodlust_challenges", {})
        challenges[context.target_id] = context.user_id
        context.payload["log"] = f"Hisoka challenged <@{context.target_id}> with Bloodlust."


@role_registry.register
class Hisoka(BaseRole):
    role_key: ClassVar[str] = "hisoka"
    priority: ClassVar[int] = 4
    tags: ClassVar[tuple[str, ...]] = (RoleCategory.NEUTRAL, "chaos")
    continues_game_after_win: ClassVar[bool] = True
    cooldown_text: ClassVar[str] = "None"
    limitations_text: ClassVar[str] = "Texture Surprise has 2 uses, Bloodlust has 1 use."

    def __init__(self) -> None:
        super().__init__()
        self.abilities = [HisokaBungee(), HisokaTextureSurprise(), HisokaBloodlust()]
        self.win_condition_obj = HisokaWinCondition()

    async def get_night_feedback(self, context: RoleContext) -> str | None:
        target_id = context.payload.get("target_id")
        action_idx = context.payload.get("action_index", 0)
        
        if action_idx == 0:
            target2 = context.payload.get("controlled_vote_target")
            if target_id and target2:
                return f"{get_emoji('hisoka')} **Bungee Gum:** Linked <@{target_id}> and <@{target2}> successfully!"
        elif action_idx == 1:
            if target_id:
                disg_faction = context.payload.get("disguised_faction", "Hero")
                disg_category = context.payload.get("disguised_category", "neutral")
                return f"{get_emoji('hisoka')} **Texture Surprise:** Successfully disguised <@{target_id}> as Faction: **{disg_faction}** and Category: **{disg_category}** tonight!"
        elif action_idx == 2:
            if target_id:
                return f"{get_emoji('hisoka')} **Bloodlust:** Successfully challenged <@{target_id}>! Any active ability they target you with tonight will redirect back onto themselves."
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






# --- Eren Jaeger ---

class ErenWinCondition(WinCondition):
    def __init__(self) -> None:
        super().__init__("Survive until Night 5 to trigger The Rumbling, then kill everyone until you are the last one standing.")

    def check(self, alive_factions: frozenset[str], context: RoleContext) -> bool:
        session = context.payload.get("session")
        if not session:
            return False
        player_state = session.players.get(context.user_id)
        if not player_state:
            return False
            
        current_night = session.metadata.get("night_num", 1)
        if current_night >= 6:
            alive_players = [pid for pid, pstate in session.players.items() if pstate.alive]
            if len(alive_players) == 1 and alive_players[0] == context.user_id:
                player_state.metadata["rumbling_win"] = True
                return True
        return False


class ErenRumble(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Founding Vision / The Rumbling",
            description="Founding Vision: Learn player faction. The Rumbling (Night 6+): Crush and kill a target.",
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
        if current_night >= 6:
            kills = session.metadata.setdefault("pending_kills", {})
            kills[target_id] = kills.get(target_id, []) + ["rumbling"]
            context.payload["log"] = f"Eren Jaeger's Rumbling crushed <@{target_id}>!"
            return

        # Normal Founding Vision: check side
        target_player = session.players.get(target_id)
        if target_player:
            faction = target_player.metadata.get("disguised_faction", target_player.faction)
            context.payload["result"] = f"Founding Vision: <@{target_id}> belongs to **{faction}**."


@role_registry.register
class ErenJaeger(BaseRole):
    role_key: ClassVar[str] = "eren_jaeger"
    priority: ClassVar[int] = 4
    tags: ClassVar[tuple[str, ...]] = (RoleCategory.NEUTRAL, "apocalypse")
    is_hostile_neutral: ClassVar[bool] = True
    cooldown_text: ClassVar[str] = "None"
    limitations_text: ClassVar[str] = "The Rumbling kills are only active Night 6 onwards."

    def __init__(self) -> None:
        super().__init__()
        self.abilities = [ErenRumble()]
        self.win_condition_obj = ErenWinCondition()

    def is_active_threat(self, session: Any, player_state: Any) -> bool:
        return player_state.alive and session.metadata.get("night_num", 1) >= 6


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


class LelouchGeass(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Geass",
            description="Choose a player tonight. All votes towards them tomorrow (both nomination and voting phases) will count double. Cooldown: 1 Night.",
            priority=5
        )

    def can_use(self, session: Any, player_state: Any) -> tuple[bool, str | None]:
        last_used = player_state.metadata.get("geass_last_used", -1)
        current_night = session.metadata.get("night_num", 1)
        if last_used == current_night - 1:
            return False, "Geass is on cooldown tonight."
        return True, None

    def get_eligible_targets(self, session: Any, actor_id: int) -> list[int]:
        return [pid for pid, pstate in session.players.items() if pstate.alive and pid != actor_id]

    async def execute(self, context: RoleContext) -> None:
        target_id = context.target_id
        session = context.payload.get("session")
        if not target_id or not session:
            return

        player_state = session.players[context.user_id]
        player_state.metadata["geass_last_used"] = session.metadata.get("night_num", 1)

        session.metadata["geass_target"] = target_id
        context.payload["result"] = f"{get_emoji('lelouch')} **Geass:** You have commanded <@{target_id}>. All votes towards them tomorrow will be doubled."


@role_registry.register
class LelouchLamperouge(BaseRole):
    role_key: ClassVar[str] = "lelouch"
    priority: ClassVar[int] = 5
    tags: ClassVar[tuple[str, ...]] = (RoleCategory.UTILITY,)
    cooldown_text: ClassVar[str] = "Geass: 1 Night, Black Knight: Once per game"
    limitations_text: ClassVar[str] = "None"

    def __init__(self) -> None:
        super().__init__()
        self.abilities = [LelouchGeass()]

    def win_condition_met(self, alive_factions: frozenset[str], context: RoleContext) -> bool:
        session = context.payload.get("session")
        if not session:
            return False

        # Win Condition 1: All Protagonists (Heroes) are dead
        alive_heroes = [pid for pid, pstate in session.players.items() if pstate.alive and pstate.faction == RoleFaction.HERO.value]
        if not alive_heroes:
            return True

        # Win Condition 2: Lelouch was lynched (Zero Requiem)
        player_state = session.players.get(context.user_id)
        if player_state and player_state.metadata.get("lelouch_lynched"):
            return True

        return False

    async def get_night_feedback(self, context: RoleContext) -> str | None:
        return context.payload.get("result")
