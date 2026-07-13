from __future__ import annotations

import discord
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from game_engine import GameSession, GameEngine

import asyncio
from config import get_emoji


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

        if player.metadata.get("roleblocked"):
            await interaction.response.send_message("You feel disoriented... You have been roleblocked and cannot act tonight!", ephemeral=True)
            return

        role_key = player.role_key
        if not role_key:
            await interaction.response.send_message("You do not have a role assigned.", ephemeral=True)
            return

        # Special check for roles that can't act or have custom UIs
        if role_key in ["villager", "demon", "mahoraga"]:
            await interaction.response.send_message("You do not have an active night ability.", ephemeral=True)
            return

        # Build target select menu
        # Targets are living players
        living_targets = [
            pid for pid, pstate in session.players.items()
            if pstate.alive
        ]

        if not living_targets:
            await interaction.response.send_message("No targets available.", ephemeral=True)
            return

        # Filter targets based on role rules
        options = []
        guild = interaction.guild
        for pid in living_targets:
            # Self-targeting check
            if pid == user_id:
                # Only Doctor Tenma can heal himself (implied by "heal anyone")
                if role_key != "doctor_tenma":
                    continue
            
            # Mafia cannot target fellow Mafia for hostile actions
            if player.faction == "Villain" and role_key in ["blackbeard", "light_yagami", "muzan_kibutsuji", "makima", "upper_moon"]:
                target_state = session.players[pid]
                if target_state.faction == "Villain":
                    continue

            member = guild.get_member(pid) if guild else None
            name = member.display_name if member else f"User {pid}"
            options.append(discord.SelectOption(label=name, value=str(pid)))

        if not options:
            await interaction.response.send_message("No eligible targets for your ability.", ephemeral=True)
            return

        # Handle roles with custom secondary selections
        view = discord.ui.View(timeout=120)
        
        if role_key == "light_yagami":
            # Guessing role or using Devils Pen
            select_type = LightYagamiActionSelect(self.game_id, self.engine, options)
            view.add_item(select_type)
            await interaction.response.send_message("Select which ability you wish to use:", view=view, ephemeral=True)
        elif role_key == "makima":
            # Needs to select target 1 and target 2
            select = MakimaSelect(self.game_id, self.engine, options)
            view.add_item(select)
            await interaction.response.send_message("Select the first target (whom you will control):", view=view, ephemeral=True)
        elif role_key == "hisoka" and not player.metadata.get("revived"):
            # Bungee gum: needs two targets
            select = HisokaBungeeSelect(self.game_id, self.engine, options)
            view.add_item(select)
            await interaction.response.send_message("Select the first target to link with Bungee Gum:", view=view, ephemeral=True)
        elif role_key == "doctor_tenma" and player.metadata.get("saves_count", 0) >= 3 and not player.metadata.get("revive_used"):
            # Can choose normal heal or Scalpel of Justice (revive)
            select = DoctorTenmaActionSelect(self.game_id, self.engine, options)
            view.add_item(select)
            await interaction.response.send_message("Select which ability you wish to use:", view=view, ephemeral=True)
        else:
            # Standard single target action
            from utils.roles import role_registry
            role_cls = role_registry.get(role_key) if role_registry.contains(role_key) else None
            prompt_text = getattr(role_cls, "action_prompt", "Select your target for tonight:") if role_cls else "Select your target for tonight:"
            if not prompt_text:
                prompt_text = "Select your target for tonight:"
            select = StandardActionSelect(self.game_id, self.engine, options)
            view.add_item(select)
            await interaction.response.send_message(prompt_text, view=view, ephemeral=True)

