from __future__ import annotations

import random
from typing import ClassVar, Any
from utils.roles import BaseRole, RoleContext, RoleCategory, role_registry, NightAction, PassiveEffect
from utils.constants import RoleFaction
from config import get_emoji


class AntagonistBaseKill(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Kill",
            description="Eliminate a target player at night for the Antagonist faction.",
            priority=14
        )

    def get_eligible_targets(self, session: Any, actor_id: int) -> list[int]:
        targets = super().get_eligible_targets(session, actor_id)
        return [
            pid for pid in targets
            if pid != actor_id and session.players[pid].faction != RoleFaction.VILLAIN.value
        ]

    async def execute(self, context: RoleContext) -> None:
        target_id = context.target_id
        session = context.payload.get("session")
        if not target_id or not session:
            return

        kills = session.metadata.setdefault("pending_kills", {})
        kills[target_id] = kills.get(target_id, []) + ["mafia_strike"]
        context.payload["log"] = f"Antagonist attacked <@{target_id}>."
        context.payload["result"] = f"{get_emoji('antagonist_base_killer')} **Antagonist Attack:** You targeted <@{target_id}> tonight."


@role_registry.register
class AntagonistBaseKiller(BaseRole):
    role_key: ClassVar[str] = "antagonist_base_killer"
    priority: ClassVar[int] = 14
    tags: ClassVar[tuple[str, ...]] = (RoleCategory.KILLING,)
    is_unique: ClassVar[bool] = False
    cooldown_text: ClassVar[str] = "None"
    limitations_text: ClassVar[str] = "Cannot target Mafia teammates."

    def __init__(self) -> None:
        super().__init__()
        self.abilities = [AntagonistBaseKill()]

    def is_active_threat(self, session: Any, player_state: Any) -> bool:
        return player_state.alive


class BlackbeardDarknessLogia(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Darkness Logia",
            description="Roleblock a player. Cooldown: 1 Night.",
            priority=1
        )

    def can_use(self, session: Any, player_state: Any) -> tuple[bool, str | None]:
        last_used_night = player_state.metadata.get("last_block_night", -1)
        current_night = session.metadata.get("night_num", 1)
        if last_used_night == current_night - 1:
            return False, "Darkness Logia is on cooldown tonight."
        return True, None

    def get_eligible_targets(self, session: Any, actor_id: int) -> list[int]:
        return [pid for pid in super().get_eligible_targets(session, actor_id) if pid != actor_id]

    async def execute(self, context: RoleContext) -> None:
        target_id = context.target_id
        session = context.payload.get("session")
        if not target_id or not session:
            return

        player_state = session.players[context.user_id]
        current_night = session.metadata.get("night_num", 1)
        player_state.metadata["last_block_night"] = current_night

        target_player = session.players.get(target_id)
        if target_player:
            target_player.metadata["roleblocked"] = True
            context.payload["log"] = f"Blackbeard roleblocked <@{target_id}> using Darkness Logia."


class BlackbeardTremorFruit(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Tremor Fruit",
            description="Roleblock all non-mafia players for one night. (Once per game)",
            priority=1
        )
        self.num_targets = 0

    def can_use(self, session: Any, player_state: Any) -> tuple[bool, str | None]:
        if player_state.metadata.get("tremor_used"):
            return False, "Tremor Fruit has already been used this game."
        return True, None

    async def execute(self, context: RoleContext) -> None:
        session = context.payload.get("session")
        if not session:
            return

        player_state = session.players[context.user_id]
        player_state.metadata["tremor_used"] = True

        blocked_count = 0
        for pid, pstate in session.players.items():
            if pstate.alive and pstate.faction != RoleFaction.VILLAIN.value:
                pstate.metadata["roleblocked"] = True
                blocked_count += 1

        context.payload["action_type"] = "tremor"
        context.payload["log"] = f"Blackbeard triggered the Tremor Fruit! An earthquake roleblocked {blocked_count} players."

        # Queue aura embed for day transition (after death report, before alive/dead list)
        from utils.helpers import queue_aura
        from config import get_event_image
        queue_aura(
            session,
            title=f"{get_emoji('blackbeard')} ZEHAHAHAHA! THE EARTHQUAKE IS SHAKING THE LOBBY!",
            description=(
                f"**\"From now on, this is my era!\"**\n\n"
                f"Blackbeard has unleashed the Tremor Fruit power! "
                f"The ground trembles violently, disrupting **{blocked_count}** players' actions tonight..."
            ),
            image_url=get_event_image("blackbeard_tremor"),
        )


