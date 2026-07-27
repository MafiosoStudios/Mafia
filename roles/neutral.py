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
            priority=17
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

        # Send DM embeds to both linked players in the background
        import asyncio
        async def notify_bond(s=session, h_id=context.user_id, t1=target1, t2=target2):
            if context.bot:
                guild = context.bot.get_guild(s.game_handle.guild_id)
                if guild:
                    m1 = guild.get_member(t1)
                    m2 = guild.get_member(t2)
                    t1_name = m1.display_name if m1 else f"User {t1}"
                    t2_name = m2.display_name if m2 else f"User {t2}"
                    
                    import discord
                    from ui import build_v2_layout

                    view1 = build_v2_layout(
                        title=f"{get_emoji('hisoka')} Bound by Bungee Gum!",
                        description=(
                            f"You have been bound to **{t2_name}** (<@{t2}>) by Hisoka's **Bungee Gum**!\n\n"
                            f"🤝 **Shared Destiny:**\n"
                            f"If either of you fulfills your win condition while both of you are still alive, **you both win!**"
                        ),
                        color=discord.Color.magenta(),
                        footer_text="Bound by Bungee Gum",
                    )
                    view2 = build_v2_layout(
                        title=f"{get_emoji('hisoka')} Bound by Bungee Gum!",
                        description=(
                            f"You have been bound to **{t1_name}** (<@{t1}>) by Hisoka's **Bungee Gum**!\n\n"
                            f"🤝 **Shared Destiny:**\n"
                            f"If either of you fulfills your win condition while both of you are still alive, **you both win!**"
                        ),
                        color=discord.Color.magenta(),
                        footer_text="Bound by Bungee Gum",
                    )
                    
                    if m1:
                        try:
                            context.bot.message_queue.send(m1, view=view1)
                        except Exception:
                            pass
                    if m2:
                        try:
                            context.bot.message_queue.send(m2, view=view2)
                        except Exception:
                            pass
        asyncio.create_task(notify_bond())
        context.payload["log"] = f"Hisoka bound <@{target1}> and <@{target2}> with Bungee Gum."


class HisokaTextureSurprise(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Texture Surprise",
            description="Disguise a player's faction and category to alignment/category investigations until morning.",
            priority=17
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
            priority=17
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
    priority: ClassVar[int] = 17
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
            priority=19
        )

    def get_eligible_targets(self, session: Any, actor_id: int) -> list[int]:
        return [pid for pid in session.players.keys() if pid != actor_id]

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
    priority: ClassVar[int] = 19
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
            priority=18
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
    priority: ClassVar[int] = 18
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

# Factions that can be adapted to (internal string values)
_MAHORAGA_FACTIONS = (
    "Protagonist",   # Town / Hero
    "Antagonist",    # Mafia / Villain
    "Neutral",       # Neutral
)
# Adaptation success chances per stage (1st→2nd→3rd adaptation)
_ADAPT_CHANCES = [0.75, 0.50, 0.25]


class MahoragaWinCondition(WinCondition):
    def __init__(self) -> None:
        super().__init__("Be the last remaining player alive in the lobby.")

    def check(self, alive_factions: frozenset[str], context: RoleContext) -> bool:
        session = context.payload.get("session")
        if not session:
            return False
        player_state = session.players.get(context.user_id)
        if not player_state or not player_state.alive:
            return False
        # Win if Mahoraga is the only living player
        alive_players = [pid for pid, ps in session.players.items() if ps.alive]
        return len(alive_players) == 1 and alive_players[0] == context.user_id


class MahoragaAdaptation(NightAction):
    """
    Adaptation — Mahoraga's active night ability.
    Mahoraga visits a player each night to attempt adapting to their faction.
    Stages: 75% → 50% → 25% success per new faction.
    Once a faction is adapted to, their night-kill abilities are blocked.
    After all 3 factions are adapted, Mahoraga is also immune to being voted out.
    """

    def __init__(self) -> None:
        super().__init__(
            name="Adaptation",
            description=(
                "Visit a player to attempt adapting to their faction. "
                "1st faction: 75% success. 2nd: 50%. 3rd: 25%.\n"
                "Adapted factions cannot kill Mahoraga at night (only unstoppable/one-hit "
                "abilities bypass this). After adapting to all 3 factions, you also cannot "
                "be voted out by the town."
            ),
            priority=3,
        )

    def can_use(self, session: Any, player_state: Any) -> tuple[bool, str]:
        adapted: list = player_state.metadata.get("mahoraga_adapted_factions", [])
        if player_state.metadata.get("mahoraga_adapt_complete"):
            return False, "You have already adapted to all three factions. Adaptation is complete."
        return True, None

    def get_eligible_targets(self, session: Any, actor_id: int) -> list[int]:
        actor_state = session.players.get(actor_id)
        adapted: list = actor_state.metadata.get("mahoraga_adapted_factions", []) if actor_state else []
        # Only target players whose faction hasn't been adapted yet
        eligible = []
        for pid, pstate in session.players.items():
            if pid == actor_id or not pstate.alive:
                continue
            if pstate.faction not in adapted:
                eligible.append(pid)
        return eligible

    async def execute(self, context: RoleContext) -> None:
        target_id = context.target_id
        session = context.payload.get("session")
        if not target_id or not session:
            return

        player_state = session.players[context.user_id]
        target_state = session.players.get(target_id)
        if not target_state:
            return

        target_faction = target_state.faction
        adapted: list = player_state.metadata.setdefault("mahoraga_adapted_factions", [])

        # Determine which stage this adaptation is (0-indexed)
        stage = len(adapted)
        if stage >= 3:
            context.payload["result"] = f"🌀 **Adaptation Complete.** You have already adapted to all factions."
            return

        if target_faction in adapted:
            context.payload["result"] = (
                f"🌀 You have already adapted to the **{target_faction}** faction. "
                f"Choose a player from a different faction next night."
            )
            return

        chance = _ADAPT_CHANCES[stage]
        success = random.random() < chance

        faction_label_map = {
            "Protagonist": "Protagonist (Town)",
            "Antagonist": "Antagonist (Mafia)",
            "Neutral": "Neutral",
        }
        faction_label = faction_label_map.get(target_faction, target_faction)

        if success:
            adapted.append(target_faction)
            player_state.metadata["mahoraga_adapted_factions"] = adapted

            # Update the session-level immune factions list so the engine can read it quickly
            immune: list = session.metadata.setdefault("mahoraga_faction_immune", [])
            if target_faction not in immune:
                immune.append(target_faction)

            remaining_factions = [f for f in _MAHORAGA_FACTIONS if f not in adapted]

            if len(adapted) == 3:
                player_state.metadata["mahoraga_adapt_complete"] = True
                session.metadata["mahoraga_vote_immune"] = True
                context.payload["result"] = (
                    f"🌀 **Adaptation Successful!** You have now adapted to all three factions — "
                    f"**{faction_label}** was your final target.\n\n"
                    f"No faction can eliminate you through night abilities anymore, "
                    f"and **the town can no longer vote you out.** "
                    f"Only an unstoppable one-hit ability can end your reign."
                )
            else:
                next_stage_chance = int(_ADAPT_CHANCES[len(adapted)] * 100)
                context.payload["result"] = (
                    f"🌀 **Adaptation Successful!** You have adapted to the **{faction_label}** faction "
                    f"({int(chance * 100)}% chance).\n"
                    f"Their faction can no longer kill you through night abilities.\n\n"
                    f"Remaining factions to adapt: **{', '.join(faction_label_map.get(f, f) for f in remaining_factions)}**\n"
                    f"Next adaptation chance: **{next_stage_chance}%**"
                )
        else:
            context.payload["result"] = (
                f"🌀 **Adaptation Failed!** ({int(chance * 100)}% chance)\n"
                f"You attempted to adapt to the **{faction_label}** faction but failed. "
                f"Try again next night — you may target the same faction again."
            )