class StandardActionSelect(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Select a target...", options=options[:25])
        self.game_id = game_id
        self.engine = engine

    async def callback(self, interaction: discord.Interaction) -> None:
        target_id = int(self.values[0])
        await self.engine.queue_night_action(self.game_id, interaction.user.id, {"target_id": target_id})
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
        await self.engine.queue_night_action(self.game_id, interaction.user.id, {"target_id": target_id, "action_type": "heal"})
        await interaction.response.edit_message(content=f"Night action registered: Healing <@{target_id}>.", view=None)


class TenmaReviveSelect(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Select a dead mafia member...", options=options[:25])
        self.game_id = game_id
        self.engine = engine

    async def callback(self, interaction: discord.Interaction) -> None:
        target_id = int(self.values[0])
        await self.engine.queue_night_action(self.game_id, interaction.user.id, {"target_id": target_id, "action_type": "revive"})
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
        view = discord.ui.View(timeout=120)
        role_options = [
            discord.SelectOption(label="Doctor Tenma", value="doctor_tenma"),
            discord.SelectOption(label="Ayanokoji Kiyotaka", value="ayanokoji_kiyotaka"),
            discord.SelectOption(label="L", value="l"),
            discord.SelectOption(label="Hisoka", value="hisoka"),
            discord.SelectOption(label="Gilgamesh", value="gilgamesh"),
            discord.SelectOption(label="Lelouch Lamperouge", value="lelouch_lamperouge"),
            discord.SelectOption(label="Eren Jaeger", value="eren_jaeger"),
            discord.SelectOption(label="Mahoraga", value="mahoraga")
        ]
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
        await self.engine.queue_night_action(self.game_id, interaction.user.id, {
            "target_id": self.target_id,
            "action_type": "guess",
            "guessed_role": guessed_role
        })
        await interaction.response.edit_message(content=f"Death Note guess registered on <@{self.target_id}> for role '{guessed_role}'.", view=None)


class LightYagamiPenSelect(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Select player to write down...", options=options[:25])
        self.game_id = game_id
        self.engine = engine

    async def callback(self, interaction: discord.Interaction) -> None:
        target_id = int(self.values[0])
        await self.engine.queue_night_action(self.game_id, interaction.user.id, {
            "target_id": target_id,
            "action_type": "devils_pen"
        })
        await interaction.response.edit_message(content=f"Devil's Pen registered on <@{target_id}>.", view=None)


class MakimaSelect(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Select first target...", options=options[:25])
        self.game_id = game_id
        self.engine = engine
        self.target_options = options

    async def callback(self, interaction: discord.Interaction) -> None:
        target1 = int(self.values[0])
        # Select second target (can be anyone)
        options2 = [opt for opt in self.target_options if opt.value != str(target1)]
        view = discord.ui.View(timeout=120)
        select2 = MakimaVoteTargetSelect(self.game_id, self.engine, target1, options2)
        view.add_item(select2)
        await interaction.response.edit_message(content=f"Select the target <@{target1}> will be forced to vote for:", view=view)


class MakimaVoteTargetSelect(discord.ui.Select):
    def __init__(self, game_id: str, engine: GameEngine, target1: int, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Select vote target...", options=options[:25])
        self.game_id = game_id
        self.engine = engine
        self.target1 = target1

    async def callback(self, interaction: discord.Interaction) -> None:
        target2 = int(self.values[0])
        await self.engine.queue_night_action(self.game_id, interaction.user.id, {
            "target_id": self.target1,
            "controlled_vote_target": target2
        })
        await interaction.response.edit_message(content=f"Control Devil registered: Redirection of <@{self.target1}> to vote for <@{target2}>.", view=None)


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
        await self.engine.queue_night_action(self.game_id, interaction.user.id, {
            "target_id": self.target1,
            "controlled_vote_target": target2
        })
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

        # Prepare target options: living players and Skip Vote option
        options = [discord.SelectOption(label="Skip Vote", value="skip")]
        guild = interaction.guild
        for pid, pstate in session.players.items():
            if pstate.alive:
                member = guild.get_member(pid) if guild else None
                name = member.display_name if member else f"User {pid}"
                options.append(discord.SelectOption(label=name, value=str(pid)))

        view = discord.ui.View(timeout=60)
        select = VoteSelector(self.game_id, self.engine, options)
        view.add_item(select)
        await interaction.response.send_message("Select a target to vote for (or Skip):", view=view, ephemeral=True)


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

        verdicts = session.metadata.setdefault("verdicts", {})
        verdicts[user_id] = decision
        await interaction.response.send_message(f"You cast a verdict of **{decision.upper()}**.", ephemeral=True)
