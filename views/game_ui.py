from __future__ import annotations

import discord
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from game_engine import GameSession, GameEngine

import asyncio
import logging
from config import get_emoji
from utils.constants import GamePhase, RoleFaction
from ui.base import MafiosoLayoutView
from ui.theme import heading, small_footer
from ui import build_v2_layout

logger = logging.getLogger(__name__)



async def _safe_respond_or_edit(
    interaction: discord.Interaction,
    *,
    view: Any = None,
    description: str = "",
    ephemeral: bool = True,
) -> None:
    """Safely sends a new ephemeral followup response so original interaction menus remain intact."""
    layout = build_v2_layout(description=description, view=view, footer_text="")
    if interaction.response.is_done():
        try:
            await interaction.followup.send(view=layout, ephemeral=ephemeral)
        except Exception:
            try:
                await interaction.edit_original_response(view=layout)
            except Exception as e:
                logger.debug("Failed to send response: %s", e)
    else:
        try:
            await interaction.response.send_message(view=layout, ephemeral=ephemeral)
        except Exception:
            try:
                await interaction.followup.send(view=layout, ephemeral=ephemeral)
            except Exception as e:
                logger.debug("Failed to send response: %s", e)


async def _safe_queue_night_action(
    interaction: discord.Interaction,
    engine: "GameEngine",
    game_id: str,
    user_id: int,
    payload: dict[str, Any],
) -> bool:
    """Submits a night action, gracefully handling the case where the night
    phase already ended or parameters are invalid. Returns True on success."""
    if not interaction.response.is_done():
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            pass
    try:
        await engine.queue_night_action(game_id, user_id, payload)
        return True
    except RuntimeError:
        await _safe_respond_or_edit(
            interaction,
            description=f"{get_emoji('cross')} Night actions have already locked in — your action wasn't submitted.",
        )
        return False
    except ValueError as val_err:
        await _safe_respond_or_edit(
            interaction,
            description=f"{get_emoji('cross')} **Invalid Action:** {val_err}",
        )
        return False
    except Exception as exc:
        logger.exception("Unexpected error in night action queue")
        await _safe_respond_or_edit(
            interaction,
            description=f"{get_emoji('cross')} An unexpected error occurred: {exc}",
        )
        return False



class StartGameView(MafiosoLayoutView):
    """Shown to the host after setup. Clicking 'Start Game' creates the channel and begins the match."""

    def __init__(self, game_id: str, engine: GameEngine) -> None:
        super().__init__(timeout=300)  # 5 minutes to click
        self.game_id = game_id
        self.engine = engine
        self.children[0].label = "Start Game"

    @discord.ui.button(label="Start Game", style=discord.ButtonStyle.success, custom_id="mafia_start_game_button")
    async def start_game(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.response.is_done():
            try:
                await interaction.response.defer()
            except Exception:
                pass

        session = await self.engine.get_session(self.game_id)
        if not session:
            await interaction.followup.send("This game is no longer active.", ephemeral=True)
            return

        # Only the host (or an admin) can start the game
        host_id = session.game_handle.host_id
        is_admin = interaction.user.guild_permissions.administrator if isinstance(interaction.user, discord.Member) else False
        if interaction.user.id != host_id and not is_admin:
            await interaction.followup.send("Only the match host or an admin can start the game!", ephemeral=True)
            return

        # Disable the button immediately
        button.disabled = True
        button.label = "Game Starting..."

        container = discord.ui.Container(accent_color=discord.Color.blurple())
        emoji_lobby = get_emoji('lobby')
        container.add_item(discord.ui.TextDisplay(f"{heading(f'{emoji_lobby} Game Starting!')}\nCreating the game channel and initializing the match..."))
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(small_footer("Anime Mafia")))

        start_view = MafiosoLayoutView(timeout=300)
        start_view.add_item(container)

        try:
            await interaction.edit_original_response(view=start_view)
        except Exception:
            pass

        # Launch the game loop as a background task with tracking
        self.engine._track_task(f"game_loop_{self.game_id}", self.engine.run_game_loop(self.game_id))