@role_registry.register
class Blackbeard(BaseRole):
    role_key: ClassVar[str] = "blackbeard"
    priority: ClassVar[int] = 1
    tags: ClassVar[tuple[str, ...]] = (RoleCategory.CONTROL,)
    cooldown_text: ClassVar[str] = "1 night cooldown (Darkness Logia)"
    limitations_text: ClassVar[str] = "Tremor Fruit is once per game."

    def __init__(self) -> None:
        super().__init__()
        self.abilities = [BlackbeardDarknessLogia(), BlackbeardTremorFruit()]

    async def get_night_feedback(self, context: RoleContext) -> str | None:
        target_id = context.payload.get("target_id")
        action_type = context.payload.get("action_type")
        if action_type == "tremor":
            return f"{get_emoji('blackbeard')} **You triggered the Tremor Fruit earthquake! All non-mafia players have been roleblocked.**"
        elif target_id:
            return f"{get_emoji('blackbeard')} **Your Darkness Logia roleblock successfully distracted <@{target_id}>!**"
        return None


class LightYagamiKill(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Death Note / Devil's Pen",
            description="Death Note: Guess target's role; if correct, they are eliminated. Devil's Pen: Targeted player dies unpreventably after 3 nights.",
            priority=15
        )

    async def execute(self, context: RoleContext) -> None:
        session = context.payload.get("session")
        if not session:
            return
            
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

        # 2. Death Note Guess
        target_id = context.target_id
        guessed_role = context.payload.get("guessed_role")
        if not target_id or not guessed_role:
            context.payload["error"] = "Must select a target and guess their role."
            return

        target_player = session.players.get(target_id)
        if not target_player:
            return

        if target_player.role_key == guessed_role:
            kills = session.metadata.setdefault("pending_kills", {})
            kills[target_id] = kills.get(target_id, []) + ["light_guess"]
            context.payload["log"] = f"Light Yagami guessed the role of <@{target_id}> correctly!"
        else:
            context.payload["log"] = f"Light Yagami guessed <@{target_id}>'s role incorrectly as '{guessed_role}'."
            # Wrong guess — publicly expose Light Yagami and his target
            mafia_ch_id = session.metadata.get("mafia_channel_id")
            if mafia_ch_id and context.bot:
                ch = context.bot.get_channel(mafia_ch_id)
                if ch:
                    guild = ch.guild
                    ly_member = guild.get_member(context.user_id) if guild else None
                    target_member = guild.get_member(target_id) if guild else None
                    ly_name = ly_member.display_name if ly_member else f"User {context.user_id}"
                    target_name = target_member.display_name if target_member else f"User {target_id}"

                    from roles import ROLES_METADATA
                    guessed_display = ROLES_METADATA.get(guessed_role, {}).get("name", guessed_role)

                    from ui import build_v2_layout
                    kira_view = build_v2_layout(
                        title=f"{get_emoji('light_yagami')} Kira Has Been Exposed!",
                        description=(
                            f"**{ly_name}** (<@{context.user_id}>) wrote **{target_name}**'s (<@{target_id}>) name "
                            f"in the Death Note, guessing they were **{guessed_display}**.\n\n"
                            f"{get_emoji('cross')} **The guess was wrong.** The Death Note is powerless and now everyone knows who Kira is."
                        ),
                        color=discord.Color.red(),
                        footer_text="The pen may lie, but the truth never stays hidden.",
                    )
                    await context.bot.message_queue.send(ch, view=kira_view)



