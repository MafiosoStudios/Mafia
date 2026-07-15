from __future__ import annotations

import discord
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from game_engine import GameSession, GameEngine

import asyncio
import logging
from config import get_emoji
from utils.constants import GamePhase, RoleFaction

logger = logging.getLogger(__name__)


async def _safe_queue_night_action(
    interaction: discord.Interaction,
    engine: "GameEngine",
    game_id: str,
    user_id: int,
    payload: dict[str, Any],
) -> bool:
    """Submits a night action, gracefully handling the case where the night
    phase already ended or parameters are invalid. Returns True on success."""
    try:
        await engine.queue_night_action(game_id, user_id, payload)
        return True
    except RuntimeError:
        await interaction.response.edit_message(
            content=f"{get_emoji('cross')} Night actions have already locked in — your action wasn't submitted.",
            view=None,
        )
        return False
    except ValueError as val_err:
        await interaction.response.edit_message(
            content=f"{get_emoji('cross')} **Invalid Action:** {val_err}",
            view=None,
        )
        return False
    except Exception as exc:
        logger.exception("Unexpected error in night action queue")
        await interaction.response.edit_message(
            content=f"{get_emoji('cross')} An unexpected error occurred: {exc}",
            view=None,
        )
        return False


class StartGameView(discord.ui.View):
    """Shown to the host after setup. Clicking 'Start Game' creates the channel and begins the match."""

    def __init__(self, game_id: str, engine: GameEngine) -> None:
        super().__init__(timeout=300)  # 5 minutes to click
        self.game_id = game_id
        self.engine = engine
        self.children[0].label = f"{get_emoji('lobby')} Start Game"

    @discord.ui.button(label="Start Game", style=discord.ButtonStyle.success, custom_id="mafia_start_game_button")
    async def start_game(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        session = await self.engine.get_session(self.game_id)
        if not session:
            await interaction.response.send_message("This game is no longer active.", ephemeral=True)
            return

        # Only the host (or an admin) can start the game
        host_id = session.game_handle.host_id
        is_admin = interaction.user.guild_permissions.administrator if isinstance(interaction.user, discord.Member) else False
        if interaction.user.id != host_id and not is_admin:
            await interaction.response.send_message("Only the match host or an admin can start the game!", ephemeral=True)
            return

        # Disable the button immediately
        button.disabled = True
        button.label = "Game Starting..."
        await interaction.response.edit_message(
            embed=discord.Embed(
                title=f"{get_emoji('lobby')} Game Starting!",
                description="Creating the game channel and initializing the match...",
                color=discord.Color.blurple()
            ),
            view=self
        )

        # Launch the game loop as a background task
        asyncio.create_task(self.engine.run_game_loop(self.game_id))


class SpectateView(discord.ui.View):
    """Shown in the lobby channel when a game begins, allowing non-players to spectate the match channel."""

    def __init__(self, game_id: str, engine: GameEngine) -> None:
        super().__init__(timeout=None)
        self.game_id = game_id
        self.engine = engine

    @discord.ui.button(label="Spectate", style=discord.ButtonStyle.blurple, custom_id="spectate_button")
    async def spectate(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        session = await self.engine.get_session(self.game_id)
        if not session:
            await interaction.response.send_message("❌ This game is no longer active.", ephemeral=True)
            return

        if interaction.user.id in session.player_ids:
            await interaction.response.send_message("❌ You are a player in this game! You cannot spectate.", ephemeral=True)
            return

        mafia_ch_id = session.metadata.get("mafia_channel_id")
        if not mafia_ch_id:
            await interaction.response.send_message("❌ Match channel not found.", ephemeral=True)
            return

        guild = interaction.guild
        if guild:
            ch = guild.get_channel(mafia_ch_id)
            if ch:
                await ch.set_permissions(interaction.user, read_messages=True, send_messages=False)
                await interaction.response.send_message(f"✅ You are now spectating! Check out <#{mafia_ch_id}>.", ephemeral=True)
                return

        await interaction.response.send_message("❌ Failed to add spectator permissions.", ephemeral=True)


class NightActionView(discord.ui.View):
    def __init__(self, game_id: str, engine: GameEngine) -> None:
        super().__init__(timeout=None)
        self.game_id = game_id
        self.engine = engine

    @discord.ui.button(label="Choose Night Action", style=discord.ButtonStyle.primary, custom_id="mafia_choose_night_action")
    async def choose_action(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        session = await self.engine.get_session(self.game_id)
        if not session:
            await interaction.response.send_message("This game is no longer active.", ephemeral=True)
            return

        user_id = interaction.user.id
        if user_id not in session.players:
            await interaction.response.send_message("You are not part of this game lobby.", ephemeral=True)
            return

        player = session.players[user_id]
        if not player.alive:
            await interaction.response.send_message("Dead players cannot perform night actions.", ephemeral=True)
            return

        # Check Wounded status
        if player.metadata.get("wounded_until_night") == session.metadata.get("night_num", 1):
            await interaction.response.send_message("You are Wounded and cannot act tonight!", ephemeral=True)
            return

        # Check Exhausted status
        if player.metadata.get("exhausted_until_night") == session.metadata.get("night_num", 1):
            await interaction.response.send_message("You are Exhausted and cannot act tonight!", ephemeral=True)
            return

        if player.metadata.get("roleblocked"):
            await interaction.response.send_message("You feel disoriented... You have been roleblocked and cannot act tonight!", ephemeral=True)
            return

        if player.metadata.get("detained"):
            await interaction.response.send_message("🌑 You are detained inside Tōsen's Bankai and cannot act tonight.", ephemeral=True)
            return

        role_key = player.role_key
        if not role_key:
            await interaction.response.send_message("You do not have a role assigned.", ephemeral=True)
            return

        # Special check for roles that can't act
        if role_key in ["villager", "demon", "mahoraga"]:
            await interaction.response.send_message("You do not have an active night ability.", ephemeral=True)
            return

        # Instantiate role to retrieve abilities
        from utils.roles import role_registry, NightAction
        role_cls = role_registry.get(role_key) if role_registry.contains(role_key) else None
        if not role_cls:
            await interaction.response.send_message("Your role is not registered.", ephemeral=True)
            return

        role_inst = role_cls()
        active_abilities = [a for a in role_inst.abilities if isinstance(a, NightAction)]
        if not active_abilities:
            await interaction.response.send_message("You do not have an active night ability.", ephemeral=True)
            return

        # Handle legacy role-specific custom views (e.g. Light Yagami)
        # Note: Kenzo Tenma is now fully updated, but Light Yagami uses a special guess panel
        if role_key == "light_yagami":
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
                async with self.engine._lock:
                    if inter.user.id in session.night_actions:
                        session.night_actions.pop(inter.user.id, None)
                        player.night_actions_used = max(0, player.night_actions_used - 1)
                        await inter.response.edit_message(content="✅ **Your night action has been cancelled.**", view=None)
                        return
                await inter.response.send_message("❌ You have not submitted any night actions yet tonight.", ephemeral=True)
            cancel_btn.callback = ly_cancel_callback
            view.add_item(cancel_btn)
            
            await interaction.response.send_message("Select which ability you wish to use:", view=view, ephemeral=True)
            return

        # Otherwise, present the dynamic separate buttons view for the role's abilities!
        view = NightAbilityButtonsView(self.game_id, self.engine, user_id, role_inst, session)
        await interaction.response.send_message("Select an ability to use tonight:", view=view, ephemeral=True)


class NightAbilityButtonsView(discord.ui.View):
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
            session = await self.engine.get_session(self.game_id)
            if not session:
                await interaction.response.send_message("This game is no longer active.", ephemeral=True)
                return

            player_state = session.players.get(self.player_id)
            if not player_state or not player_state.alive:
                await interaction.response.send_message("You cannot perform night actions.", ephemeral=True)
                return

            if player_state.metadata.get("roleblocked"):
                await interaction.response.send_message("You are roleblocked and cannot act tonight!", ephemeral=True)
                return

            if player_state.metadata.get("detained"):
                await interaction.response.send_message("🌑 You are detained inside Tōsen's Bankai and cannot act tonight.", ephemeral=True)
                return

            # Check if wounded/exhausted
            night_num = session.metadata.get("night_num", 1)
            if player_state.metadata.get("wounded_until_night") == night_num or player_state.metadata.get("exhausted_until_night") == night_num:
                await interaction.response.send_message("You cannot use abilities tonight.", ephemeral=True)
                return

            # Check if this ability can be used yet
            can_use, reason = ability.can_use(session, player_state)
            if not can_use:
                # If they have someone selected, remove/clear that selection!
                removed = False
                async with self.engine._lock:
                    if self.player_id in session.night_actions:
                        session.night_actions.pop(self.player_id, None)
                        player_state.night_actions_used = max(0, player_state.night_actions_used - 1)
                        removed = True
                
                msg = f"❌ **You cannot use {ability.name} yet.**\nReason: {reason or 'Not available.'}"
                if removed:
                    msg += "\n⚠️ **Your previously registered night action target has been cleared.**"
                await interaction.response.send_message(msg, ephemeral=True)
                return

            # Retrieve eligible targets
            targets = ability.get_eligible_targets(session, self.player_id)
            
            # Teammate validation for Villain faction (Mafia)
            if player_state.faction == "Villain" and self.role_inst.role_key in ["blackbeard", "light_yagami", "muzan_kibutsuji", "makima", "upper_moon"]:
                targets = [t for t in targets if session.players[t].faction != "Villain"]

            if ability.num_targets > 0 and not targets:
                await interaction.response.send_message("No eligible targets for this ability.", ephemeral=True)
                return

            # If 0 targets (like Levi's Precision Strike)
            if ability.num_targets == 0:
                payload = {
                    "action_index": idx,
                    "target_id": None
                }
                if not await _safe_queue_night_action(interaction, self.engine, self.game_id, self.player_id, payload):
                    return
                await interaction.response.edit_message(content=f"Ability **{ability.name}** activated successfully.", view=None)
                return

            # Build SelectOptions
            options = []
            guild = interaction.guild
            for pid in targets:
                # Self targeting check (only doctor tenma is allowed to heal himself)
                if pid == self.player_id and self.role_inst.role_key != "doctor_tenma":
                    continue
                member = guild.get_member(pid) if guild else None
                name = member.display_name if member else f"User {pid}"
                options.append(discord.SelectOption(label=name, value=str(pid)))

            if not options:
                await interaction.response.send_message("No eligible targets for this ability.", ephemeral=True)
                return

            view = discord.ui.View(timeout=120)
            if ability.name == "Texture Surprise":
                select = TextureSurpriseStep1(self.game_id, self.engine, ability, idx, options)
                view.add_item(select)
            elif ability.name == "Brew Potion":
                select = MaomaoBrewPotionStep1(self.game_id, self.engine, ability, idx, options)
                view.add_item(select)
            elif ability.name == "Demon Detection":
                select = FrierenDemonDetectionStep1(self.game_id, self.engine, ability, idx, options)
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
                orig_view = NightAbilityButtonsView(self.game_id, self.engine, self.player_id, self.role_inst, session)
                await inter.response.edit_message(content="Select an ability to use tonight:", view=orig_view)
            back_btn.callback = back_callback
            view.add_item(back_btn)

            if ability.name == "Texture Surprise":
                await interaction.response.edit_message(content=f"Using **{ability.name}**.\nSelect the player to disguise:", view=view)
            elif ability.name == "Brew Potion":
                await interaction.response.edit_message(content=f"Using **{ability.name}**.\nSelect the potion you want to brew:", view=view)
            elif ability.name == "Demon Detection":
                await interaction.response.edit_message(content=f"Using **{ability.name}**.\nSelect the first target:", view=view)
            elif ability.num_targets == 2:
                await interaction.response.edit_message(content=f"Using **{ability.name}**.\nSelect the first target:", view=view)
            else:
                await interaction.response.edit_message(content=f"Using **{ability.name}**.\nSelect your target:", view=view)

        return callback

    async def cancel_action_callback(self, interaction: discord.Interaction) -> None:
        session = await self.engine.get_session(self.game_id)
        if not session:
            await interaction.response.send_message("This game is no longer active.", ephemeral=True)
            return

        player_state = session.players.get(self.player_id)
        if not player_state:
            return

        async with self.engine._lock:
            if self.player_id in session.night_actions:
                session.night_actions.pop(self.player_id, None)
                player_state.night_actions_used = max(0, player_state.night_actions_used - 1)
                await interaction.response.edit_message(content="✅ **Your night action has been cancelled.**\nFeel free to select a new target at any time tonight.", view=None)
                return
        
        await interaction.response.send_message("❌ You have not submitted any night actions yet tonight.", ephemeral=True)


class AbilityTargetSelect(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, ability: Any, action_index: int, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Select a target...", options=options[:25])
        self.game_id = game_id
        self.engine = engine
        self.ability = ability
        self.action_index = action_index

    async def callback(self, interaction: discord.Interaction) -> None:
        target_id = int(self.values[0])
        payload = {
            "action_index": self.action_index,
            "target_id": target_id
        }
        if not await _safe_queue_night_action(interaction, self.engine, self.game_id, interaction.user.id, payload):
            return
        await interaction.response.edit_message(content=f"Ability **{self.ability.name}** registered on <@{target_id}>.", view=None)


class TwoTargetSelectStep1(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, ability: Any, action_index: int, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Select first target...", options=options[:25])
        self.game_id = game_id
        self.engine = engine
        self.ability = ability
        self.action_index = action_index
        self.target_options = options

    async def callback(self, interaction: discord.Interaction) -> None:
        target1 = int(self.values[0])
        options2 = [opt for opt in self.target_options if opt.value != str(target1)]
        view = discord.ui.View(timeout=120)
        select2 = TwoTargetSelectStep2(self.game_id, self.engine, self.ability, self.action_index, target1, options2)
        view.add_item(select2)
        await interaction.response.edit_message(content=f"Using **{self.ability.name}**.\nSelect the second target to pair with <@{target1}>:", view=view)


class TwoTargetSelectStep2(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, ability: Any, action_index: int, target1: int, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Select second target...", options=options[:25])
        self.game_id = game_id
        self.engine = engine
        self.ability = ability
        self.action_index = action_index
        self.target1 = target1

    async def callback(self, interaction: discord.Interaction) -> None:
        target2 = int(self.values[0])
        payload = {
            "action_index": self.action_index,
            "target_id": self.target1,
            "controlled_vote_target": target2,
            "targets": (self.target1, target2)
        }
        if not await _safe_queue_night_action(interaction, self.engine, self.game_id, interaction.user.id, payload):
            return
        await interaction.response.edit_message(content=f"Ability **{self.ability.name}** registered on <@{self.target1}> and <@{target2}>.", view=None)


class TextureSurpriseStep1(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, ability: Any, action_index: int, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Select a player to disguise...", options=options[:25])
        self.game_id = game_id
        self.engine = engine
        self.ability = ability
        self.action_index = action_index

    async def callback(self, interaction: discord.Interaction) -> None:
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
            session = await self.engine.get_session(self.game_id)
            if session:
                from views.game_ui import NightAbilityButtonsView
                role_inst = session.players[interaction.user.id].role_inst
                orig_view = NightAbilityButtonsView(self.game_id, self.engine, interaction.user.id, role_inst, session)
                await inter.response.edit_message(content="Select an ability to use tonight:", view=orig_view)
        back_btn.callback = back_callback
        view.add_item(back_btn)
        
        await interaction.response.edit_message(content=f"Using **{self.ability.name}** on <@{target_id}>.\nChoose disguised Faction:", view=view)


class TextureSurpriseStep2(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, ability: Any, action_index: int, target_id: int, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Choose faction...", options=options)
        self.game_id = game_id
        self.engine = engine
        self.ability = ability
        self.action_index = action_index
        self.target_id = target_id

    async def callback(self, interaction: discord.Interaction) -> None:
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
            session = await self.engine.get_session(self.game_id)
            if session:
                from views.game_ui import NightAbilityButtonsView
                role_inst = session.players[interaction.user.id].role_inst
                orig_view = NightAbilityButtonsView(self.game_id, self.engine, interaction.user.id, role_inst, session)
                await inter.response.edit_message(content="Select an ability to use tonight:", view=orig_view)
        back_btn.callback = back_callback
        view.add_item(back_btn)
        
        await interaction.response.edit_message(content=f"Using **{self.ability.name}** on <@{self.target_id}>.\nChoose disguised Category:", view=view)


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
        category_choice = self.values[0]
        payload = {
            "action_index": self.action_index,
            "target_id": self.target_id,
            "disguised_faction": self.faction_choice,
            "disguised_category": category_choice
        }
        if not await _safe_queue_night_action(interaction, self.engine, self.game_id, interaction.user.id, payload):
            return
        await interaction.response.edit_message(content=f"Ability **{self.ability.name}** registered. Target <@{self.target_id}> will appear as faction **{self.faction_choice}** and category **{category_choice}** tonight.", view=None)


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
        potion_choice = self.values[0]
        view = discord.ui.View(timeout=120)
        select2 = MaomaoBrewPotionStep2(self.game_id, self.engine, self.ability, self.action_index, potion_choice, self.target_options)
        view.add_item(select2)
        
        back_btn = discord.ui.Button(label="Cancel / Go Back", style=discord.ButtonStyle.danger)
        async def back_callback(inter: discord.Interaction) -> None:
            session = await self.engine.get_session(self.game_id)
            if session:
                from views.game_ui import NightAbilityButtonsView
                role_inst = session.players[interaction.user.id].role_inst
                orig_view = NightAbilityButtonsView(self.game_id, self.engine, interaction.user.id, role_inst, session)
                await inter.response.edit_message(content="Select an ability to use tonight:", view=orig_view)
        back_btn.callback = back_callback
        view.add_item(back_btn)
        
        potion_label = next(opt.label for opt in self.options if opt.value == potion_choice)
        await interaction.response.edit_message(content=f"Brewing **{potion_label}**.\nSelect the player to use it on:", view=view)


class MaomaoBrewPotionStep2(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, ability: Any, action_index: int, potion_choice: str, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Select target player...", options=options[:25])
        self.game_id = game_id
        self.engine = engine
        self.ability = ability
        self.action_index = action_index
        self.potion_choice = potion_choice

    async def callback(self, interaction: discord.Interaction) -> None:
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
        await interaction.response.edit_message(content=f"Successfully queued **{potion_name}** on <@{target_id}>.", view=None)


class FrierenDemonDetectionStep1(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, ability: Any, action_index: int, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Select first target...", options=options[:25])
        self.game_id = game_id
        self.engine = engine
        self.ability = ability
        self.action_index = action_index
        self.target_options = options

    async def callback(self, interaction: discord.Interaction) -> None:
        target1 = int(self.values[0])
        options2 = [opt for opt in self.target_options if opt.value != str(target1)]
        view = discord.ui.View(timeout=120)
        select2 = FrierenDemonDetectionStep2(self.game_id, self.engine, self.ability, self.action_index, target1, options2, self.target_options)
        view.add_item(select2)
        
        back_btn = discord.ui.Button(label="Cancel / Go Back", style=discord.ButtonStyle.danger)
        async def back_callback(inter: discord.Interaction) -> None:
            session = await self.engine.get_session(self.game_id)
            if session:
                from views.game_ui import NightAbilityButtonsView
                role_inst = session.players[interaction.user.id].role_inst
                orig_view = NightAbilityButtonsView(self.game_id, self.engine, interaction.user.id, role_inst, session)
                await inter.response.edit_message(content="Select an ability to use tonight:", view=orig_view)
        back_btn.callback = back_callback
        view.add_item(back_btn)
        
        await interaction.response.edit_message(content=f"Using **{self.ability.name}**.\nSelect the second target to pair with <@{target1}>:", view=view)


class FrierenDemonDetectionStep2(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, ability: Any, action_index: int, target1: int, options: list[discord.SelectOption], original_options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Select second target...", options=options[:25])
        self.game_id = game_id
        self.engine = engine
        self.ability = ability
        self.action_index = action_index
        self.target1 = target1
        self.original_options = original_options

    async def callback(self, interaction: discord.Interaction) -> None:
        target2 = int(self.values[0])
        options3 = [opt for opt in self.original_options if opt.value != str(self.target1) and opt.value != str(target2)]
        view = discord.ui.View(timeout=120)
        select3 = FrierenDemonDetectionStep3(self.game_id, self.engine, self.ability, self.action_index, self.target1, target2, options3)
        view.add_item(select3)
        
        back_btn = discord.ui.Button(label="Cancel / Go Back", style=discord.ButtonStyle.danger)
        async def back_callback(inter: discord.Interaction) -> None:
            session = await self.engine.get_session(self.game_id)
            if session:
                from views.game_ui import NightAbilityButtonsView
                role_inst = session.players[interaction.user.id].role_inst
                orig_view = NightAbilityButtonsView(self.game_id, self.engine, interaction.user.id, role_inst, session)
                await inter.response.edit_message(content="Select an ability to use tonight:", view=orig_view)
        back_btn.callback = back_callback
        view.add_item(back_btn)
        
        await interaction.response.edit_message(content=f"Using **{self.ability.name}**.\nSelect the third target to pair with <@{self.target1}> and <@{target2}>:", view=view)


class FrierenDemonDetectionStep3(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, ability: Any, action_index: int, target1: int, target2: int, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Select third target...", options=options[:25])
        self.game_id = game_id
        self.engine = engine
        self.ability = ability
        self.action_index = action_index
        self.target1 = target1
        self.target2 = target2

    async def callback(self, interaction: discord.Interaction) -> None:
        target3 = int(self.values[0])
        payload = {
            "action_index": self.action_index,
            "target_id": self.target1,
            "targets": (self.target1, self.target2, target3)
        }
        if not await _safe_queue_night_action(interaction, self.engine, self.game_id, interaction.user.id, payload):
            return
        await interaction.response.edit_message(content=f"Ability **{self.ability.name}** registered on <@{self.target1}>, <@{self.target2}>, and <@{target3}>.", view=None)


class StandardActionSelect(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Select a target...", options=options[:25])
        self.game_id = game_id
        self.engine = engine

    async def callback(self, interaction: discord.Interaction) -> None:
        target_id = int(self.values[0])
        if not await _safe_queue_night_action(interaction, self.engine, self.game_id, interaction.user.id, {"target_id": target_id}):
            return
        await interaction.response.edit_message(content=f"Night action registered on <@{target_id}>.", view=None)


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
        action_type = self.values[0]
        view = discord.ui.View(timeout=120)
        
        if action_type == "heal":
            select = TenmaHealSelect(self.game_id, self.engine, self.target_options)
            view.add_item(select)
            await interaction.response.edit_message(content="Select a player to heal:", view=view)
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
                await interaction.response.edit_message(content="There are no dead mafia members to revive.", view=None)
                return

            select = TenmaReviveSelect(self.game_id, self.engine, dead_mafia_options)
            view.add_item(select)
            await interaction.response.edit_message(content="Select a dead mafia member to revive as a Default Villager:", view=view)


class TenmaHealSelect(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Select a player to heal...", options=options[:25])
        self.game_id = game_id
        self.engine = engine

    async def callback(self, interaction: discord.Interaction) -> None:
        target_id = int(self.values[0])
        if not await _safe_queue_night_action(interaction, self.engine, self.game_id, interaction.user.id, {"target_id": target_id, "action_type": "heal"}):
            return
        await interaction.response.edit_message(content=f"Night action registered: Healing <@{target_id}>.", view=None)


class TenmaReviveSelect(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Select a dead mafia member...", options=options[:25])
        self.game_id = game_id
        self.engine = engine

    async def callback(self, interaction: discord.Interaction) -> None:
        target_id = int(self.values[0])
        if not await _safe_queue_night_action(interaction, self.engine, self.game_id, interaction.user.id, {"target_id": target_id, "action_type": "revive"}):
            return
        await interaction.response.edit_message(content=f"Night action registered: Reviving <@{target_id}>.", view=None)


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
        action_type = self.values[0]
        view = discord.ui.View(timeout=120)
        
        if action_type == "guess":
            select = LightYagamiTargetSelect(self.game_id, self.engine, self.target_options)
            view.add_item(select)
            await interaction.response.edit_message(content="Select a player to guess their role:", view=view)
        else:
            select = LightYagamiPenSelect(self.game_id, self.engine, self.target_options)
            view.add_item(select)
            await interaction.response.edit_message(content="Select a player to write in your notebook:", view=view)


class LightYagamiTargetSelect(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Select a player...", options=options[:25])
        self.game_id = game_id
        self.engine = engine

    async def callback(self, interaction: discord.Interaction) -> None:
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
        await interaction.response.edit_message(content=f"Select the guessed role for <@{target_id}>:", view=view)


class LightYagamiRoleGuessSelect(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, target_id: int, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Select guessed role...", options=options)
        self.game_id = game_id
        self.engine = engine
        self.target_id = target_id

    async def callback(self, interaction: discord.Interaction) -> None:
        guessed_role = self.values[0]
        payload = {
            "target_id": self.target_id,
            "action_type": "guess",
            "guessed_role": guessed_role
        }
        if not await _safe_queue_night_action(interaction, self.engine, self.game_id, interaction.user.id, payload):
            return
        await interaction.response.edit_message(content=f"Death Note guess registered on <@{self.target_id}> for role '{guessed_role}'.", view=None)


class LightYagamiPenSelect(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Select player to write down...", options=options[:25])
        self.game_id = game_id
        self.engine = engine

    async def callback(self, interaction: discord.Interaction) -> None:
        target_id = int(self.values[0])
        payload = {
            "target_id": target_id,
            "action_type": "devils_pen"
        }
        if not await _safe_queue_night_action(interaction, self.engine, self.game_id, interaction.user.id, payload):
            return
        await interaction.response.edit_message(content=f"Devil's Pen registered on <@{target_id}>.", view=None)


class MakimaSelect(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Select player to control...", options=options[:25])
        self.game_id = game_id
        self.engine = engine
        self.target_options = options

    async def callback(self, interaction: discord.Interaction) -> None:
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
        await interaction.response.edit_message(content=f"Select the target <@{target1}>'s action will be redirected to:", view=view)


class MakimaRedirectTargetSelect(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, target1: int, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Select redirection target...", options=options[:25])
        self.game_id = game_id
        self.engine = engine
        self.target1 = target1

    async def callback(self, interaction: discord.Interaction) -> None:
        target2 = int(self.values[0])
        payload = {
            "target_id": self.target1,
            "redirect_target": target2,
            "action_index": 0
        }
        if not await _safe_queue_night_action(interaction, self.engine, self.game_id, interaction.user.id, payload):
            return
        await interaction.response.edit_message(content=f"Control Devil registered: Redirecting <@{self.target1}> to target <@{target2}>.", view=None)


class HisokaBungeeSelect(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Select first target...", options=options[:25])
        self.game_id = game_id
        self.engine = engine
        self.target_options = options

    async def callback(self, interaction: discord.Interaction) -> None:
        target1 = int(self.values[0])
        options2 = [opt for opt in self.target_options if opt.value != str(target1)]
        view = discord.ui.View(timeout=120)
        select2 = HisokaBungeeLinkSelect(self.game_id, self.engine, target1, options2)
        view.add_item(select2)
        await interaction.response.edit_message(content=f"Select the second target to link with <@{target1}>:", view=view)


class HisokaBungeeLinkSelect(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, target1: int, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Select second target...", options=options[:25])
        self.game_id = game_id
        self.engine = engine
        self.target1 = target1

    async def callback(self, interaction: discord.Interaction) -> None:
        target2 = int(self.values[0])
        payload = {
            "target_id": self.target1,
            "controlled_vote_target": target2
        }
        if not await _safe_queue_night_action(interaction, self.engine, self.game_id, interaction.user.id, payload):
            return
        await interaction.response.edit_message(content=f"Bungee Gum registered: linking <@{self.target1}> with <@{target2}>.", view=None)


class VoteUISelectView(discord.ui.View):
    def __init__(self, game_id: str, engine: GameEngine) -> None:
        super().__init__(timeout=None)
        self.game_id = game_id
        self.engine = engine

    @discord.ui.button(label="Cast Vote", style=discord.ButtonStyle.primary, custom_id="mafia_cast_vote_button")
    async def cast_vote(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        session = await self.engine.get_session(self.game_id)
        if not session:
            await interaction.response.send_message("This game is no longer active.", ephemeral=True)
            return

        user_id = interaction.user.id
        if user_id not in session.players:
            await interaction.response.send_message("You are not part of this game.", ephemeral=True)
            return

        player = session.players[user_id]
        if not player.alive:
            await interaction.response.send_message("Dead players cannot vote.", ephemeral=True)
            return

        day_num = session.metadata.get("day_num", 1)
        if player.metadata.get("wounded_until_day") == day_num:
            await interaction.response.send_message("You are Wounded and cannot vote today.", ephemeral=True)
            return
        if player.metadata.get("exhausted_until_day") == day_num:
            await interaction.response.send_message("You are Exhausted and cannot vote today.", ephemeral=True)
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
            deadly_uses = player.metadata.setdefault("deadly_sentencing_uses", 2)
            if deadly_uses > 0:
                view = discord.ui.View(timeout=30)
                btn_normal = discord.ui.Button(label="Cast Normal Vote", style=discord.ButtonStyle.secondary)
                btn_deadly = discord.ui.Button(label=f"Deadly Sentencing ({deadly_uses} left)", style=discord.ButtonStyle.danger)

                async def normal_cb(inter: discord.Interaction) -> None:
                    normal_options = [discord.SelectOption(label="Skip Vote", value="skip")] + options
                    v = discord.ui.View(timeout=60)
                    select = VoteSelector(self.game_id, self.engine, normal_options)
                    v.add_item(select)
                    await inter.response.send_message("Select a target to vote for (or Skip):", view=v, ephemeral=True)

                async def deadly_cb(inter: discord.Interaction) -> None:
                    deadly_targets = [opt for opt in options if opt.value != str(user_id)]
                    if not deadly_targets:
                        await inter.response.send_message("No eligible players to execute.", ephemeral=True)
                        return
                    v = discord.ui.View(timeout=60)
                    select = HiromiDeadlySentencingSelect(self.game_id, self.engine, deadly_targets)
                    v.add_item(select)
                    await inter.response.send_message("⚖️ **Deadly Sentencing:** Select a player to instantly execute:", view=v, ephemeral=True)

                btn_normal.callback = normal_cb
                btn_deadly.callback = deadly_cb
                view.add_item(btn_normal)
                view.add_item(btn_deadly)
                await interaction.response.send_message("Hiromi Higuruma, select an action:", view=view, ephemeral=True)
                return

        normal_options = [discord.SelectOption(label="Skip Vote", value="skip")] + options
        view = discord.ui.View(timeout=60)
        select = VoteSelector(self.game_id, self.engine, normal_options)
        view.add_item(select)
        await interaction.response.send_message("Select a target to vote for (or Skip):", view=view, ephemeral=True)


class HiromiDeadlySentencingSelect(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Select player to sentence...", options=options[:25])
        self.game_id = game_id
        self.engine = engine

    async def callback(self, interaction: discord.Interaction) -> None:
        # Defer response immediately to avoid 3-second timeout
        await interaction.response.defer(ephemeral=True)
        
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

        deadly_uses = player.metadata.get("deadly_sentencing_uses", 2)
        if deadly_uses <= 0:
            await interaction.followup.send("You have no uses left.", ephemeral=True)
            return

        async with self.engine._lock:
            player.metadata["deadly_sentencing_uses"] = deadly_uses - 1
            session.metadata["deadly_sentencing_triggered"] = True
            session.metadata["deadly_sentencing_active"] = True
            session.metadata["deadly_sentencing_run"] = True

        target_player = session.players.get(target_id)
        target_faction = target_player.faction if target_player else None
        
        mafia_channel = interaction.channel
        await self.engine.bot.message_queue.send(
            mafia_channel,
            f"🏛️ **Hiromi Higuruma has declared Deadly Sentencing!**\n"
            f"Hiromi Higuruma decided to put <@{target_id}> on the stand!"
        )

        await asyncio.sleep(3)

        faction_display = "Town (Hero)"
        if target_faction == RoleFaction.VILLAIN.value:
            faction_display = "Mafia (Villain)"
        elif target_faction == "Neutral":
            faction_display = "Neutral"

        await self.engine.bot.message_queue.send(
            mafia_channel,
            f"⚖️ The defendant <@{target_id}> was aligned with the **{faction_display}** faction!"
        )

        await asyncio.sleep(3)

        await self.engine.eliminate_player(self.game_id, target_id, "deadly_sentencing")
        await self.engine.bot.message_queue.send(
            mafia_channel,
            f"⚡ Defendant <@{target_id}> was immediately executed under the Prosecutor's absolute authority!"
        )

        if target_faction == RoleFaction.HERO.value:
            await asyncio.sleep(3)
            await self.engine.eliminate_player(self.game_id, interaction.user.id, "wrongful_judgment")
            await self.engine.bot.message_queue.send(
                mafia_channel,
                f"⚠️ **Wrongful Judgment!** Hiromi Higuruma executed a fellow **Town** member and was executed by the Hangman!"
            )

        async with self.engine._lock:
            session.metadata["deadly_sentencing_active"] = False

        await interaction.edit_original_response(content=f"Deadly Sentencing declared on <@{target_id}>.", view=None)


class VoteSelector(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Select a player...", options=options[:25])
        self.game_id = game_id
        self.engine = engine

    async def callback(self, interaction: discord.Interaction) -> None:
        value = self.values[0]
        voter_id = interaction.user.id

        session = await self.engine.get_session(self.game_id)
        if not session:
            return

        try:
            if value == "skip":
                await self.engine.register_vote(self.game_id, voter_id, None)
                # Store skip in session metadata
                skips = session.metadata.setdefault("skip_votes", set())
                skips.add(voter_id)
                await interaction.response.edit_message(content="You voted to Skip.", view=None)
            else:
                target_id = int(value)
                await self.engine.register_vote(self.game_id, voter_id, target_id)
                # Remove from skips
                skips = session.metadata.setdefault("skip_votes", set())
                skips.discard(voter_id)
                await interaction.response.edit_message(content=f"You voted for <@{target_id}>.", view=None)
        except RuntimeError:
            await interaction.response.edit_message(
                content=f"{get_emoji('cross')} Voting has already ended for this round — your vote wasn't counted.",
                view=None,
            )


class VerdictUISelectView(discord.ui.View):
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
        session = await self.engine.get_session(self.game_id)
        if not session:
            await interaction.response.send_message("This game is no longer active.", ephemeral=True)
            return

        user_id = interaction.user.id
        if user_id not in session.players:
            await interaction.response.send_message("You are not part of this game.", ephemeral=True)
            return

        player = session.players[user_id]
        if not player.alive:
            await interaction.response.send_message("Dead players cannot vote on verdict.", ephemeral=True)
            return
            
        defendant_id = session.metadata.get("defendant_id")
        if user_id == defendant_id:
            await interaction.response.send_message("You cannot vote on your own trial!", ephemeral=True)
            return

        if session.phase != GamePhase.EXECUTION:
            await interaction.response.send_message(
                f"{get_emoji('cross')} The trial has already ended — your verdict wasn't counted.",
                ephemeral=True,
            )
            return

        # If forced guilty (e.g. during a Retrial trial), they must vote guilty
        if session.metadata.get("forced_guilty"):
            decision = "guilty"

        # Hiromi Higuruma Retrial check
        if decision == "innocent" and player.role_key == "hiromi_higuruma":
            retrial_uses = player.metadata.setdefault("retrial_uses", 2)
            if retrial_uses > 0:
                view = discord.ui.View(timeout=30)
                btn_normal = discord.ui.Button(label="Vote Innocent Normally", style=discord.ButtonStyle.secondary)
                btn_retrial = discord.ui.Button(label=f"Trigger Retrial ({retrial_uses} left)", style=discord.ButtonStyle.danger)

                async def normal_cb(inter: discord.Interaction) -> None:
                    verdicts = session.metadata.setdefault("verdicts", {})
                    verdicts[inter.user.id] = "innocent"
                    await inter.response.edit_message(content="Registered normal Innocent verdict.", view=None)

                async def retrial_cb(inter: discord.Interaction) -> None:
                    async with self.engine._lock:
                        player.metadata["retrial_uses"] = retrial_uses - 1
                        session.metadata["retrial_triggered"] = True
                        session.metadata["retrial_defendant"] = defendant_id
                        session.metadata["retrial_by"] = inter.user.id
                    
                    mafia_channel = inter.channel
                    await self.engine.bot.message_queue.send(
                        mafia_channel,
                        f"⚖️ <@{inter.user.id}> (Hiromi Higuruma) has activated **Retrial** for this case!"
                    )
                    await inter.response.edit_message(content="⚖️ **Retrial Activated!**", view=None)

                btn_normal.callback = normal_cb
                btn_retrial.callback = retrial_cb
                view.add_item(btn_normal)
                view.add_item(btn_retrial)
                await interaction.response.send_message("Choose whether to trigger Retrial:", view=view, ephemeral=True)
                return

        verdicts = session.metadata.setdefault("verdicts", {})
        verdicts[user_id] = decision
        await interaction.response.send_message(f"You cast a verdict of **{decision.upper()}**.", ephemeral=True)