class SpectateView(MafiosoLayoutView):
    """Shown in the lobby channel when a game begins, allowing non-players to spectate the match channel."""

    def __init__(self, game_id: str, engine: GameEngine) -> None:
        super().__init__(timeout=None)
        self.game_id = game_id
        self.engine = engine

    @discord.ui.button(label="Spectate", style=discord.ButtonStyle.blurple, custom_id="spectate_button")
    async def spectate(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except Exception:
                pass

        session = await self.engine.get_session(self.game_id)
        if not session:
            await interaction.followup.send(f"{get_emoji('cross')} This game is no longer active.", ephemeral=True)
            return

        if interaction.user.id in session.player_ids:
            await interaction.followup.send(f"{get_emoji('cross')} You are a player in this game! You cannot spectate.", ephemeral=True)
            return

        mafia_ch_id = session.metadata.get("mafia_channel_id")
        if not mafia_ch_id:
            await interaction.followup.send(f"{get_emoji('cross')} Match channel not found.", ephemeral=True)
            return

        guild = interaction.guild
        if guild:
            ch = guild.get_channel(mafia_ch_id)
            if ch:
                await ch.set_permissions(interaction.user, read_messages=True, send_messages=False)
                await interaction.followup.send(f"{get_emoji('check')} You are now spectating! Check out <#{mafia_ch_id}>.", ephemeral=True)
                return

        await interaction.followup.send(f"{get_emoji('cross')} Failed to add spectator permissions.", ephemeral=True)


class NightActionView(MafiosoLayoutView):
    def __init__(self, game_id: str, engine: GameEngine) -> None:
        super().__init__(timeout=None)
        self.game_id = game_id
        self.engine = engine


    @discord.ui.button(label="Choose Night Action", style=discord.ButtonStyle.primary, custom_id="mafia_choose_night_action")
    async def choose_action(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except Exception:
                pass

        session = await self.engine.get_session(self.game_id)
        if not session:
            await interaction.followup.send("This game is no longer active.", ephemeral=True)
            return

        user_id = interaction.user.id
        if user_id not in session.players:
            await interaction.followup.send("You are not part of this game lobby.", ephemeral=True)
            return

        player = session.players[user_id]
        if not player.alive:
            await interaction.followup.send("Dead players cannot perform night actions.", ephemeral=True)
            return

        # Check Wounded status
        if player.metadata.get("wounded_until_night") == session.metadata.get("night_num", 1):
            await interaction.followup.send("You are Wounded and cannot act tonight!", ephemeral=True)
            return

        # Check Exhausted status
        if player.metadata.get("exhausted_until_night") == session.metadata.get("night_num", 1):
            await interaction.followup.send("You are Exhausted and cannot act tonight!", ephemeral=True)
            return

        if player.metadata.get("roleblocked"):
            await interaction.followup.send("You feel disoriented... You have been roleblocked and cannot act tonight!", ephemeral=True)
            return

        if player.metadata.get("detained"):
            await interaction.followup.send("🌑 You are detained inside Tōsen's Bankai and cannot act tonight.", ephemeral=True)
            return

        role_key = player.role_key
        if not role_key:
            await interaction.followup.send("You do not have a role assigned.", ephemeral=True)
            return

        # Special check for roles that can't act
        if role_key in ["villager", "demon", "mahoraga"]:
            await interaction.followup.send("You do not have an active night ability.", ephemeral=True)
            return

        # Instantiate role to retrieve abilities
        from utils.roles import role_registry, NightAction
        role_cls = role_registry.get(role_key) if role_registry.contains(role_key) else None
        if not role_cls:
            await interaction.followup.send("Your role is not registered.", ephemeral=True)
            return

        role_inst = role_cls()
        if player.metadata.get("is_converted_antagonist_killer"):
            from roles.mafia import AntagonistBaseKill
            role_inst.abilities = [AntagonistBaseKill()]
            role_inst.passives = []

        active_abilities = [a for a in role_inst.abilities if isinstance(a, NightAction)]
        if not active_abilities:
            await interaction.followup.send("You do not have an active night ability.", ephemeral=True)
            return

        # Handle legacy role-specific custom views (e.g. Light Yagami)
        if role_key == "light_yagami" and not player.metadata.get("is_converted_antagonist_killer"):
            living_targets = [pid for pid, pstate in session.players.items() if pstate.alive and pstate.faction != "Villain"]
            options = []
            guild = interaction.guild
            for pid in living_targets:
                member = guild.get_member(pid) if guild else None
                name = member.display_name if member else f"User {pid}"
                options.append(discord.SelectOption(label=name, value=str(pid)))

            view = discord.ui.View(timeout=120)
            select_type = LightYagamiActionSelect(self.game_id, self.engine, options)
            view.add_item(select_type)
            
            cancel_btn = discord.ui.Button(label="Cancel Action", style=discord.ButtonStyle.danger)
            async def ly_cancel_callback(inter: discord.Interaction) -> None:
                if not inter.response.is_done():
                    try:
                        await inter.response.defer(ephemeral=True)
                    except Exception:
                        pass
                async with self.engine._lock:
                    if inter.user.id in session.night_actions:
                        session.night_actions.pop(inter.user.id, None)
                        player.night_actions_used = max(0, player.night_actions_used - 1)
                        await _safe_respond_or_edit(inter, description=f"{get_emoji('check')} **Your night action has been cancelled.**")
                        self.engine.request_night_status_update(self.game_id)
                        return
                await inter.followup.send(view=build_v2_layout(description=f"{get_emoji('cross')} You have not submitted any night actions yet tonight.", footer_text=""), ephemeral=True)
            cancel_btn.callback = ly_cancel_callback
            view.add_item(cancel_btn)
            
            await interaction.followup.send(view=build_v2_layout(description="Select which ability you wish to use:", view=view, footer_text=""), ephemeral=True)
            return

        # Otherwise, present the dynamic separate buttons view for the role's abilities!
        view = NightAbilityButtonsView(self.game_id, self.engine, user_id, role_inst, session)
        await interaction.followup.send(view=build_v2_layout(description="Select an ability to use tonight:", view=view, footer_text=""), ephemeral=True)



class TwoTargetSelectStep1(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, ability: Any, action_index: int, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Select first target...", options=options[:25])
        self.game_id = game_id
        self.engine = engine
        self.ability = ability
        self.action_index = action_index
        self.action_idx = action_index
        self.target_options = options

    async def callback(self, interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except Exception:
                pass
        first_target = int(self.values[0])
        self.first_target = first_target

        options2 = [opt for opt in self.target_options if opt.value not in (str(first_target), str(interaction.user.id))]
        if not options2:
            await _safe_respond_or_edit(interaction, description=f"{get_emoji('cross')} No eligible secondary target available.")
            return

        view = discord.ui.View(timeout=120)
        select2 = TwoTargetSelectStep2(self.game_id, self.engine, self.ability, self.action_index, first_target, options2)
        view.add_item(select2)

        if self.ability.name == "Control":
            prompt = f"Using **{self.ability.name}**.\nSelect the target to redirect <@{first_target}>'s action onto:"
        else:
            prompt = f"Using **{self.ability.name}**.\nSelect the second target to pair with <@{first_target}>:"

        await _safe_respond_or_edit(interaction, view=view, description=prompt)


class TwoTargetSelectStep2(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, ability: Any, action_index: int, first_target: int, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Select second target...", options=options[:25])
        self.game_id = game_id
        self.engine = engine
        self.ability = ability
        self.action_index = action_index
        self.action_idx = action_index
        self.first_target = first_target

    async def callback(self, interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except Exception:
                pass
        second_target = int(self.values[0])
        payload = {
            "action_index": self.action_idx,
            "target_id": self.first_target,
            "targets": [self.first_target, second_target],
            "redirect_target": second_target,
        }
        if not await _safe_queue_night_action(interaction, self.engine, self.game_id, interaction.user.id, payload):
            return

        if self.ability.name == "Control":
            desc = f"You have decided to **Control** <@{self.first_target}> and redirect their action onto <@{second_target}>."
        else:
            desc = f"Ability **{self.ability.name}** registered targeting <@{self.first_target}> and <@{second_target}>."
        await _safe_respond_or_edit(interaction, description=desc)



class NightAbilityButtonsView(MafiosoLayoutView):
    def __init__(self, game_id: str, engine: GameEngine, player_id: int, role_inst: Any, session: GameSession) -> None:
        super().__init__(timeout=120)
        self.game_id = game_id
        self.engine = engine
        self.player_id = player_id
        self.role_inst = role_inst
        self.session = session

        from utils.roles import NightAction
        for idx, ability in enumerate(role_inst.abilities):
            if isinstance(ability, NightAction):
                btn = discord.ui.Button(
                    label=ability.name,
                    style=discord.ButtonStyle.primary,
                    custom_id=f"mafia_ability_{player_id}_{idx}_{ability.name.lower().replace(' ', '_')}"
                )
                btn.callback = self.make_callback(ability, idx)
                self.add_item(btn)

        # Cancel Action button
        cancel_btn = discord.ui.Button(
            label="Cancel Action",
            style=discord.ButtonStyle.danger,
            custom_id=f"mafia_ability_cancel_{player_id}"
        )
        cancel_btn.callback = self.cancel_action_callback
        self.add_item(cancel_btn)

    def make_callback(self, ability: Any, idx: int):
        async def callback(interaction: discord.Interaction) -> None:
            if not interaction.response.is_done():
                try:
                    await interaction.response.defer(ephemeral=True)
                except Exception:
                    pass

            session = await self.engine.get_session(self.game_id)
            if not session:
                await interaction.followup.send("This game is no longer active.", ephemeral=True)
                return

            player_state = session.players.get(self.player_id)
            if not player_state or not player_state.alive:
                await interaction.followup.send("You cannot perform night actions.", ephemeral=True)
                return

            if player_state.metadata.get("roleblocked"):
                await interaction.followup.send("You are roleblocked and cannot act tonight!", ephemeral=True)
                return

            if player_state.metadata.get("detained"):
                await interaction.followup.send("🌑 You are detained inside Tōsen's Bankai and cannot act tonight.", ephemeral=True)
                return

            # Check if wounded/exhausted
            night_num = session.metadata.get("night_num", 1)
            if player_state.metadata.get("wounded_until_night") == night_num or player_state.metadata.get("exhausted_until_night") == night_num:
                await interaction.followup.send("You cannot use abilities tonight.", ephemeral=True)
                return

            # Check if this role or ability can be used yet
            can_act, act_reason = self.role_inst.can_act_tonight(session, player_state)
            if not can_act:
                await interaction.followup.send(f"{get_emoji('cross')} **You cannot act tonight.**\nReason: {act_reason or 'Not available.'}", ephemeral=True)
                return

            can_use, reason = ability.can_use(session, player_state)
            if not can_use:
                # If they have someone selected, remove/clear that selection!
                removed = False
                async with self.engine._lock:
                    if self.player_id in session.night_actions:
                        session.night_actions.pop(self.player_id, None)
                        player_state.night_actions_used = max(0, player_state.night_actions_used - 1)
                        removed = True
                
                msg = f"{get_emoji('cross')} **You cannot use {ability.name} yet.**\nReason: {reason or 'Not available.'}"
                if removed:
                    msg += f"\n{get_emoji('warning')} **Your previously registered night action target has been cleared.**"
                    self.engine.request_night_status_update(self.game_id)
                await interaction.followup.send(msg, ephemeral=True)
                return

            # Retrieve eligible targets
            targets = ability.get_eligible_targets(session, self.player_id)
            
            # Teammate validation for Villain faction (Mafia)
            if player_state.faction == "Villain" and self.role_inst.role_key in ["blackbeard", "light_yagami", "muzan_kibutsuji", "makima", "upper_moon"]:
                targets = [t for t in targets if session.players[t].faction != "Villain"]

            if ability.num_targets > 0 and not targets:
                await interaction.followup.send("No eligible targets for this ability.", ephemeral=True)
                return

            # If 0 targets (like Levi's Precision Strike)
            if ability.num_targets == 0:
                if self.role_inst.role_key == "levi_ackerman" and ability.name == "Precision Strike":
                    player_state.metadata["levi_precision_active"] = True
                    odm_ability = self.role_inst.abilities[0]
                    odm_targets = odm_ability.get_eligible_targets(session, self.player_id)
                    options = []
                    guild = interaction.guild
                    for pid in odm_targets:
                        member = guild.get_member(pid) if guild else None
                        name = member.display_name if member else f"User {pid}"
                        options.append(discord.SelectOption(label=name, value=str(pid)))

                    if not options:
                        await _safe_respond_or_edit(interaction, description="No eligible targets for ODM Execution.")
                        return

                    view = discord.ui.View(timeout=120)
                    select = AbilityTargetSelect(self.game_id, self.engine, odm_ability, 0, options)
                    view.add_item(select)

                    back_btn = discord.ui.Button(label="Cancel / Go Back", style=discord.ButtonStyle.danger)
                    async def back_callback(inter: discord.Interaction) -> None:
                        if not inter.response.is_done():
                            try:
                                await inter.response.defer(ephemeral=True)
                            except Exception:
                                pass
                        player_state.metadata["levi_precision_active"] = False
                        orig_view = NightAbilityButtonsView(self.game_id, self.engine, self.player_id, self.role_inst, session)
                        await _safe_respond_or_edit(inter, view=orig_view, description="Select an ability to use tonight:")
                    back_btn.callback = back_callback
                    view.add_item(back_btn)

                    await _safe_respond_or_edit(
                        interaction,
                        view=view,
                        description=f"{get_emoji('sword')} **Precision Strike Activated!** (Bypasses Protections)\nNow select your target for **ODM Execution**:"
                    )
                    return
                else:
                    payload = {
                        "action_index": idx,
                        "target_id": None
                    }
                    if not await _safe_queue_night_action(interaction, self.engine, self.game_id, self.player_id, payload):
                        return
                    await _safe_respond_or_edit(interaction, description=f"Ability **{ability.name}** activated successfully.")
                    return



            # Build SelectOptions
            options = []
            guild = interaction.guild
            for pid in targets:
                # Self targeting check
                if pid == self.player_id and self.role_inst.role_key not in ("doctor_tenma",):
                    continue
                member = guild.get_member(pid) if guild else None
                name = member.display_name if member else f"User {pid}"
                p_st = session.players.get(pid)
                if p_st and not p_st.alive:
                    name += " (Dead 💀)"
                options.append(discord.SelectOption(label=name, value=str(pid)))

            if not options:
                await interaction.followup.send(view=build_v2_layout(description="No eligible targets for this ability.", footer_text=""), ephemeral=True)
                return

            view = discord.ui.View(timeout=120)
            if ability.name == "Texture Surprise":
                select = TextureSurpriseStep1(self.game_id, self.engine, ability, idx, options)
                view.add_item(select)
            elif ability.name == "Brew Potion":
                select = MaomaoBrewPotionStep1(self.game_id, self.engine, ability, idx, options)
                view.add_item(select)
            elif ability.name == "Demon Detection":
                select = FrierenDemonDetectionMultiSelect(self.game_id, self.engine, ability, idx, options)
                view.add_item(select)
            elif ability.num_targets == 2:
                select = TwoTargetSelectStep1(self.game_id, self.engine, ability, idx, options)
                view.add_item(select)
            else:
                select = AbilityTargetSelect(self.game_id, self.engine, ability, idx, options)
                view.add_item(select)

            # Go Back / Cancel button for target selection
            back_btn = discord.ui.Button(label="Cancel / Go Back", style=discord.ButtonStyle.danger)
            async def back_callback(inter: discord.Interaction) -> None:
                if not inter.response.is_done():
                    try:
                        await inter.response.defer(ephemeral=True)
                    except Exception:
                        pass
                orig_view = NightAbilityButtonsView(self.game_id, self.engine, self.player_id, self.role_inst, session)
                await _safe_respond_or_edit(inter, view=orig_view, description="Select an ability to use tonight:")
            back_btn.callback = back_callback
            view.add_item(back_btn)

            if ability.name == "Texture Surprise":
                desc = f"Using **{ability.name}**.\nSelect the player to disguise:"
            elif ability.name == "Brew Potion":
                desc = f"Using **{ability.name}**.\nSelect the potion you want to brew:"
            elif ability.name == "Demon Detection" or ability.num_targets == 2:
                desc = f"Using **{ability.name}**.\nSelect the first target:"
            else:
                desc = f"Using **{ability.name}**.\nSelect your target:"

            await _safe_respond_or_edit(interaction, view=view, description=desc)

        return callback

    async def cancel_action_callback(self, interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except Exception:
                pass

        session = await self.engine.get_session(self.game_id)
        if not session:
            await interaction.followup.send(view=build_v2_layout(description="This game is no longer active.", footer_text=""), ephemeral=True)
            return

        player_state = session.players.get(self.player_id)
        if not player_state:
            return

        async with self.engine._lock:
            if self.player_id in session.night_actions:
                session.night_actions.pop(self.player_id, None)
                player_state.night_actions_used = max(0, player_state.night_actions_used - 1)
                await _safe_respond_or_edit(
                    interaction,
                    description=f"{get_emoji('check')} **Your night action has been cancelled.**\nFeel free to select a new target at any time tonight.",
                )
                self.engine.request_night_status_update(self.game_id)
                return
        
        await interaction.followup.send(view=build_v2_layout(description=f"{get_emoji('cross')} You have not submitted any night actions yet tonight.", footer_text=""), ephemeral=True)



class AbilityTargetSelect(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, ability: Any, action_index: int, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Select a target...", options=options[:25])
        self.game_id = game_id
        self.engine = engine
        self.ability = ability
        self.action_index = action_index

    async def callback(self, interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except Exception:
                pass
        target_id = int(self.values[0])
        payload = {
            "action_index": self.action_index,
            "target_id": target_id
        }
        if not await _safe_queue_night_action(interaction, self.engine, self.game_id, interaction.user.id, payload):
            return
        await _safe_respond_or_edit(interaction, description=f"Ability **{self.ability.name}** registered on <@{target_id}>.")



class TextureSurpriseStep1(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, ability: Any, action_index: int, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Select a player to disguise...", options=options[:25])
        self.game_id = game_id
        self.engine = engine
        self.ability = ability
        self.action_index = action_index

    async def callback(self, interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except Exception:
                pass
        target_id = int(self.values[0])
        view = discord.ui.View(timeout=120)
        faction_options = [
            discord.SelectOption(label="Town (Protagonist)", value="Hero"),
            discord.SelectOption(label="Mafia (Antagonist)", value="Villain"),
            discord.SelectOption(label="Neutral", value="Neutral")
        ]
        select2 = TextureSurpriseStep2(self.game_id, self.engine, self.ability, self.action_index, target_id, faction_options)
        view.add_item(select2)
        
        back_btn = discord.ui.Button(label="Cancel / Go Back", style=discord.ButtonStyle.danger)
        async def back_callback(inter: discord.Interaction) -> None:
            if not inter.response.is_done():
                try:
                    await inter.response.defer(ephemeral=True)
                except Exception:
                    pass
            session = await self.engine.get_session(self.game_id)
            if session:
                from views.game_ui import NightAbilityButtonsView
                role_inst = session.players[interaction.user.id].role_inst
                orig_view = NightAbilityButtonsView(self.game_id, self.engine, interaction.user.id, role_inst, session)
                await _safe_respond_or_edit(inter, view=orig_view, description="Select an ability to use tonight:")

        back_btn.callback = back_callback
        view.add_item(back_btn)
        
        await _safe_respond_or_edit(interaction, view=view, description=f"Using **{self.ability.name}** on <@{target_id}>.\nChoose disguised Faction:")


class TextureSurpriseStep2(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, ability: Any, action_index: int, target_id: int, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Choose faction...", options=options)
        self.game_id = game_id
        self.engine = engine
        self.ability = ability
        self.action_index = action_index
        self.target_id = target_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except Exception:
                pass
        faction_choice = self.values[0]
        view = discord.ui.View(timeout=120)
        category_options = [
            discord.SelectOption(label="Protective", value="protective"),
            discord.SelectOption(label="Investigative", value="investigative"),
            discord.SelectOption(label="Council", value="council"),
            discord.SelectOption(label="Utility", value="utility"),
            discord.SelectOption(label="Killing", value="killing"),
            discord.SelectOption(label="Deception", value="deception"),
            discord.SelectOption(label="Control", value="control"),
            discord.SelectOption(label="Neutral", value="neutral")
        ]
        select3 = TextureSurpriseStep3(self.game_id, self.engine, self.ability, self.action_index, self.target_id, faction_choice, category_options)
        view.add_item(select3)
        
        back_btn = discord.ui.Button(label="Cancel / Go Back", style=discord.ButtonStyle.danger)
        async def back_callback(inter: discord.Interaction) -> None:
            if not inter.response.is_done():
                try:
                    await inter.response.defer(ephemeral=True)
                except Exception:
                    pass
            session = await self.engine.get_session(self.game_id)
            if session:
                from views.game_ui import NightAbilityButtonsView
                role_inst = session.players[interaction.user.id].role_inst
                orig_view = NightAbilityButtonsView(self.game_id, self.engine, interaction.user.id, role_inst, session)
                await _safe_respond_or_edit(inter, view=orig_view, description="Select an ability to use tonight:")
        back_btn.callback = back_callback
        view.add_item(back_btn)
        
        await _safe_respond_or_edit(interaction, view=view, description=f"Using **{self.ability.name}** on <@{self.target_id}>.\nChoose disguised Category:")


class TextureSurpriseStep3(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, ability: Any, action_index: int, target_id: int, faction_choice: str, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Choose category...", options=options)
        self.game_id = game_id
        self.engine = engine
        self.ability = ability
        self.action_index = action_index
        self.target_id = target_id
        self.faction_choice = faction_choice

    async def callback(self, interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except Exception:
                pass
        category_choice = self.values[0]
        payload = {
            "action_index": self.action_index,
            "target_id": self.target_id,
            "disguised_faction": self.faction_choice,
            "disguised_category": category_choice
        }
        if not await _safe_queue_night_action(interaction, self.engine, self.game_id, interaction.user.id, payload):
            return
        await _safe_respond_or_edit(interaction, description=f"You have decided to use **{self.ability.name}**. <@{self.target_id}> will appear as **{self.faction_choice}** and category **{category_choice}** tonight.")


class MaomaoBrewPotionStep1(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, ability: Any, action_index: int, target_options: list[discord.SelectOption]) -> None:
        potion_options = [
            discord.SelectOption(label="Potion of Truth (Faction)", value="truth", description="Reveals the target's faction"),
            discord.SelectOption(label="Potion of Invisibility (Untargetable)", value="invisibility", description="Makes target invisible tonight"),
            discord.SelectOption(label="Potion of Happiness (Roleblock)", value="happiness", description="Distracts (roleblocks) the target"),
            discord.SelectOption(label="Potion of Revitalization (Cooldown)", value="revitalization", description="Restores target's cooldowns"),
            discord.SelectOption(label="Potion of Intelligence (+1 Vote)", value="intelligence", description="Gains target +1 vote for tomorrow")
        ]
        super().__init__(placeholder="Select a potion to brew...", options=potion_options)
        self.game_id = game_id
        self.engine = engine
        self.ability = ability
        self.action_index = action_index
        self.target_options = target_options

    async def callback(self, interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except Exception:
                pass
        potion_choice = self.values[0]
        view = discord.ui.View(timeout=120)
        select2 = MaomaoBrewPotionStep2(self.game_id, self.engine, self.ability, self.action_index, potion_choice, self.target_options)
        view.add_item(select2)
        
        back_btn = discord.ui.Button(label="Cancel / Go Back", style=discord.ButtonStyle.danger)
        async def back_callback(inter: discord.Interaction) -> None:
            if not inter.response.is_done():
                try:
                    await inter.response.defer(ephemeral=True)
                except Exception:
                    pass
            session = await self.engine.get_session(self.game_id)
            if session:
                from views.game_ui import NightAbilityButtonsView
                role_inst = session.players[interaction.user.id].role_inst
                orig_view = NightAbilityButtonsView(self.game_id, self.engine, interaction.user.id, role_inst, session)
                await _safe_respond_or_edit(inter, view=orig_view, description="Select an ability to use tonight:")
        back_btn.callback = back_callback
        view.add_item(back_btn)
        
        potion_label = next(opt.label for opt in self.options if opt.value == potion_choice)
        await _safe_respond_or_edit(interaction, view=view, description=f"Brewing **{potion_label}**.\nSelect the player to use it on:")


class MaomaoBrewPotionStep2(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, ability: Any, action_index: int, potion_choice: str, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Select target player...", options=options[:25])
        self.game_id = game_id
        self.engine = engine
        self.ability = ability
        self.action_index = action_index
        self.potion_choice = potion_choice

    async def callback(self, interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except Exception:
                pass
        target_id = int(self.values[0])
        payload = {
            "action_index": self.action_index,
            "target_id": target_id,
            "potion_choice": self.potion_choice
        }
        if not await _safe_queue_night_action(interaction, self.engine, self.game_id, interaction.user.id, payload):
            return
        potion_names = {
            "truth": "Potion of Truth",
            "invisibility": "Potion of Invisibility",
            "happiness": "Potion of Happiness",
            "revitalization": "Potion of Revitalization",
            "intelligence": "Potion of Intelligence"
        }
        potion_name = potion_names.get(self.potion_choice, "Potion")
        await _safe_respond_or_edit(interaction, description=f"Successfully queued **{potion_name}** on <@{target_id}>.")


class FrierenDemonDetectionMultiSelect(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, ability: Any, action_index: int, options: list[discord.SelectOption]) -> None:
        min_vals = min(3, len(options))
        max_vals = min(3, len(options))
        super().__init__(
            placeholder="Select exactly 3 target players for Demon Detection...",
            min_values=min_vals,
            max_values=max_vals,
            options=options[:25],
        )
        self.game_id = game_id
        self.engine = engine
        self.ability = ability
        self.action_index = action_index

    async def callback(self, interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except Exception:
                pass
        if len(self.values) < 3:
            await _safe_respond_or_edit(interaction, description=f"{get_emoji('warning')} You must select 3 targets.")
            return
        t1, t2, t3 = int(self.values[0]), int(self.values[1]), int(self.values[2])
        payload = {
            "action_index": self.action_index,
            "target_id": t1,
            "targets": (t1, t2, t3)
        }
        if not await _safe_queue_night_action(interaction, self.engine, self.game_id, interaction.user.id, payload):
            return
        await _safe_respond_or_edit(interaction, description=f"✨ **Demon Detection** queued on <@{t1}>, <@{t2}>, and <@{t3}>.")


class StandardActionSelect(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Select a target...", options=options[:25])
        self.game_id = game_id
        self.engine = engine

    async def callback(self, interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except Exception:
                pass
        target_id = int(self.values[0])
        if not await _safe_queue_night_action(interaction, self.engine, self.game_id, interaction.user.id, {"target_id": target_id}):
            return
        await _safe_respond_or_edit(interaction, description=f"You have decided to use your ability on <@{target_id}>.")


class DoctorTenmaActionSelect(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, options: list[discord.SelectOption]) -> None:
        choices = [
            discord.SelectOption(label="Hand of Compassion (Heal)", value="heal"),
            discord.SelectOption(label="Scalpel of Justice (Revive Mafia)", value="revive")
        ]
        super().__init__(placeholder="Choose action type...", options=choices)
        self.game_id = game_id
        self.engine = engine
        self.target_options = options

    async def callback(self, interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except Exception:
                pass
        action_type = self.values[0]
        view = discord.ui.View(timeout=120)
        
        if action_type == "heal":
            select = TenmaHealSelect(self.game_id, self.engine, self.target_options)
            view.add_item(select)
            await _safe_respond_or_edit(interaction, view=view, description="Select a player to heal:")
        else:
            # For revive, must select a dead player
            session = await self.engine.get_session(self.game_id)
            dead_mafia_options = []
            guild = interaction.guild
            if session:
                for pid, pstate in session.players.items():
                    if not pstate.alive and pstate.faction == "Villain":
                        member = guild.get_member(pid) if guild else None
                        name = member.display_name if member else f"User {pid}"
                        dead_mafia_options.append(discord.SelectOption(label=name, value=str(pid)))

            if not dead_mafia_options:
                await _safe_respond_or_edit(interaction, description="There are no dead mafia members to revive.")
                return

            select = TenmaReviveSelect(self.game_id, self.engine, dead_mafia_options)
            view.add_item(select)
            await _safe_respond_or_edit(interaction, view=view, description="Select a dead mafia member to revive as a Default Villager:")


class TenmaHealSelect(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Select a player to heal...", options=options[:25])
        self.game_id = game_id
        self.engine = engine

    async def callback(self, interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except Exception:
                pass
        target_id = int(self.values[0])
        if not await _safe_queue_night_action(interaction, self.engine, self.game_id, interaction.user.id, {"target_id": target_id, "action_type": "heal"}):
            return
        await _safe_respond_or_edit(interaction, description=f"You have decided to heal <@{target_id}>.")


class TenmaReviveSelect(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Select a dead mafia member...", options=options[:25])
        self.game_id = game_id
        self.engine = engine

    async def callback(self, interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except Exception:
                pass
        target_id = int(self.values[0])
        if not await _safe_queue_night_action(interaction, self.engine, self.game_id, interaction.user.id, {"target_id": target_id, "action_type": "revive"}):
            return
        await _safe_respond_or_edit(interaction, description=f"You have decided to revive <@{target_id}>.")


class LightYagamiActionSelect(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, options: list[discord.SelectOption]) -> None:
        choices = [
            discord.SelectOption(label="Death Note (Guess Role)", value="guess"),
            discord.SelectOption(label="Devil's Pen (Kill in 3 nights)", value="pen")
        ]
        super().__init__(placeholder="Choose action type...", options=choices)
        self.game_id = game_id
        self.engine = engine
        self.target_options = options

    async def callback(self, interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except Exception:
                pass
        action_type = self.values[0]
        view = discord.ui.View(timeout=120)
        
        if action_type == "guess":
            select = LightYagamiTargetSelect(self.game_id, self.engine, self.target_options)
            view.add_item(select)
            await _safe_respond_or_edit(interaction, view=view, description="Select a player to guess their role:")
        else:
            select = LightYagamiPenSelect(self.game_id, self.engine, self.target_options)
            view.add_item(select)
            await _safe_respond_or_edit(interaction, view=view, description="Select a player to write in your notebook:")


class LightYagamiTargetSelect(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Select a player...", options=options[:25])
        self.game_id = game_id
        self.engine = engine

    async def callback(self, interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except Exception:
                pass
        target_id = int(self.values[0])
        # Now prompt for role guess
        import roles
        role_options = []
        for rkey, rmeta in roles.ROLES_METADATA.items():
            name = rmeta.get("name", rkey.replace("_", " ").title())
            role_options.append(discord.SelectOption(label=name, value=rkey))
        role_options = sorted(role_options, key=lambda opt: opt.label)[:25]
        
        view = discord.ui.View(timeout=120)
        select = LightYagamiRoleGuessSelect(self.game_id, self.engine, target_id, role_options)
        view.add_item(select)
        await interaction.followup.send(
            content=f"📓 **Death Note — Step 2:** Select the guessed role for <@{target_id}>:",
            view=view,
            ephemeral=True,
        )


class LightYagamiRoleGuessSelect(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, target_id: int, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Select guessed role...", options=options)
        self.game_id = game_id
        self.engine = engine
        self.target_id = target_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except Exception:
                pass
        guessed_role = self.values[0]
        payload = {
            "target_id": self.target_id,
            "action_type": "guess",
            "guessed_role": guessed_role
        }
        if not await _safe_queue_night_action(interaction, self.engine, self.game_id, interaction.user.id, payload):
            return
        await _safe_respond_or_edit(interaction, description=f"You have decided to use the Death Note on <@{self.target_id}> for role '{guessed_role}'.")


class LightYagamiPenSelect(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Select player to write down...", options=options[:25])
        self.game_id = game_id
        self.engine = engine

    async def callback(self, interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except Exception:
                pass
        target_id = int(self.values[0])
        payload = {
            "target_id": target_id,
            "action_type": "devils_pen"
        }
        if not await _safe_queue_night_action(interaction, self.engine, self.game_id, interaction.user.id, payload):
            return
        await _safe_respond_or_edit(interaction, description=f"You have decided to use Devil's Pen on <@{target_id}>.")


class MakimaSelect(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Select player to control...", options=options[:25])
        self.game_id = game_id
        self.engine = engine
        self.target_options = options

    async def callback(self, interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except Exception:
                pass
        target1 = int(self.values[0])
        session = await self.engine.get_session(self.game_id)
        if not session:
            return

        # Target 2 can be any living player except the controlled player
        options2 = []
        guild = interaction.guild
        for pid, pstate in session.players.items():
            if pstate.alive and pid != target1:
                member = guild.get_member(pid) if guild else None
                name = member.display_name if member else f"User {pid}"
                options2.append(discord.SelectOption(label=name, value=str(pid)))

        view = discord.ui.View(timeout=120)
        select2 = MakimaRedirectTargetSelect(self.game_id, self.engine, target1, options2)
        view.add_item(select2)
        await _safe_respond_or_edit(interaction, view=view, description=f"Select the target <@{target1}>'s action will be redirected to:")


class MakimaRedirectTargetSelect(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, target1: int, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Select redirection target...", options=options[:25])
        self.game_id = game_id
        self.engine = engine
        self.target1 = target1

    async def callback(self, interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except Exception:
                pass
        target2 = int(self.values[0])
        payload = {
            "target_id": self.target1,
            "redirect_target": target2,
            "action_index": 0
        }
        if not await _safe_queue_night_action(interaction, self.engine, self.game_id, interaction.user.id, payload):
            return
        await _safe_respond_or_edit(interaction, description=f"You have decided to control Devil: Redirecting <@{self.target1}> to target <@{target2}>.")


class HisokaBungeeSelect(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Select first target...", options=options[:25])
        self.game_id = game_id
        self.engine = engine
        self.target_options = options

    async def callback(self, interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except Exception:
                pass
        target1 = int(self.values[0])
        options2 = [opt for opt in self.target_options if opt.value != str(target1)]
        view = discord.ui.View(timeout=120)
        select2 = HisokaBungeeLinkSelect(self.game_id, self.engine, target1, options2)
        view.add_item(select2)
        await _safe_respond_or_edit(interaction, view=view, description=f"Select the second target to link with <@{target1}>:")


class HisokaBungeeLinkSelect(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, target1: int, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Select second target...", options=options[:25])
        self.game_id = game_id
        self.engine = engine
        self.target1 = target1

    async def callback(self, interaction: discord.Interaction) -> None:
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except Exception:
                pass
        target2 = int(self.values[0])
        payload = {
            "target_id": self.target1,
            "controlled_vote_target": target2
        }
        if not await _safe_queue_night_action(interaction, self.engine, self.game_id, interaction.user.id, payload):
            return
        await _safe_respond_or_edit(interaction, description=f"You have decided to link <@{self.target1}> with <@{target2}>.")


class VoteUISelectView(MafiosoLayoutView):
    def __init__(self, game_id: str, engine: GameEngine) -> None:
        super().__init__(timeout=None)

        self.game_id = game_id
        self.engine = engine

    @discord.ui.button(label="Cast Vote", style=discord.ButtonStyle.primary, custom_id="mafia_cast_vote_button")
    async def cast_vote(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async def _reply(target_inter: discord.Interaction, content: str = "", view: Any = None) -> None:
            if not target_inter.response.is_done():
                try:
                    await target_inter.response.send_message(content, view=view, ephemeral=True)
                except Exception:
                    await target_inter.followup.send(content, view=view, ephemeral=True)
            else:
                await target_inter.followup.send(content, view=view, ephemeral=True)

        session = await self.engine.get_session(self.game_id)
        if not session:
            await _reply(interaction, "This game is no longer active.")
            return

        user_id = interaction.user.id
        if user_id not in session.players:
            await _reply(interaction, "You are not part of this game.")
            return

        player = session.players[user_id]
        if not player.alive:
            await _reply(interaction, "Dead players cannot vote.")
            return

        day_num = session.metadata.get("day_num", 1)
        if player.metadata.get("wounded_until_day") == day_num:
            await _reply(interaction, "You are Wounded and cannot vote today.")
            return
        if player.metadata.get("exhausted_until_day") == day_num:
            await _reply(interaction, "You are Exhausted and cannot vote today.")
            return

        # Build standard target options
        options = []
        guild = interaction.guild
        for pid, pstate in session.players.items():
            if pstate.alive:
                member = guild.get_member(pid) if guild else None
                name = member.display_name if member else f"User {pid}"
                options.append(discord.SelectOption(label=name, value=str(pid)))

        if player.role_key == "hiromi_higuruma":
            day_num = session.metadata.get("day_num", 1)
            deadly_uses = player.metadata.setdefault("deadly_sentencing_uses", 2)
            used_today = (player.metadata.get("higuruma_used_ability_day") == day_num)
            if deadly_uses > 0 and not used_today:
                view = discord.ui.View(timeout=30)
                btn_normal = discord.ui.Button(label="Cast Normal Vote", style=discord.ButtonStyle.secondary)
                btn_deadly = discord.ui.Button(label=f"Deadly Sentencing ({deadly_uses} left)", style=discord.ButtonStyle.danger)

                async def normal_cb(inter: discord.Interaction) -> None:
                    normal_options = [discord.SelectOption(label="Skip Vote", value="skip")] + options
                    v = discord.ui.View(timeout=60)
                    select = VoteSelector(self.game_id, self.engine, normal_options)
                    v.add_item(select)
                    await _reply(inter, "Select a target to vote for (or Skip):", view=v)

                async def deadly_cb(inter: discord.Interaction) -> None:
                    deadly_targets = [opt for opt in options if opt.value != str(user_id)]
                    if not deadly_targets:
                        await _reply(inter, "No eligible players to execute.")
                        return
                    v = discord.ui.View(timeout=60)
                    select = HiromiDeadlySentencingSelect(self.game_id, self.engine, deadly_targets)
                    v.add_item(select)
                    await _reply(inter, f"{get_emoji('trial')} **Deadly Sentencing:** Select a player to instantly execute:", view=v)

                btn_normal.callback = normal_cb
                btn_deadly.callback = deadly_cb
                view.add_item(btn_normal)
                view.add_item(btn_deadly)
                await _reply(interaction, "Hiromi Higuruma, select an action:", view=view)
                return

        normal_options = [discord.SelectOption(label="Skip Vote", value="skip")] + options
        view = discord.ui.View(timeout=60)
        select = VoteSelector(self.game_id, self.engine, normal_options)
        view.add_item(select)
        await _reply(interaction, "Select a target to vote for (or Skip):", view=view)


class HiromiDeadlySentencingSelect(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Select player to sentence...", options=options[:25])
        self.game_id = game_id
        self.engine = engine

    async def callback(self, interaction: discord.Interaction) -> None:
        # Defer response immediately to avoid 3-second timeout
        if not interaction.response.is_done():
            try:
                await interaction.response.defer(ephemeral=True)
            except Exception:
                pass
        
        target_id = int(self.values[0])
        session = await self.engine.get_session(self.game_id)
        if not session:
            return

        if session.phase != GamePhase.VOTING:
            await interaction.followup.send("Voting phase has already ended.", ephemeral=True)
            return

        player = session.players.get(interaction.user.id)
        if not player or player.role_key != "hiromi_higuruma":
            return

        day_num = session.metadata.get("day_num", 1)
        if player.metadata.get("higuruma_used_ability_day") == day_num:
            await interaction.followup.send("You have already used a courtroom ability today!", ephemeral=True)
            return

        deadly_uses = player.metadata.get("deadly_sentencing_uses", 2)
        if deadly_uses <= 0:
            await interaction.followup.send("You have no uses left.", ephemeral=True)
            return

        async with self.engine._lock:
            player.metadata["deadly_sentencing_uses"] = deadly_uses - 1
            player.metadata["higuruma_used_ability_day"] = day_num
            session.metadata["deadly_sentencing_triggered"] = True
            session.metadata["deadly_sentencing_active"] = True
            session.metadata["deadly_sentencing_run"] = True

        target_player = session.players.get(target_id)
        target_faction = target_player.faction if target_player else None
        
        mafia_channel = interaction.channel
        await self.engine.bot.message_queue.send(
            mafia_channel,
            f"{get_emoji('court')} **Hiromi Higuruma has declared Deadly Sentencing on <@{target_id}>!**\n"
        )

        await asyncio.sleep(3)

        # Mahoraga adaptation intercept — if target has adapted to Protagonist (Town) faction,
        # the Deadly Sentencing is blocked, role is revealed, and the use is wasted.
        if (
            target_player
            and target_player.role_key == "mahoraga"
            and "Protagonist" in target_player.metadata.get("mahoraga_adapted_factions", [])
        ):
            mahoraga_null_view = build_v2_layout(
                title="Deadly Sentencing Nullified!",
                description=(
                    f"**Hiromi Higuruma's** judgment could not be carried out!\n\n"
                    f"<@{target_id}> has **adapted to the Protagonist faction** — "
                    f"all Protagonist abilities, including this Sentencing, are nullified against them.\n\n"
                    f"Their role has been revealed: **Eight-Handled Sword Divergent Sila Divine General Mahoraga** 🌀\n\n"
                    f"The Sentencing use has been consumed."
                ),
                color=discord.Color.from_rgb(110, 58, 190),
            )
            await self.engine.bot.message_queue.send(
                mafia_channel, view=mahoraga_null_view)


            async with self.engine._lock:
                session.metadata["deadly_sentencing_active"] = False
            await _safe_respond_or_edit(interaction, description="Deadly Sentencing failed — target has Protagonist adaptation.")
            return

        # Send Deadly Sentencing animation GIF and wait 12 seconds
        sentencing_gif = "https://static2.klipy.com/ii/4493325008d34b7bf8cd6813cd5c1619/c1/fe/jpjrHLS0LwS0xMqN.gif"
        await self.engine.bot.message_queue.send(mafia_channel, sentencing_gif)
        await asyncio.sleep(8)

        faction_display = "Town (Hero)"
        if target_faction == RoleFaction.VILLAIN.value:
            faction_display = "Mafia (Villain)"
        elif target_faction == "Neutral":
            faction_display = "Neutral"

        await self.engine.bot.message_queue.send(
            mafia_channel,
            f"The defendant <@{target_id}> was aligned with the **{faction_display}** faction!"
        )

        await asyncio.sleep(3)

        target_state = target_player or session.players.get(target_id)

        # Get target name for messaging
        try:
            guild = self.engine.bot.get_guild(session.game_handle.guild_id)
            target_member = guild.get_member(target_id) if guild else None
            target_name = target_member.display_name if target_member else f"User {target_id}"
        except Exception:
            target_name = f"User {target_id}"

        if target_state and target_state.role_key == "makima" and not target_state.metadata.get("pm_contract_activated"):
            target_state.metadata["pm_contract_activated"] = True
            await self.engine.bot.message_queue.send(
                mafia_channel,
                f"{get_emoji('trial')} **Prime Minister's Contract Triggered!** An invisible force prevented Makima's execution!"
            )
            async with self.engine._lock:
                session.metadata["deadly_sentencing_active"] = False
            await _safe_respond_or_edit(interaction, description="Deadly Sentencing failed — Makima's Prime Minister's Contract protected her.")
            return

        await self.engine.eliminate_player(self.game_id, target_id, "deadly_sentencing")
        await self.engine.bot.message_queue.send(
            mafia_channel,
            f"Defendant <@{target_id}> was immediately executed under the Prosecutor's absolute authority!"
        )

        if target_state and target_state.role_key == "lelouch":
            target_state.metadata["lelouch_lynched"] = True
            zero_requiem_layout = build_v2_layout(
                title=f"{get_emoji('crown')} Zero Requiem Activated!",
                description=(
                    f"**{target_name}** (Lelouch Lamperouge) has been executed under Deadly Sentencing!\n\n"
                    f"This was all part of his master plan to focus the world's hatred on himself and die, breaking the cycle of hatred.\n\n"
                    f"{get_emoji('victory')} **Lelouch Lamperouge wins the game!**"
                ),
                color=discord.Color.purple(),
            )
            await self.engine.bot.message_queue.send(
                mafia_channel,
                view=zero_requiem_layout
            )
            session.state = GameState.ENDED
            session.winner_faction = "Lelouch Lamperouge"

        if target_faction == RoleFaction.HERO.value:
            await asyncio.sleep(3)
            await self.engine.eliminate_player(self.game_id, interaction.user.id, "wrongful_judgment")
            await self.engine.bot.message_queue.send(
                mafia_channel,
                f"{get_emoji('warning')} **Wrongful Judgment!** Hiromi Higuruma executed a fellow **Town** member and was executed by the Hangman!"
            )

        async with self.engine._lock:
            session.metadata["deadly_sentencing_active"] = False

        await _safe_respond_or_edit(interaction, description=f"Deadly Sentencing declared on <@{target_id}>.")


class VoteSelector(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Select a player...", options=options[:25])
        self.game_id = game_id
        self.engine = engine

    async def callback(self, interaction: discord.Interaction) -> None:
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except Exception:
            pass

        value = self.values[0]
        voter_id = interaction.user.id

        session = await self.engine.get_session(self.game_id)
        if not session:
            await interaction.followup.send("This game is no longer active.", ephemeral=True)
            return

        try:
            if value == "skip":
                await self.engine.register_vote(self.game_id, voter_id, None)
                skips = session.metadata.setdefault("skip_votes", [])
                if voter_id not in skips:
                    skips.append(voter_id)
                await _safe_respond_or_edit(interaction, description="You voted to Skip.")
            else:
                target_id = int(value)
                await self.engine.register_vote(self.game_id, voter_id, target_id)
                skips = session.metadata.setdefault("skip_votes", [])
                if voter_id in skips:
                    skips.remove(voter_id)
                await _safe_respond_or_edit(interaction, description=f"Voted for <@{target_id}>.")
        except RuntimeError:
            await _safe_respond_or_edit(interaction, description=f"{get_emoji('cross')} Voting has already ended for this round — your vote wasn't counted.")
        except Exception as exc:
            logger.exception("Error during vote registration")
            try:
                await _safe_respond_or_edit(interaction, description=f"{get_emoji('cross')} Failed to register vote: {exc}")
            except Exception:
                pass


class VerdictUISelectView(MafiosoLayoutView):
    def __init__(self, game_id: str, engine: GameEngine) -> None:
        super().__init__(timeout=None)

        self.game_id = game_id
        self.engine = engine

    @discord.ui.button(label="Guilty", style=discord.ButtonStyle.danger, custom_id="mafia_verdict_guilty")
    async def guilty(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._register_verdict(interaction, "guilty")

    @discord.ui.button(label="Innocent", style=discord.ButtonStyle.success, custom_id="mafia_verdict_innocent")
    async def innocent(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._register_verdict(interaction, "innocent")

    async def _register_verdict(self, interaction: discord.Interaction, decision: str) -> None:
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except Exception:
            pass

        session = await self.engine.get_session(self.game_id)
        if not session:
            await interaction.followup.send("This game is no longer active.", ephemeral=True)
            return

        user_id = interaction.user.id
        if user_id not in session.players:
            await interaction.followup.send("You are not part of this game.", ephemeral=True)
            return

        player = session.players[user_id]
        if not player.alive:
            await interaction.followup.send("Dead players cannot vote on verdict.", ephemeral=True)
            return
            
        defendant_id = session.metadata.get("defendant_id")
        if user_id == defendant_id:
            await interaction.followup.send("You cannot vote on your own trial!", ephemeral=True)
            return

        if session.phase != GamePhase.EXECUTION:
            await interaction.followup.send(
                f"{get_emoji('cross')} The trial has already ended — your verdict wasn't counted.",
                ephemeral=True,
            )
            return

        # If forced guilty (e.g. during a Retrial trial), they must vote guilty
        if session.metadata.get("forced_guilty"):
            decision = "guilty"

        # Hiromi Higuruma Retrial check
        if decision == "innocent" and player.role_key == "hiromi_higuruma":
            day_num = session.metadata.get("day_num", 1)
            retrial_uses = player.metadata.setdefault("retrial_uses", 2)
            used_today = (player.metadata.get("higuruma_used_ability_day") == day_num)
            if retrial_uses > 0 and not used_today:
                view = discord.ui.View(timeout=30)
                btn_normal = discord.ui.Button(label="Vote Innocent Normally", style=discord.ButtonStyle.secondary)
                btn_retrial = discord.ui.Button(label=f"Trigger Retrial ({retrial_uses} left)", style=discord.ButtonStyle.danger)

                async def normal_cb(inter: discord.Interaction) -> None:
                    try:
                        if not inter.response.is_done():
                            await inter.response.defer(ephemeral=True)
                    except Exception:
                        pass
                    verdicts = session.metadata.setdefault("verdicts", {})
                    verdicts[str(inter.user.id)] = "innocent"
                    await _safe_respond_or_edit(inter, description="Registered normal Innocent verdict.")

                async def retrial_cb(inter: discord.Interaction) -> None:
                    try:
                        if not inter.response.is_done():
                            await inter.response.defer(ephemeral=True)
                    except Exception:
                        pass
                    async with self.engine._lock:
                        player.metadata["retrial_uses"] = retrial_uses - 1
                        player.metadata["higuruma_used_ability_day"] = day_num
                        session.metadata["retrial_triggered"] = True
                        session.metadata["retrial_defendant"] = defendant_id
                        session.metadata["retrial_by"] = inter.user.id
                    
                    mafia_channel = inter.channel
                    await self.engine.bot.message_queue.send(
                        mafia_channel,
                        f"{get_emoji('trial')} <@{inter.user.id}> (Hiromi Higuruma) has activated **Retrial** for this case!"
                    )
                    await _safe_respond_or_edit(inter, description=f"{get_emoji('trial')} **Retrial Activated!**")

                btn_normal.callback = normal_cb
                btn_retrial.callback = retrial_cb
                view.add_item(btn_normal)
                view.add_item(btn_retrial)
                await interaction.followup.send("Choose whether to trigger Retrial:", view=view, ephemeral=True)
                return

        verdicts = session.metadata.setdefault("verdicts", {})
        verdicts[str(user_id)] = decision
        await interaction.followup.send(f"You cast a verdict of **{decision.upper()}**.", ephemeral=True)