@role_registry.register
class LightYagami(BaseRole):
    role_key: ClassVar[str] = "light_yagami"
    priority: ClassVar[int] = 15
    tags: ClassVar[tuple[str, ...]] = (RoleCategory.UTILITY,)
    cooldown_text: ClassVar[str] = "3 nights cooldown (Devil's Pen)"
    limitations_text: ClassVar[str] = "Death Note guess only kills on correct guesses."

    def __init__(self) -> None:
        super().__init__()
        self.abilities = [LightYagamiKill()]

    async def get_night_feedback(self, context: RoleContext) -> str | None:
        target_id = context.payload.get("target_id")
        action_type = context.payload.get("action_type")
        if not target_id:
            return None
            
        if action_type == "devils_pen":
            return f"{get_emoji('light_yagami')} **You wrote <@{target_id}>'s name in the Death Note with the Devil's Pen. They will die in 3 nights.**"
        else:
            guessed_role = context.payload.get("guessed_role")
            session = context.payload.get("session")
            if session:
                target_player = session.players.get(target_id)
                if target_player and target_player.role_key == guessed_role:
                    return f"{get_emoji('light_yagami')} **Kira's judgment! Your guess of <@{target_id}> as '{guessed_role}' was correct. They have been eliminated.**"
                else:
                    return f"{get_emoji('light_yagami')} **Your guess of <@{target_id}> as '{guessed_role}' was incorrect. No elimination took place.**"
        return None


class MuzanInfect(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Blood Demon Art",
            description="Transform a Town player into a Demon (85% basic Demon, 10% Lower Moon, 5% Upper Moon). (Twice per game)",
            priority=16
        )

    def can_use(self, session: Any, player_state: Any) -> tuple[bool, str | None]:
        uses_left = player_state.metadata.get("muzan_uses_left", 2)
        if uses_left <= 0:
            return False, "You have already used Blood Demon Art twice this game."
        return True, None

    async def execute(self, context: RoleContext) -> None:
        session = context.payload.get("session")
        if not session:
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

        player_state = session.players[context.user_id]
        uses_left = player_state.metadata.get("muzan_uses_left", 2)
        player_state.metadata["muzan_uses_left"] = max(0, uses_left - 1)

        # Transform logic
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
        remaining = player_state.metadata["muzan_uses_left"]
        context.payload["log"] = f"Muzan Kibutsuji infected <@{target_id}>, transforming them into a **{new_role_name}**! ({remaining} uses left)"


class MuzanRegen(PassiveEffect):
    def __init__(self) -> None:
        super().__init__(
            name="Instant Regeneration",
            description="Survive first night attack."
        )

    async def resolve_protection(self, context: RoleContext, attack_sources: list[str]) -> bool:
        session = context.payload.get("session")
        if not session:
            return False
            
        player_state = session.players.get(context.user_id)
        if player_state and player_state.metadata.get("muzan_regen", True):
            player_state.metadata["muzan_regen"] = False

            # Queue the notification DM (Component V2 embed)
            import discord
            from ui import build_v2_layout
            guild = context.bot.get_guild(session.game_handle.guild_id) if (context.bot and session.game_handle) else None
            if guild:
                muzan_member = guild.get_member(context.user_id)
                if muzan_member:
                    regen_layout = build_v2_layout(
                        title=f"{get_emoji('shield')} Instant Regeneration Triggered!",
                        description="You blocked an attack. Your passive is now **disabled**.",
                        color=discord.Color.dark_red(),
                    )
                    context.bot.message_queue.send(muzan_member, view=regen_layout)
            return True
        return False