@role_registry.register
class Mahoraga(BaseRole):
    role_key: ClassVar[str] = "mahoraga"
    priority: ClassVar[int] = 99
    tags: ClassVar[tuple[str, ...]] = (RoleCategory.NEUTRAL, "survival")
    is_unique: ClassVar[bool] = False
    cooldown_text: ClassVar[str] = "None — Adaptation can be used every night until all 3 factions are adapted"
    limitations_text: ClassVar[str] = "Cannot target a faction already adapted to."

    def __init__(self) -> None:
        super().__init__()
        self.abilities = [MahoragaAdaptation()]
        self.passives = []
        self.win_condition_obj = MahoragaWinCondition()

    async def resolve_protection(self, context: RoleContext, attack_sources: list[str]) -> bool:
        """
        Block night kills from adapted factions.
        Unstoppable sources (light_guess, devils_pen_kill, bang_kill, frieza_golden_kill,
        tosen_kill, gates_of_babylon, kishibe_alert_kill) always bypass this.
        """
        session = context.payload.get("session")
        if not session:
            return False

        player_state = session.players.get(context.user_id)
        if not player_state:
            return False

        immune_factions: list = session.metadata.get("mahoraga_faction_immune", [])
        if not immune_factions:
            return False

        # These sources always bypass Mahoraga's adaptation immunity
        UNSTOPPABLE = {
            "light_guess", "devils_pen_kill", "bang_kill", "frieza_golden_kill",
            "tosen_kill", "gates_of_babylon", "kishibe_alert_kill",
        }
        # If any unstoppable source is present → don't block
        if any(src in UNSTOPPABLE for src in attack_sources):
            return False

        # Map attack sources back to their originating faction
        # Sources from known faction attackers
        VILLAIN_SOURCES = {"mafia_strike", "frieza_kill", "demon_strike", "upper_moon"}
        HERO_SOURCES = {"levi_kill"}
        NEUTRAL_SOURCES = {"eren_attack", "muzan_kill", "gilgamesh_attack"}

        faction_of_source: dict[str, str] = {}
        for src in attack_sources:
            if src in VILLAIN_SOURCES:
                faction_of_source[src] = "Antagonist"
            elif src in HERO_SOURCES:
                faction_of_source[src] = "Protagonist"
            elif src in NEUTRAL_SOURCES:
                faction_of_source[src] = "Neutral"
            else:
                # For generic sources, try to trace back via night_actions
                for pid, action in session.night_actions.items():
                    t_id = action.get("target_id")
                    targets = action.get("targets", ())
                    if t_id == context.user_id or context.user_id in targets:
                        pstate = session.players.get(pid)
                        if pstate:
                            faction_of_source[src] = pstate.faction
                            break

        # Block only if ALL attack sources come from adapted (immune) factions
        if not faction_of_source:
            return False

        all_immune = all(
            faction_of_source.get(src, "") in immune_factions
            for src in attack_sources
        )

        if all_immune:
            # Notify Mahoraga
            if context.bot:
                guild = context.bot.get_guild(session.game_handle.guild_id)
                if guild:
                    mahoraga_mem = guild.get_member(context.user_id)
                    if mahoraga_mem:
                        attacker_factions = set(faction_of_source.values())
                        context.bot.message_queue.send(
                            mahoraga_mem,
                            f"🌀 **Mahoraga — Adaptation Shield!**\n"
                            f"An attack from the **{', '.join(attacker_factions)}** faction was nullified "
                            f"by your adaptation. They cannot harm you."
                        )
            return True

        return False


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
    priority: ClassVar[int] = 99
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