@role_registry.register
class MuzanKibutsuji(BaseRole):
    role_key: ClassVar[str] = "muzan_kibutsuji"
    priority: ClassVar[int] = 16
    tags: ClassVar[tuple[str, ...]] = (RoleCategory.DECEPTION,)
    cooldown_text: ClassVar[str] = "None (Twice per game total)"
    limitations_text: ClassVar[str] = "Can only infect living Town (Hero) faction players. 2 uses total."

    def __init__(self) -> None:
        super().__init__()
        self.abilities = [MuzanInfect()]
        self.passives = [MuzanRegen()]

    def can_act_tonight(self, session: Any, player_state: Any) -> tuple[bool, str | None]:
        uses_left = player_state.metadata.get("muzan_uses_left", 2)
        if uses_left <= 0:
            return False, "You have already used Blood Demon Art twice this game."
        return True, None

    async def get_night_feedback(self, context: RoleContext) -> str | None:
        target_id = context.payload.get("target_id")
        if not target_id:
            return None
        session = context.payload.get("session")
        if session:
            target_player = session.players.get(target_id)
            if target_player and target_player.faction == RoleFaction.VILLAIN.value:
                from roles import ROLES_METADATA
                role_meta = ROLES_METADATA.get(target_player.role_key or "", {})
                role_display = role_meta.get("name", "Demon")
                return f"{get_emoji('muzan_kibutsuji')} **Your Blood Demon Art successfully infected <@{target_id}>! They are now a {role_display} on your side.**"
            else:
                return f"{get_emoji('muzan_kibutsuji')} **Your Blood Demon Art failed to infect <@{target_id}>.**"
        return None


class MakimaControl(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Control",
            description="Control a player, redirecting their night action to a target of your choice. You cannot target friendly mafia, or the same player on consecutive nights.",
            priority=5
        )
        self.num_targets = 2

    def can_use(self, session: Any, player_state: Any) -> tuple[bool, str | None]:
        return True, None

    def get_eligible_targets(self, session: Any, actor_id: int) -> list[int]:
        return [pid for pid in super().get_eligible_targets(session, actor_id) if pid != actor_id]

    async def execute(self, context: RoleContext) -> None:
        # Resolves before priority list in game_engine.py _resolve_night_logic.
        # This execute method acts as a backup logger.
        pass


class MakimaBang(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Bang.",
            description="Fire an invisible force that deals an Unstoppable Attack to a player. Once per game.",
            priority=2
        )
        self.num_targets = 1

    def can_use(self, session: Any, player_state: Any) -> tuple[bool, str | None]:
        if player_state.metadata.get("bang_used"):
            return False, "Bang has already been used this game."
            
        contract_activated = player_state.metadata.get("pm_contract_activated", False)
        controlled_count = player_state.metadata.get("controlled_count", 0)
        
        if not contract_activated or controlled_count < 2:
            reasons = []
            if not contract_activated:
                reasons.append("Prime Minister's Contract has not activated")
            if controlled_count < 2:
                reasons.append(f"Successfully controlled only {controlled_count}/2 different players")
            return False, f"Bang is sealed. Conditions not met: {', '.join(reasons)}."
            
        return True, None

    async def execute(self, context: RoleContext) -> None:
        target_id = context.target_id
        session = context.payload.get("session")
        if not target_id or not session:
            return

        player_state = session.players[context.user_id]
        player_state.metadata["bang_used"] = True

        # Queue unstoppable attack
        kills = session.metadata.setdefault("pending_kills", {})
        kills[target_id] = kills.get(target_id, []) + ["bang_kill"]
        context.payload["action_type"] = "bang"
        context.payload["log"] = f"Makima used Bang. on <@{target_id}>!"


@role_registry.register
class Makima(BaseRole):
    role_key: ClassVar[str] = "makima"
    priority: ClassVar[int] = 2
    tags: ClassVar[tuple[str, ...]] = (RoleCategory.CONTROL,)
    cooldown_text: ClassVar[str] = "Control: None. Bang: Once per game (requires conditions)."
    limitations_text: ClassVar[str] = "Control fails if target doesn't actively visit. Cannot control consecutive nights."

    def __init__(self) -> None:
        super().__init__()
        self.abilities = [MakimaControl(), MakimaBang()]

    async def get_night_feedback(self, context: RoleContext) -> str | None:
        # Check if Bang was used
        action_type = context.payload.get("action_type")
        if action_type == "bang" or context.payload.get("action_index") == 1:
            target_id = context.payload.get("target_id")
            return f"{get_emoji('makima')} **Bang. dealt an Unstoppable Attack to <@{target_id}>.**"
            
        # Control feedback
        target_id = context.payload.get("target_id")
        redirect_target = context.payload.get("redirect_target")
        success = context.payload.get("control_success", False)
        error = context.payload.get("error")
        
        if success and target_id and redirect_target:
            return f"{get_emoji('makima')} **Your Control succeeded! <@{target_id}> was redirected to <@{redirect_target}>.**"
        elif error:
            return f"{get_emoji('makima')} **Your Control failed.** Reason: {error}"
        return None




@role_registry.register
class Demon(BaseRole):
    role_key: ClassVar[str] = "demon"
    priority: ClassVar[int] = 99
    cooldown_text: ClassVar[str] = "None"
    limitations_text: ClassVar[str] = "No active night abilities."

    def __init__(self) -> None:
        super().__init__()


class LowerMoonDistract(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Distract",
            description="Roleblock a player.",
            priority=1
        )

    async def execute(self, context: RoleContext) -> None:
        target_id = context.target_id
        if not target_id:
            return
            
        session = context.payload.get("session")
        if not session:
            return
            
        target_player = session.players.get(target_id)
        if target_player:
            target_player.metadata["roleblocked"] = True
            context.payload["log"] = f"Lower Moon Demon distracted <@{target_id}>."


@role_registry.register
class LowerMoon(BaseRole):
    role_key: ClassVar[str] = "lower_moon"
    priority: ClassVar[int] = 1
    tags: ClassVar[tuple[str, ...]] = (RoleCategory.CONTROL,)
    cooldown_text: ClassVar[str] = "None"
    limitations_text: ClassVar[str] = "Cannot target Mafia teammates."

    def __init__(self) -> None:
        super().__init__()
        self.abilities = [LowerMoonDistract()]


class UpperMoonStrike(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Demon Strike",
            description="Kill a player.",
            priority=14
        )

    async def execute(self, context: RoleContext) -> None:
        target_id = context.target_id
        if not target_id:
            return
            
        session = context.payload.get("session")
        if not session:
            return
            
        kills = session.metadata.setdefault("pending_kills", {})
        kills[target_id] = kills.get(target_id, []) + ["demon_strike"]
        context.payload["log"] = f"Upper Moon Demon attacked <@{target_id}>."


@role_registry.register
class UpperMoon(BaseRole):
    role_key: ClassVar[str] = "upper_moon"
    priority: ClassVar[int] = 14
    tags: ClassVar[tuple[str, ...]] = (RoleCategory.KILLING,)
    cooldown_text: ClassVar[str] = "None"
    limitations_text: ClassVar[str] = "Cannot target Mafia teammates."

    def __init__(self) -> None:
        super().__init__()
        self.abilities = [UpperMoonStrike()]


class FriezaDeathBeam(NightAction):
    def __init__(self) -> None:
        super().__init__(
            name="Death Beam",
            description="Every night, choose a player to eliminate.",
            priority=14
        )

    async def execute(self, context: RoleContext) -> None:
        target_id = context.target_id
        if not target_id:
            return
            
        session = context.payload.get("session")
        if not session:
            return
            
        kills = session.metadata.setdefault("pending_kills", {})
        kills[target_id] = kills.get(target_id, []) + ["frieza_kill"]
        context.payload["log"] = f"Frieza fired a Death Beam at <@{target_id}>."
        context.payload["result"] = f"{get_emoji('frieza')} **Death Beam Fired!** You targeted <@{target_id}> with your Death Beam tonight."


@role_registry.register
class Frieza(BaseRole):
    role_key: ClassVar[str] = "frieza"
    priority: ClassVar[int] = 14
    tags: ClassVar[tuple[str, ...]] = (RoleCategory.KILLING,)
    is_unique: ClassVar[bool] = False
    cooldown_text: ClassVar[str] = "None"
    limitations_text: ClassVar[str] = "Cannot target Mafia teammates."

    def __init__(self) -> None:
        super().__init__()
        self.abilities = [FriezaDeathBeam()]

    def is_active_threat(self, session: Any, player_state: Any) -> bool:
        return player_state.alive
