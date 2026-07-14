from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import discord
from database.database import DatabaseManager
from database.models import GamePlayerRecord, GameRecord, MatchHistoryRecord
from game_manager import ActiveGameHandle
from utils.constants import GamePhase, GameState, RoleFaction
from utils.helpers import utcnow
from utils.roles import BaseRole, RoleContext, role_registry
import roles
from config import (
    get_emoji, get_death_message, get_inaction_message, get_event_image, get_role_image,
    GAME_CATEGORY_NAME_TEMPLATE, GAME_CHANNEL_NAME_TEMPLATE,
)

logger = logging.getLogger(__name__)


def get_rules_text() -> str:
    return (
        f"**{get_emoji('lobby')} Welcome to Anime Mafia Remastered!**\n\n"
        f"**{get_emoji('lobby')} Rules:**\n"
        "• Each player has been assigned a secret role via DM.\n"
        f"• There are three factions: **Hero (Town) {get_emoji('Hero')}**, **Villain (Mafia) {get_emoji('Villain')}**, and **Neutral {get_emoji('Neutral')}**.\n"
        "• The game alternates between **Night** and **Day** phases.\n\n"
        f"**{get_emoji('night')} Night Phase:**\n"
        "• Use the action button to select your target. Actions are private.\n"
        "• Mafia members can communicate via DMs (proxied to teammates).\n\n"
        f"**{get_emoji('day')} Day Phase:**\n"
        "• Discuss who you think the Mafia members are.\n"
        "• Vote to put someone on the stand for trial.\n"
        "• The defendant gets a chance to plead their case.\n"
        "• Cast your verdict: **Guilty** or **Innocent**.\n\n"
        f"**{get_emoji('victory')} Win Conditions:**\n"
        "• **Town** wins when all Mafia and hostile Neutrals are eliminated.\n"
        "• **Mafia** wins when they equal or outnumber non-Mafia players.\n"
        "• **Neutrals** each have their own unique win conditions.\n\n"
        f"**{get_emoji('warning')} Keep your role secret! Good luck!**"
    )


@dataclass(slots=True)
class GamePlayerState:
    user_id: int
    role_key: str | None = None
    faction: str | None = None
    alive: bool = True
    disconnected: bool = False
    vote_weight: int = 1
    votes_cast: int = 0
    night_actions_used: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class GameSession:
    game_handle: ActiveGameHandle
    player_ids: tuple[int, ...]
    min_players: int
    max_players: int
    created_at: datetime = field(default_factory=utcnow)
    state: GameState = GameState.LOBBY
    phase: GamePhase = GamePhase.JOINING
    players: dict[int, GamePlayerState] = field(default_factory=dict)
    role_history: dict[int, str] = field(default_factory=dict)
    votes: dict[int, int] = field(default_factory=dict)
    night_actions: dict[int, dict[str, Any]] = field(default_factory=dict)
    winner_faction: str | None = None
    draw_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class GameEngine:
    """Owns gameplay state and resolves roles and votes."""

    def __init__(self, database: DatabaseManager) -> None:
        self._database = database
        self._sessions: dict[str, GameSession] = {}
        self._lock = asyncio.Lock()
        self.bot: discord.Client | None = None

    async def create_session(
        self,
        game_handle: ActiveGameHandle,
        player_ids: tuple[int, ...],
        min_players: int,
        max_players: int,
    ) -> GameSession:
        async with self._lock:
            session = GameSession(
                game_handle=game_handle,
                player_ids=player_ids,
                min_players=min_players,
                max_players=max_players,
                players={user_id: GamePlayerState(user_id=user_id) for user_id in player_ids},
            )
            self._sessions[game_handle.game_id] = session
            logger.info("Created game session %s.", game_handle.game_id)
            return session

    async def get_session(self, game_id: str) -> GameSession | None:
        async with self._lock:
            return self._sessions.get(game_id)

    async def assign_roles(self, game_id: str, role_keys: tuple[str, ...]) -> dict[int, str]:
        async with self._lock:
            session = self._require_session(game_id)
            player_ids = list(session.players)
            if len(role_keys) < len(player_ids):
                raise ValueError("Not enough roles for all players.")

            for index, user_id in enumerate(player_ids):
                role_key = role_keys[index]
                role_cls = role_registry.get(role_key)
                session.players[user_id].role_key = role_key
                session.players[user_id].faction = role_cls.faction.value
                session.role_history[user_id] = role_key
                await self._database.upsert_game_player(
                    GamePlayerRecord(
                        game_id=game_id,
                        user_id=user_id,
                        guild_id=session.game_handle.guild_id,
                        character_key=role_key,
                        faction=role_cls.faction.value,
                    )
                )
            session.state = GameState.NIGHT
            session.phase = GamePhase.NIGHT_ACTIONS
            return dict(session.role_history)

    async def register_vote(self, game_id: str, voter_id: int, target_id: int | None) -> None:
        async with self._lock:
            session = self._require_session(game_id)
            if voter_id not in session.players:
                raise KeyError("Voter is not part of the session.")
            if session.phase != GamePhase.VOTING:
                raise RuntimeError("Voting has ended for this round.")
            if target_id is None:
                session.votes.pop(voter_id, None)
            else:
                session.votes[voter_id] = target_id
                session.players[voter_id].votes_cast += 1

    async def queue_night_action(
        self,
        game_id: str,
        user_id: int,
        payload: dict[str, Any],
    ) -> None:
        async with self._lock:
            session = self._require_session(game_id)
            if user_id not in session.players:
                raise KeyError("Actor is not part of the session.")
            if session.phase != GamePhase.NIGHT_ACTIONS:
                raise RuntimeError("Night actions have already been locked in for this round.")
            session.night_actions[user_id] = payload
            session.players[user_id].night_actions_used += 1

    async def resolve_night(self, game_id: str) -> None:
        async with self._lock:
            session = self._require_session(game_id)
            session.phase = GamePhase.DISCUSSION
            session.state = GameState.DAY
            session.night_actions.clear()

    async def resolve_day(self, game_id: str) -> None:
        async with self._lock:
            session = self._require_session(game_id)
            self._apply_votes(session)
            victory = self._evaluate_victory(session)
            if victory is not None:
                session.state = GameState.ENDED
                session.phase = GamePhase.CLEANUP
                session.winner_faction = victory
            else:
                session.phase = GamePhase.NIGHT_ACTIONS
                session.state = GameState.NIGHT

    async def eliminate_player(
        self,
        game_id: str,
        user_id: int,
        cause: str,
        *,
        death_message: str | None = None,
    ) -> None:
        async with self._lock:
            session = self._require_session(game_id)
            player = session.players[user_id]
            player.alive = False
            player.metadata["death_cause"] = cause

            if not death_message:
                guild = self.bot.get_guild(session.game_handle.guild_id) if self.bot else None
                member = guild.get_member(user_id) if guild else None
                mname = member.display_name if member else f"User {user_id}"
                death_message = get_death_message(cause, mname)

            player.metadata["death_message"] = death_message

            # Track this death so the day report picks it up (Only for night deaths)
            if session.state == GameState.NIGHT and cause != "declared_peace":
                dead_list = session.metadata.setdefault("dead_this_round", [])
                if user_id not in dead_list:
                    dead_list.append(user_id)

            await self._database.upsert_game_player(
                GamePlayerRecord(
                    game_id=game_id,
                    user_id=user_id,
                    guild_id=session.game_handle.guild_id,
                    character_key=player.role_key,
                    faction=player.faction,
                    alive=False,
                    disconnected=player.disconnected,
                    vote_weight=player.vote_weight,
                    eliminated_at=utcnow(),
                    death_cause=cause,
                )
            )

        # Broadcast day death or suicide immediately to the mafia channel (outside the lock)
        if session.state == GameState.DAY or cause == "declared_peace":
            if cause != "execution":
                mafia_ch_id = session.metadata.get("mafia_channel_id")
                if mafia_ch_id and self.bot:
                    ch = self.bot.get_channel(mafia_ch_id)
                    if ch:
                        announcement = f"{get_emoji('death')} {death_message}"
                        try:
                            await ch.send(announcement)
                        except Exception:
                            logger.exception("Failed to broadcast day death announcement")

        # Send death DM to the player (outside the lock)
        if self.bot:
            guild = self.bot.get_guild(session.game_handle.guild_id)
            if guild:
                member = guild.get_member(user_id)
                if member:
                    role_meta = roles.ROLES_METADATA.get(player.role_key or "", {})
                    role_display = role_meta.get("name", player.role_key or "Unknown")
                    try:
                        death_embed = discord.Embed(
                            title=f"{get_emoji('death')} You Have Died",
                            description=(
                                f"You were eliminated during the game.\n\n"
                                f"**Role:** {role_display}\n"
                                f"**Cause of Death:** {cause.replace('_', ' ').title()}\n\n"
                                f"You may continue spectating, but you can no longer act or vote."
                            ),
                            color=discord.Color.dark_grey()
                        )
                        await member.send(embed=death_embed)
                    except Exception:
                        logger.exception("Failed to send death DM to %s", user_id)

    async def mark_disconnected(self, game_id: str, user_id: int) -> None:
        async with self._lock:
            session = self._require_session(game_id)
            player = session.players[user_id]
            player.disconnected = True
            await self._database.mark_player_disconnected(game_id, user_id, session.game_handle.guild_id)

    async def end_game(self, game_id: str, winner_faction: str | None, draw_reason: str | None = None) -> MatchHistoryRecord:
        async with self._lock:
            session = self._require_session(game_id)
            session.state = GameState.ENDED
            session.phase = GamePhase.CLEANUP
            session.winner_faction = winner_faction
            session.draw_reason = draw_reason
            history = MatchHistoryRecord(
                game_id=game_id,
                guild_id=session.game_handle.guild_id,
                winner_faction=winner_faction,
                duration_seconds=int((utcnow() - session.created_at).total_seconds()),
                players=tuple(session.players),
                roles=dict(session.role_history),
                votes=dict(session.votes),
                deaths={
                    user_id: str(player.metadata.get("death_cause", "unknown"))
                    for user_id, player in session.players.items()
                    if not player.alive
                },
                mvp_user_id=None,
            )
            await self._database.upsert_game(
                GameRecord(
                    game_id=game_id,
                    guild_id=session.game_handle.guild_id,
                    channel_id=session.game_handle.channel_id,
                    host_id=session.game_handle.host_id,
                    state=session.state.value,
                    created_at=session.created_at,
                    ended_at=utcnow(),
                    winner_faction=winner_faction,
                    draw_reason=draw_reason,
                )
            )
            for user_id, player in session.players.items():
                await self._database.update_statistics_for_match(
                    user_id=user_id,
                    guild_id=session.game_handle.guild_id,
                    player_faction=player.faction,
                    winner_faction=winner_faction,
                )
            await self._database.save_match_history(history)
            self._sessions.pop(game_id, None)
            return history

    def _apply_votes(self, session: GameSession) -> None:
        if not session.votes:
            return
        tally: dict[int, int] = {}
        for target_id in session.votes.values():
            tally[target_id] = tally.get(target_id, 0) + 1
        if not tally:
            return
        target_id = max(tally, key=tally.get)
        if target_id in session.players:
            session.players[target_id].alive = False
            session.players[target_id].metadata["death_cause"] = "execution"

    def _evaluate_victory(self, session: GameSession) -> str | None:
        """Evaluate win conditions. Returns a faction name string or None."""
        alive_players = [p for p in session.players.values() if p.alive]
        if not alive_players:
            return "Draw"

        alive_factions = frozenset({p.faction for p in alive_players if p.faction is not None})

        # Check Neutral / Solo win conditions first
        for p in session.players.values():
            if not p.role_key:
                continue
            if not role_registry.contains(p.role_key):
                continue
            role_cls = role_registry.get(p.role_key)
            role_inst = role_cls()
            context = RoleContext(
                game_id=session.game_handle.game_id,
                guild_id=session.game_handle.guild_id,
                user_id=p.user_id,
                payload={"session": session}
            )
            # Check if this role satisfied its win condition
            if role_inst.win_condition_met(alive_factions, context):
                # Town/Mafia roles: their win is faction-based, not individual
                if role_cls.faction == RoleFaction.HERO:
                    # Don't return here; let the faction check below handle it
                    pass
                elif role_cls.faction == RoleFaction.VILLAIN:
                    # Don't return here; let the faction check below handle it
                    pass
                else:
                    # Neutral roles with special win conditions
                    # For lelouch or hisoka who win but game can continue
                    if p.role_key in ["hisoka", "lelouch_lamperouge"]:
                        p.metadata["has_won"] = True
                    else:
                        # Neutral solo winner (Gilgamesh apocalypse, Eren rumbling, etc.)
                        role_meta = roles.ROLES_METADATA.get(p.role_key, {})
                        return role_meta.get("name", p.role_key)

        # Standard Mafia / Town evaluation
        if alive_factions == {RoleFaction.HERO.value}:
            return RoleFaction.HERO.value
        if alive_factions == {RoleFaction.VILLAIN.value}:
            return RoleFaction.VILLAIN.value

        # If only Hero and Neutral remain (no Villain)
        if RoleFaction.VILLAIN.value not in alive_factions and RoleFaction.HERO.value in alive_factions:
            # Check if any remaining neutrals are hostile
            hostile_neutrals = [
                p for p in alive_players
                if p.faction == RoleFaction.NEUTRAL.value
                and p.role_key in ["eren_jaeger", "gilgamesh"]
                and not p.metadata.get("has_won")
            ]
            if not hostile_neutrals:
                return RoleFaction.HERO.value

        # If mafia equals or outnumbers town and no neutrals can kill them
        mafia_count = sum(1 for p in alive_players if p.faction == RoleFaction.VILLAIN.value)
        non_mafia_count = len(alive_players) - mafia_count
        if mafia_count > 0 and mafia_count >= non_mafia_count:
            # Check if Eren with Rumbling active can still stop them
            eren_threat = any(
                p.role_key == "eren_jaeger"
                and session.metadata.get("night_num", 1) >= 9
                and p.alive
                for p in alive_players
            )
            if not eren_threat:
                return RoleFaction.VILLAIN.value

        return None

    def _require_session(self, game_id: str) -> GameSession:
        try:
            return self._sessions[game_id]
        except KeyError as exc:
            raise KeyError(f"Game session '{game_id}' does not exist.") from exc

    # ---- Setup Phase (called from lobby_system start) ----------------------

    async def setup_game(self, game_id: str) -> None:
        """Phase 1: Assign roles, send DMs, then notify the host to start the game."""
        logger.info("Starting setup_game for game_id: %s", game_id)
        session = await self.get_session(game_id)
        if not session or not self.bot:
            return

        guild_id = session.game_handle.guild_id
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return

        # 1. Roles Distribution — category-balanced (see roles/balance.py):
        # guarantees Protective/Investigative/Council-Utility coverage for town
        # and exactly one Killing + one support role for mafia, instead of a
        # purely random draw.
        assigned_keys = roles.build_role_pool(len(session.player_ids))

        # Apply role assignments
        await self.assign_roles(game_id, tuple(assigned_keys))

        # Distribute swords for Gilgamesh
        num_swords = min(5, len(session.player_ids) // 3 + 1)
        sword_candidates = list(session.player_ids)
        gilgamesh_id = next((pid for pid, pstate in session.players.items() if pstate.role_key == "gilgamesh"), None)
        if gilgamesh_id and gilgamesh_id in sword_candidates:
            sword_candidates.remove(gilgamesh_id)
        swords_list = random.sample(sword_candidates, min(num_swords, len(sword_candidates)))
        session.metadata["gilgamesh_swords"] = swords_list

        # Send DMs to players
        mafia_members = [
            f"<@{pid}>" for pid, pstate in session.players.items()
            if pstate.faction == RoleFaction.VILLAIN.value
        ]
        mafia_list_str = ", ".join(mafia_members)

        for pid, pstate in session.players.items():
            member = guild.get_member(pid)
            if not member:
                continue

            role_meta = roles.ROLES_METADATA.get(pstate.role_key, {})
            faction_emoji = get_emoji(pstate.faction)
            role_emoji = get_emoji(pstate.role_key)

            embed = discord.Embed(
                title=f"{role_emoji} Your Role: {role_meta.get('name', 'Unknown')}",
                description=role_meta.get('description', ''),
                color=discord.Color.purple()
            )
            embed.add_field(name="Faction", value=f"{faction_emoji} **{pstate.faction}**", inline=True)
            embed.add_field(name="Win Condition", value=role_meta.get('win_condition', ''), inline=False)
            embed.add_field(name="Active Ability", value=role_meta.get('active_ability', 'None'), inline=False)
            embed.add_field(name="Passive Ability", value=role_meta.get('passive_ability', 'None'), inline=False)
            embed.set_footer(text="Keep your role secret!")
            role_image = get_role_image(pstate.role_key)
            if role_image:
                embed.set_thumbnail(url=role_image)

            try:
                await member.send(embed=embed)
                if pstate.faction == RoleFaction.VILLAIN.value and len(mafia_members) > 1:
                    await member.send(f"{get_emoji('group')} **Your Fellow Mafia Members:** {mafia_list_str}")
            except Exception:
                logger.exception("Failed to send DM to player %s", pid)

        # 2. Notify the host in the lobby channel with a "Start Game" button
        lobby_channel = self.bot.get_channel(session.game_handle.channel_id)
        if not isinstance(lobby_channel, discord.TextChannel):
            return

        host_id = session.game_handle.host_id
        from views.game_ui import StartGameView
        view = StartGameView(game_id, self)
        await lobby_channel.send(
            f"<@{host_id}>",
            embed=discord.Embed(
                title=f"{get_emoji('lobby')} Setup Complete!",
                description=(
                    "All roles have been assigned and sent to DMs.\n"
                    "Click **Start Game** below to create the game channel and begin the match!"
                ),
                color=discord.Color.green()
            ),
            view=view
        )
        logger.info("Setup complete for game_id: %s. Waiting for host to start.", game_id)

    # ---- Active Gameplay Loop Runner ---------------------------------------

    async def run_game_loop(self, game_id: str) -> None:
        """Phase 2: Creates the game channel, sends rules, then runs the day/night loop."""
        logger.info("Starting run_game_loop for game_id: %s", game_id)
        session = await self.get_session(game_id)
        if not session or not self.bot:
            return

        guild_id = session.game_handle.guild_id
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return

        # Fetch settings for this guild
        settings = await self._database.get_guild_settings(guild_id)

        # 1. Setup a temporary per-game category + #mafia channel. Both are
        # torn down together in end_game() once the match finishes.
        category_name = GAME_CATEGORY_NAME_TEMPLATE.format(game_id=game_id[:6])
        category = None
        try:
            category = await guild.create_category(category_name)
            session.metadata["mafia_category_id"] = category.id
        except Exception:
            logger.exception("Failed to create temporary Mafia match category.")

        # Create #mafia channel with proper permissions
        channel_name = GAME_CHANNEL_NAME_TEMPLATE.format(game_id=game_id[:6])
        mafia_channel = None
        try:
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(read_messages=False, send_messages=False),
                guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
            }
            # Add overwrites for each player to read but not send initially
            for pid in session.player_ids:
                member = guild.get_member(pid)
                if member:
                    overwrites[member] = discord.PermissionOverwrite(read_messages=True, send_messages=False)

            mafia_channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites
            )
            session.metadata["mafia_channel_id"] = mafia_channel.id
        except Exception:
            logger.exception("Failed to create mafia text channel.")
            # Fallback to the original lobby channel if creation failed
            lobby_chan = self.bot.get_channel(session.game_handle.channel_id)
            if isinstance(lobby_chan, discord.TextChannel):
                mafia_channel = lobby_chan
                session.metadata["mafia_channel_id"] = mafia_channel.id
            if category is not None:
                try:
                    await category.delete(reason="Mafia channel creation failed; cleaning up empty category.")
                except Exception:
                    pass
                session.metadata.pop("mafia_category_id", None)

        if not mafia_channel:
            return

        # 2. Ping all alive players so they can find the channel easily
        # 2. Ping all alive players so they can find the channel easily
        player_mentions = " ".join(f"<@{pid}>" for pid in session.player_ids)
        await mafia_channel.send(f"{get_emoji('lobby')} {player_mentions}")

        # 3. Send rules embed
        rules_embed = discord.Embed(
            title=f"{get_emoji('lobby')} Anime Mafia Remastered — Game Rules",
            description=get_rules_text(),
            color=discord.Color.purple()
        )
        rules_embed.set_footer(text="Roles have been sent to your DMs. Good luck!")
        rules_image = get_event_image("rules")
        if rules_image:
            rules_embed.set_image(url=rules_image)
        await mafia_channel.send(embed=rules_embed)

        # Wait a few seconds for players to read rules
        await asyncio.sleep(8)

        match_start_embed = discord.Embed(
            title=f"{get_emoji('lobby')} Match Starting!",
            description="The game begins now. Prepare yourselves!",
            color=discord.Color.dark_purple()
        )
        match_start_image = get_event_image("match_start")
        if match_start_image:
            match_start_embed.set_image(url=match_start_image)
        await mafia_channel.send(embed=match_start_embed)
        await asyncio.sleep(3)

        # 4. Game Cycles
        session.metadata["night_num"] = 0
        session.metadata["day_num"] = 0

        try:
            while session.state != GameState.ENDED:
                # Increment night
                session.metadata["night_num"] += 1
                night_num = session.metadata["night_num"]
                session.state = GameState.NIGHT
                session.phase = GamePhase.NIGHT_ACTIONS
                session.night_actions.clear()
                session.votes.clear()

                # Reset temporary per-night flags
                for pstate in session.players.values():
                    pstate.metadata.pop("roleblocked", None)

                # Mute all in #mafia for night
                await self._update_channel_mute(mafia_channel, session, mute=True)

                # Announce Night
                night_embed = discord.Embed(
                    title=f"{get_emoji('night')} Night {night_num}",
                    description=(
                        "Night has fallen. The town sleeps.\n"
                        "Players, check your action buttons below to make your moves."
                    ),
                    color=discord.Color.dark_blue()
                )
                night_image = get_event_image("night")
                if night_image:
                    night_embed.set_image(url=night_image)
                await mafia_channel.send(embed=night_embed)

                # Send action interface (button that opens ephemeral select menu)
                from views.game_ui import NightActionView
                action_view = NightActionView(game_id, self)
                night_msg = await mafia_channel.send(
                    f"{get_emoji('night')} **Night Action Phase**\nClick below to select your target for tonight. Actions are completely private.",
                    view=action_view
                )

                # Wait for Night timeout (or all actions completed)
                night_time = settings.get("night_duration", 45)
                for _ in range(0, night_time, 2):
                     if await self._all_active_submitted(session):
                         break
                     await asyncio.sleep(2)

                # Delete night actions prompt view
                try:
                    await night_msg.edit(content=f"{get_emoji('night')} **Night Action Phase Ended**", view=None)
                except Exception:
                    pass

                # Resolve Night
                await self._resolve_night_logic(session)

                # Check Victory
                winner = self._evaluate_victory(session)
                if winner:
                    session.metadata["day_num"] += 1
                    day_num = session.metadata["day_num"]

                    # Post the death report and the alive/dead roster as two
                    # separate embeds (they used to be one combined embed).
                    await self._send_death_and_status_embeds(
                        mafia_channel, guild, session,
                        title=f"Day {day_num} (Match Point)",
                    )

                    session.state = GameState.ENDED
                    session.winner_faction = winner
                    break

                # Transition to Day
                session.metadata["day_num"] += 1
                day_num = session.metadata["day_num"]
                session.state = GameState.DAY
                session.phase = GamePhase.DISCUSSION

                # Post the death report and the alive/dead roster as two
                # separate embeds (they used to be one combined embed).
                await self._send_death_and_status_embeds(
                    mafia_channel, guild, session,
                    title=f"Day {day_num}",
                )

                # Check if Gilgamesh has transformed and is preparing apocalypse
                for pid, pstate in list(session.players.items()):
                    if pstate.role_key == "gilgamesh" and pstate.metadata.get("transformed") and pstate.alive:
                        await mafia_channel.send(
                            embed=discord.Embed(
                                title=f"{get_emoji('warning')} Warning!",
                                description=(
                                    f"{get_emoji('zap')} **Gilgamesh has retrieved all of his swords and "
                                    f"transformed into the Horseman of Apocalypse!**\n"
                                    f"You have until the end of today to find and lynch him, "
                                    f"or he will unleash the Gates of Babylon and wipe everyone out!"
                                ),
                                color=discord.Color.red()
                            )
                        )

                # Unmute alive in #mafia for discussion
                await self._update_channel_mute(mafia_channel, session, mute=False)

                # Discussion Timer
                day_time = settings.get("day_duration", 40)
                await asyncio.sleep(day_time)

                # Day Voting
                session.phase = GamePhase.VOTING
                session.votes.clear()
                session.metadata.pop("skip_votes", None)

                # Send Vote Button
                from views.game_ui import VoteUISelectView
                vote_view = VoteUISelectView(game_id, self)
                vote_msg = await mafia_channel.send(
                    f"{get_emoji('vote')} **Voting Phase**\nClick below to select a target to vote onto the stand. You can also vote to skip.",
                    view=vote_view
                )

                vote_time = settings.get("vote_duration", 20)
                for _ in range(0, vote_time, 2):
                    alive_count_check = sum(1 for p in session.players.values() if p.alive)
                    total_votes = len(session.votes) + len(session.metadata.get("skip_votes", set()))
                    if total_votes >= alive_count_check:
                        break
                    await asyncio.sleep(2)

                # Remove vote view
                try:
                    await vote_msg.edit(content=f"{get_emoji('vote')} **Voting Phase Ended**", view=None)
                except Exception:
                    pass

                # Calculate Vote Results
                tally: dict[int, int] = {}
                for target_id in session.votes.values():
                    tally[target_id] = tally.get(target_id, 0) + 1

                # Skip calculation
                skip_count = len(session.metadata.get("skip_votes", set()))
                alive_count = sum(1 for p in session.players.values() if p.alive)
                majority = (alive_count // 2) + 1

                target_id = max(tally, key=tally.get) if tally else None
                max_votes = tally[target_id] if target_id else 0

                # Public or Anonymous settings
                anon = settings.get("anonymous_voting", True)
                vote_detail_lines = []
                for pid, target in session.votes.items():
                    voter_mem = guild.get_member(pid)
                    target_mem = guild.get_member(target)
                    vname = voter_mem.display_name if voter_mem else f"User {pid}"
                    tname = target_mem.display_name if target_mem else f"User {target}"
                    vote_detail_lines.append(f"• **{vname}** voted for **{tname}**")

                if not anon and vote_detail_lines:
                    await mafia_channel.send(
                        embed=discord.Embed(
                            title=f"{get_emoji('vote')} Vote Details",
                            description="\n".join(vote_detail_lines),
                            color=discord.Color.blue()
                        )
                    )

                # Check if majority voted a player on stand
                if target_id and max_votes >= majority and max_votes > skip_count:
                    defendant_mem = guild.get_member(target_id)
                    defendant_name = defendant_mem.display_name if defendant_mem else f"User {target_id}"

                    await mafia_channel.send(
                        embed=discord.Embed(
                            title=f"{get_emoji('trial')} Trial on Stand",
                            description=f"**{defendant_name}** has received majority votes and is on the stand!\nThey have 30 seconds to plea.",
                            color=discord.Color.orange()
                        )
                    )

                    # Mute all EXCEPT defendant (but do not mute the text channel during plea)
                    session.phase = GamePhase.TRIAL
                    session.metadata["defendant_id"] = target_id

                    # Plea Timer
                    plea_time = settings.get("plea_duration", 30)
                    await asyncio.sleep(plea_time)

                    # Verdict Phase
                    session.phase = GamePhase.EXECUTION
                    session.metadata["verdicts"] = {}

                    # Unmute everyone for verdict buttons
                    await self._update_channel_mute(mafia_channel, session, mute=False)

                    from views.game_ui import VerdictUISelectView
                    verdict_view = VerdictUISelectView(game_id, self)
                    verdict_msg = await mafia_channel.send(
                        f"{get_emoji('trial')} **Verdict Phase**\nCast your verdict on the defendant: Guilty or Innocent.",
                        view=verdict_view
                    )

                    verdict_time = settings.get("verdict_duration", 15)
                    await asyncio.sleep(verdict_time)

                    # Remove verdict view
                    try:
                        await verdict_msg.edit(content=f"{get_emoji('trial')} **Verdict Phase Closed**", view=None)
                    except Exception:
                        pass

                    # Tally verdicts
                    verdict_data = session.metadata.get("verdicts", {})
                    guilty_count = sum(1 for v in verdict_data.values() if v == "guilty")
                    inno_count = sum(1 for v in verdict_data.values() if v == "innocent")

                    # Verdict results output
                    verdict_report_lines = []
                    for pid, decision in verdict_data.items():
                        v_mem = guild.get_member(pid)
                        v_name = v_mem.display_name if v_mem else f"User {pid}"
                        verdict_report_lines.append(f"• **{v_name}**: {decision.upper()}")

                    if not anon and verdict_report_lines:
                        await mafia_channel.send(
                            embed=discord.Embed(
                                title=f"{get_emoji('trial')} Verdict Logs",
                                description="\n".join(verdict_report_lines),
                                color=discord.Color.blue()
                            )
                        )

                    await mafia_channel.send(
                        f"{get_emoji('trial')} Verdict Totals: **{guilty_count} Guilty** vs **{inno_count} Innocent**."
                    )

                    # If majority guilty, lynch them
                    if guilty_count > inno_count:
                        # Check Mahoraga adaptation (lynch immunity)
                        def_state = session.players[target_id]
                        if def_state.metadata.get("lynch_immune_day") == day_num:
                            await mafia_channel.send(f"{get_emoji('mahoraga')} **Mahoraga is immune to being lynched today!** The trial is dismissed.")
                        else:
                            # Check Lelouch Requiem Guess
                            if def_state.role_key == "lelouch_lamperouge" and def_state.metadata.get("declared_this_day"):
                                def_state.metadata["zero_requiem_win"] = True
                                await mafia_channel.send(f"{get_emoji('lelouch_lamperouge')} **Zero Requiem: Lelouch has achieved his goal!**")

                            # Check Hisoka Post-Mortem Nen lynch trigger
                            if def_state.role_key == "hisoka" and night_num <= 5:
                                def_state.metadata["post_mortem_win"] = True
                                def_state.metadata["revived"] = True
                                def_state.metadata["revived_days_left"] = 3
                                await mafia_channel.send(f"{get_emoji('hisoka')} **Hisoka was lynched! His Post-Mortem Nen will activate tomorrow...**")

                            # Perform elimination
                            role_meta = roles.ROLES_METADATA.get(def_state.role_key, {})
                            role_display = role_meta.get("name", def_state.role_key or "Unknown")
                            await self.eliminate_player(game_id, target_id, "execution")
                            await mafia_channel.send(
                                embed=discord.Embed(
                                    title=f"{get_emoji('death')} Execution",
                                    description=f"**{defendant_name}** was executed by the town! Their role was **{role_display}**.",
                                    color=discord.Color.red()
                                )
                            )
                    else:
                        await mafia_channel.send(f"{get_emoji('peace')} The town has voted to release the defendant.")

                    # Reset defendant metadata
                    session.metadata.pop("defendant_id", None)
                    session.metadata.pop("verdicts", None)

                else:
                    await mafia_channel.send(f"{get_emoji('peace')} Voting skipped. No one is on trial today.")

                # Check Victory after day phase
                winner = self._evaluate_victory(session)
                if winner:
                    session.state = GameState.ENDED
                    session.winner_faction = winner
                    break

        except Exception:
            logger.exception("Game loop error for game_id: %s", game_id)

        # 5. Cleanup & Game End
        logger.info("Match ended for game_id: %s", game_id)
        winner_faction = session.winner_faction or "Draw"
        history = await self.end_game(game_id, winner_faction)

        # Build the Victory embed and send it in the channel where the game was started from
        original_channel_id = session.game_handle.channel_id
        original_channel = self.bot.get_channel(original_channel_id) or mafia_channel
        await self._send_victory_embed(original_channel, guild, session, history, winner_faction)

        # Delete the mafia text channel after warning (but keep it if it is the original channel)
        if mafia_channel and mafia_channel.id != original_channel_id:
            try:
                # Send the final victory embed to the mafia channel too, before deleting it
                await self._send_victory_embed(mafia_channel, guild, session, history, winner_faction)
                await mafia_channel.send(f"{get_emoji('warning')} **This channel will be deleted in 20 seconds...**")
                await asyncio.sleep(20)
                await mafia_channel.delete(reason="Game ended.")
            except Exception:
                logger.exception("Failed to delete mafia channel %s", mafia_channel.id)

        # Delete the temporary per-game category that was created alongside
        # the channel — it's match-specific and should never be left orphaned.
        category_id = session.metadata.get("mafia_category_id")
        if category_id:
            category = guild.get_channel(category_id)
            if category is not None:
                try:
                    await category.delete(reason="Game ended.")
                except Exception:
                    logger.exception("Failed to delete temporary Mafia match category %s", category_id)

        # Remove active game from manager
        try:
            await self.bot.game_manager.remove_game(game_id)
        except Exception:
            logger.exception("Failed to remove game %s from manager.", game_id)

    async def _send_victory_embed(
        self,
        channel: discord.TextChannel,
        guild: discord.Guild,
        session: GameSession,
        history: MatchHistoryRecord,
        winner_faction: str,
    ) -> None:
        """Sends a detailed victory embed with Winners and Losers lists."""
        # Determine the display title for the winner
        faction_display_map = {
            RoleFaction.HERO.value: f"{get_emoji('victory')} Town (Hero) Wins!",
            RoleFaction.VILLAIN.value: f"{get_emoji('victory')} Mafia (Villain) Wins!",
            "Draw": f"{get_emoji('peace')} It's a Draw!",
        }
        # If it's a neutral solo winner, show their name
        title = faction_display_map.get(winner_faction, f"{get_emoji('victory')} {winner_faction} Wins!")

        victory_embed = discord.Embed(
            title=title,
            color=discord.Color.gold()
        )

        # Categorize players into winners and losers
        winners_lines = []
        losers_lines = []

        for pid, rkey in history.roles.items():
            member = guild.get_member(pid)
            name = member.display_name if member else f"User {pid}"
            role_meta = roles.ROLES_METADATA.get(rkey, {})
            role_display = role_meta.get("name", rkey)
            pstate = session.players.get(pid)
            status = "Alive" if (pstate and pstate.alive) else "Dead"

            player_line = f"• **{name}** — {role_display} ({status})"

            # Determine if this player is a winner
            is_winner = False
            if winner_faction == "Draw":
                is_winner = False  # No winners in a draw
            elif winner_faction == RoleFaction.HERO.value:
                if pstate and pstate.faction == RoleFaction.HERO.value:
                    is_winner = True
            elif winner_faction == RoleFaction.VILLAIN.value:
                if pstate and pstate.faction == RoleFaction.VILLAIN.value:
                    is_winner = True
            else:
                # Neutral solo winner: check by metadata or if they're that role
                if pstate and pstate.metadata.get("has_won"):
                    is_winner = True
                elif pstate and rkey and roles.ROLES_METADATA.get(rkey, {}).get("name") == winner_faction:
                    is_winner = True

            if is_winner:
                winners_lines.append(player_line)
            else:
                # Check if neutral players who individually won should also be listed
                if pstate and pstate.metadata.get("has_won"):
                    winners_lines.append(player_line)
                else:
                    losers_lines.append(player_line)

        if winners_lines:
            victory_embed.add_field(
                name=f"{get_emoji('victory')} Winners",
                value="\n".join(winners_lines),
                inline=False
            )
        if losers_lines:
            victory_embed.add_field(
                name=f"{get_emoji('death')} Losers",
                value="\n".join(losers_lines),
                inline=False
            )
        if winner_faction == "Draw":
            victory_embed.add_field(
                name=f"{get_emoji('chat')} All Players",
                value="\n".join(winners_lines + losers_lines) if (winners_lines or losers_lines) else "No players.",
                inline=False
            )

        # Add match duration
        minutes = history.duration_seconds // 60
        seconds = history.duration_seconds % 60
        victory_embed.set_footer(text=f"Match Duration: {minutes}m {seconds}s")

        image_key = {
            RoleFaction.HERO.value: "victory_hero",
            RoleFaction.VILLAIN.value: "victory_villain",
            "Draw": "draw",
        }.get(winner_faction, "victory_neutral")
        image_url = get_event_image(image_key)
        if image_url:
            victory_embed.set_image(url=image_url)

        await channel.send(embed=victory_embed)

    async def _send_death_and_status_embeds(
        self,
        channel: discord.TextChannel,
        guild: discord.Guild,
        session: GameSession,
        *,
        title: str,
    ) -> None:
        """Sends the night's death report and the alive/dead roster as two
        separate embeds (kept apart so each is easy to read on its own)."""
        dead_this_round = session.metadata.pop("dead_this_round", [])

        if dead_this_round:
            death_lines = []
            for dpid in dead_this_round:
                pstate = session.players.get(dpid)
                msg = pstate.metadata.get("death_message") if pstate else None
                if not msg:
                    member = guild.get_member(dpid)
                    mname = member.display_name if member else f"User {dpid}"
                    msg = get_death_message(pstate.metadata.get("death_cause") if pstate else None, mname)
                death_lines.append(f"{get_emoji('death')} {msg}")
            death_description = "\n".join(death_lines)
        else:
            death_description = f"{get_emoji('day')} No one died tonight. It was a quiet night."

        death_embed = discord.Embed(
            title=f"{get_emoji('death')} {title} — Death Report",
            description=death_description,
            color=discord.Color.dark_red() if dead_this_round else discord.Color.gold(),
        )
        death_image = get_event_image("death" if dead_this_round else "day")
        if death_image:
            death_embed.set_image(url=death_image)
        await channel.send(embed=death_embed)

        alive_list = []
        dead_list = []
        for pid, pstate in session.players.items():
            member = guild.get_member(pid)
            mname = member.display_name if member else f"User {pid}"
            if pstate.alive:
                alive_list.append(f"• {mname}")
            else:
                role_meta = roles.ROLES_METADATA.get(pstate.role_key or "", {})
                role_display = role_meta.get("name", pstate.role_key or "Unknown")
                dead_list.append(f"• ~~{mname}~~ ({role_display})")

        status_embed = discord.Embed(
            title=f"{get_emoji('group')} {title} — Player Status",
            color=discord.Color.blurple(),
        )
        status_embed.add_field(name=f"{get_emoji('alive')} Alive Players", value="\n".join(alive_list) if alive_list else "None", inline=True)
        status_embed.add_field(name=f"{get_emoji('death')} Dead Players", value="\n".join(dead_list) if dead_list else "None", inline=True)
        await channel.send(embed=status_embed)

    async def _all_active_submitted(self, session: GameSession) -> bool:
        """Checks if all alive players who have active night actions have submitted."""
        for pid, pstate in session.players.items():
            if not pstate.alive:
                continue
            if pstate.role_key in ["villager", "demon", "mahoraga"]:
                continue
            if pstate.metadata.get("roleblocked"):
                continue
            if pid not in session.night_actions:
                return False
        return True

    async def _resolve_night_logic(self, session: GameSession) -> None:
        """Processes all night actions based on priorities."""
        night_num = session.metadata.get("night_num", 1)
        guild = self.bot.get_guild(session.game_handle.guild_id) if (self.bot and session.game_handle) else None

        # Priority resolution queues
        session.metadata["pending_kills"] = {}
        session.metadata["healed_players"] = {}
        session.metadata["dead_this_round"] = []
        session.metadata["bungee_gum_links"] = {}

        # 1. Gather all actions
        action_list = []
        for actor_id, payload in list(session.night_actions.items()):
            actor_state = session.players.get(actor_id)
            if not actor_state or not actor_state.alive:
                continue

            # Check roleblock early
            if actor_state.metadata.get("roleblocked"):
                continue

            role_key = actor_state.role_key
            if not role_key:
                continue

            if not role_registry.contains(role_key):
                continue

            role_cls = role_registry.get(role_key)
            action_list.append((role_cls.priority, actor_id, payload, role_cls()))

        # Sort actions by priority (lower number runs first)
        action_list.sort(key=lambda x: x[0])

        # Execute actions in priority order
        for priority, actor_id, payload, role_inst in action_list:
            # Check if actor got roleblocked during the resolution
            actor_state = session.players.get(actor_id)
            if actor_state.metadata.get("roleblocked"):
                continue

            context = RoleContext(
                game_id=session.game_handle.game_id,
                guild_id=session.game_handle.guild_id,
                user_id=actor_id,
                target_id=payload.get("target_id"),
                payload={**payload, "session": session}
            )
            try:
                await role_inst.night_action(context)

                # Persist whatever the role wrote (log/result/error) back onto
                # the stored action payload so later feedback code can read it.
                session.night_actions[actor_id] = {k: v for k, v in context.payload.items() if k != "session"}

                # Check L / Ayanokoji scan results and deliver to their DMs
                if "result" in context.payload:
                    mafia_ch_id = session.metadata.get("mafia_channel_id")
                    if mafia_ch_id:
                        ch = self.bot.get_channel(mafia_ch_id)
                        if ch:
                            actor_member = ch.guild.get_member(actor_id)
                            if actor_member:
                                try:
                                    role_meta = roles.ROLES_METADATA.get(actor_state.role_key or "", {})
                                    role_display = role_meta.get("name", "Investigator")
                                    emoji = get_emoji(actor_state.role_key) or get_emoji("search")
                                    embed = discord.Embed(
                                        title=f"{emoji} {role_display} Intel",
                                        description=context.payload["result"],
                                        color=discord.Color.blue()
                                    )
                                    await actor_member.send(embed=embed)
                                except Exception:
                                    logger.exception("Failed to DM scan result to %s", actor_id)

                # Handle Muzan conversion: notify converted player + existing mafia
                if actor_state.role_key == "muzan_kibutsuji" and context.target_id:
                    target_pstate = session.players.get(context.target_id)
                    if target_pstate and target_pstate.faction == RoleFaction.VILLAIN.value:
                        await self._notify_muzan_conversion(
                            session, context.target_id, target_pstate
                        )

            except Exception:
                logger.exception("Failed to execute night action for user %s", actor_id)

        # 2. Check unpreventable Devil's Pen deaths
        death_queue = session.metadata.get("devils_pen_deaths", {})
        for pid_str, due_night in list(death_queue.items()):
            if night_num >= due_night:
                pid = int(pid_str)
                kills = session.metadata.setdefault("pending_kills", {})
                kills[pid] = kills.get(pid, []) + ["devils_pen_kill"]
                death_queue.pop(pid_str, None)

        # 3. Check Gilgamesh transformed apocalypse
        for pid, pstate in session.players.items():
            if pstate.role_key == "gilgamesh" and pstate.metadata.get("transformed") and pstate.alive:
                current_day = session.metadata.get("day_num", 1)
                trans_day = pstate.metadata.get("transformation_day", 1)
                if current_day > trans_day:
                    for target_pid, target_pstate in session.players.items():
                        if target_pid != pid and target_pstate.alive:
                            kills = session.metadata.setdefault("pending_kills", {})
                            kills[target_pid] = kills.get(target_pid, []) + ["gates_of_babylon"]

        # 4. Check Hisoka Bungee Gum matches
        bungee_links = session.metadata.get("bungee_gum_links", {})
        for hisoka_id, link_data in bungee_links.items():
            if not isinstance(link_data, (list, tuple)) or len(link_data) < 2:
                continue
            t1, t2 = link_data[0], link_data[1]
            t1_action = session.night_actions.get(t1, {})
            t2_action = session.night_actions.get(t2, {})

            t1_target = t1_action.get("target_id")
            t2_target = t2_action.get("target_id")

            if t1_target == t2 or t2_target == t1:
                hisoka_state = session.players.get(hisoka_id)
                if hisoka_state:
                    points = hisoka_state.metadata.get("bungee_points", 0) + 1
                    hisoka_state.metadata["bungee_points"] = points

                    mafia_ch_id = session.metadata.get("mafia_channel_id")
                    if mafia_ch_id:
                        ch = self.bot.get_channel(mafia_ch_id)
                        if ch:
                            hisoka_mem = ch.guild.get_member(hisoka_id)
                            if hisoka_mem:
                                try:
                                    await hisoka_mem.send(
                                        f"{get_emoji('target')} **Bungee Gum Success!** You correctly linked <@{t1}> and <@{t2}> "
                                        f"who visited one another! Points: **{points}/3**."
                                    )
                                except Exception:
                                    pass

        # 5. Apply Heals/Protections vs Attacks
        pending_kills = session.metadata.get("pending_kills", {})
        healed_players = session.metadata.get("healed_players", {})

        for target_id, sources in list(pending_kills.items()):
            target_state = session.players.get(target_id)
            if not target_state or not target_state.alive:
                continue

            # Check unpreventable kills (Devils Pen/Apocalypse)
            unpreventable_sources = ("devils_pen_kill", "gates_of_babylon")
            if any(src in unpreventable_sources for src in sources):
                target_mem = guild.get_member(target_id) if guild else None
                target_name = target_mem.display_name if target_mem else f"User {target_id}"
                cause_key = next(src for src in unpreventable_sources if src in sources)
                death_msg = get_death_message(cause_key, target_name)
                await self.eliminate_player(session.game_handle.game_id, target_id, "darkness", death_message=death_msg)
                continue

            # Check Doctor Tenma heal protection
            if target_id in healed_players:
                doc_id = healed_players.get(target_id + 1000000)
                if doc_id:
                    doc_state = session.players.get(doc_id)
                    if doc_state:
                        doc_saves = doc_state.metadata.get("saves_count", 0) + 1
                        doc_state.metadata["saves_count"] = doc_saves

                        mafia_ch_id = session.metadata.get("mafia_channel_id")
                        if mafia_ch_id:
                            ch = self.bot.get_channel(mafia_ch_id)
                            if ch:
                                doc_member = ch.guild.get_member(doc_id)
                                if doc_member:
                                    try:
                                        await doc_member.send(
                                            f"{get_emoji('shield')} **Compassion Successful!** You saved <@{target_id}> from an attack! "
                                            f"Saves: **{doc_saves}/3**."
                                        )
                                    except Exception:
                                        pass
                continue

            # Check Muzan Instant Regeneration
            if target_state.role_key == "muzan_kibutsuji" and target_state.metadata.get("muzan_regen"):
                target_state.metadata["muzan_regen"] = False
                mafia_ch_id = session.metadata.get("mafia_channel_id")
                if mafia_ch_id:
                    ch = self.bot.get_channel(mafia_ch_id)
                    if ch:
                        muzan_member = ch.guild.get_member(target_id)
                        if muzan_member:
                            try:
                                await muzan_member.send(
                                    f"{get_emoji('shield')} **Instant Regeneration Triggered!** You blocked an attack. Your passive is now disabled."
                                )
                            except Exception:
                                pass
                continue

            # Check Mahoraga adaptation
            if target_state.role_key == "mahoraga":
                attacker_ids = []
                for src in sources:
                    for actor_id, payload in session.night_actions.items():
                        if payload.get("target_id") == target_id:
                            attacker_ids.append(actor_id)

                # 75% survive
                if random.random() < 0.75:
                    mahoraga_attackers = target_state.metadata.setdefault("attackers", [])
                    mahoraga_attackers.extend(attacker_ids)

                    day_num = session.metadata.get("day_num", 1)
                    target_state.metadata["lynch_immune_day"] = day_num + 1

                    mafia_ch_id = session.metadata.get("mafia_channel_id")
                    if mafia_ch_id:
                        ch = self.bot.get_channel(mafia_ch_id)
                        if ch:
                            mahoraga_mem = ch.guild.get_member(target_id)
                            if mahoraga_mem:
                                try:
                                    await mahoraga_mem.send(
                                        f"{get_emoji('shield')} **Adaptation triggered!** You survived the attack, adapted to their roles, "
                                        "and gained lynch immunity for tomorrow!"
                                    )
                                except Exception:
                                    pass
                    continue

            # Eliminate player — pick the flavor line for whichever kill source landed
            # (config.DEATH_MESSAGES), so every role's kill gets real variety instead
            # of only the first few hardcoded sources.
            target_mem = guild.get_member(target_id) if guild else None
            target_name = target_mem.display_name if target_mem else f"User {target_id}"
            cause_key = sources[-1] if sources else None
            death_msg = get_death_message(cause_key, target_name)
            await self.eliminate_player(session.game_handle.game_id, target_id, "attack", death_message=death_msg)

        # Send outcome feedback DMs to EVERY alive player — not just ones who
        # submitted an action. Players with no action (or nothing eventful)
        # still get a short "quiet night" DM instead of silence.
        dead_tonight = session.metadata.get("dead_this_round", [])
        for actor_id, actor_state in session.players.items():
            if not actor_state.alive:
                continue

            member = guild.get_member(actor_id) if guild else None
            if not member:
                continue

            payload = session.night_actions.get(actor_id)

            # No action submitted at all tonight (no ability, chose not to act, etc.)
            if payload is None:
                try:
                    await member.send(f"{get_emoji('night')} {get_inaction_message()}")
                except Exception:
                    pass
                continue

            # Roleblocked feedback
            if actor_state.metadata.get("roleblocked"):
                try:
                    await member.send(f"{get_emoji('cross')} **Your action failed because you were roleblocked tonight!**")
                except Exception:
                    pass
                continue

            role_key = actor_state.role_key
            target_id = payload.get("target_id")

            # Doctor Tenma feedback
            if role_key == "doctor_tenma":
                action_type = payload.get("action_type")
                if action_type == "revive":
                    try:
                        await member.send(f"{get_emoji('doctor_tenma')} **You used your Scalpel of Justice to revive <@{target_id}> as a Default Villager!**")
                    except Exception:
                        pass
                else:
                    # check if the target was attacked
                    was_attacked = target_id in pending_kills
                    if not was_attacked:
                        try:
                            await member.send(f"{get_emoji('doctor_tenma')} **You decided to heal <@{target_id}> tonight. They were not attacked.**")
                        except Exception:
                            pass

            # Blackbeard feedback
            elif role_key == "blackbeard":
                action_type = payload.get("action_type")
                if action_type == "tremor":
                    try:
                        await member.send(f"{get_emoji('blackbeard')} **You triggered the Tremor Fruit earthquake! All non-mafia players have been roleblocked.**")
                    except Exception:
                        pass
                else:
                    try:
                        await member.send(f"{get_emoji('blackbeard')} **Your Darkness Logia roleblock successfully distracted <@{target_id}>!**")
                    except Exception:
                        pass

            # Light Yagami feedback
            elif role_key == "light_yagami":
                action_type = payload.get("action_type")
                if action_type == "devils_pen":
                    try:
                        await member.send(f"{get_emoji('light_yagami')} **You wrote <@{target_id}>'s name in the Death Note with the Devil's Pen. They will die in 3 nights.**")
                    except Exception:
                        pass
                else:
                    guessed_role = payload.get("guessed_role")
                    target_player = session.players.get(target_id)
                    if target_player and target_player.role_key == guessed_role:
                        try:
                            await member.send(f"{get_emoji('light_yagami')} **Kira's judgment! Your guess of <@{target_id}> as '{guessed_role}' was correct. They have been eliminated.**")
                        except Exception:
                            pass
                    else:
                        try:
                            await member.send(f"{get_emoji('light_yagami')} **Your guess of <@{target_id}> as '{guessed_role}' was incorrect. No elimination took place.**")
                        except Exception:
                            pass

            # Muzan Kibutsuji feedback
            elif role_key == "muzan_kibutsuji":
                target_player = session.players.get(target_id)
                # If target is now a demon faction member
                if target_player and target_player.faction == RoleFaction.VILLAIN.value:
                    role_meta = roles.ROLES_METADATA.get(target_player.role_key or "", {})
                    role_display = role_meta.get("name", "Demon")
                    try:
                        await member.send(f"{get_emoji('muzan_kibutsuji')} **Your Blood Demon Art successfully infected <@{target_id}>! They are now a {role_display} on your side.**")
                    except Exception:
                        pass
                else:
                    try:
                        await member.send(f"{get_emoji('muzan_kibutsuji')} **Your Blood Demon Art failed to infect <@{target_id}>.**")
                    except Exception:
                        pass

            # Makima feedback
            elif role_key == "makima":
                controlled_target = payload.get("controlled_vote_target")
                try:
                    await member.send(f"{get_emoji('makima')} **Your Control Order succeeded. <@{target_id}> will vote for <@{controlled_target}> next day!**")
                except Exception:
                    pass

            # Orochimaru feedback
            elif role_key == "orochimaru":
                try:
                    await member.send(f"{get_emoji('orochimaru')} **Your Reanimation Jutsu successfully revived <@{target_id}> for the night!**")
                except Exception:
                    pass

            # Hisoka Morow feedback
            elif role_key == "hisoka":
                if actor_state.metadata.get("revived"):
                    days_left = actor_state.metadata.get("revived_days_left", 0)
                    if days_left == 3:
                        try:
                            await member.send(f"🃏 **Post-Mortem Nen: You successfully roleblocked <@{target_id}> tonight!**")
                        except Exception:
                            pass
                    elif days_left == 1:
                        if target_id in dead_tonight:
                            try:
                                await member.send(f"🃏 **Post-Mortem Nen: You successfully assassinated <@{target_id}> tonight!**")
                            except Exception:
                                pass
                        else:
                            try:
                                await member.send(f"🃏 **Post-Mortem Nen: You attempted to assassinate <@{target_id}>, but the kill failed or was prevented.**")
                            except Exception:
                                pass
                else:
                    target1 = payload.get("target_id")
                    target2 = payload.get("controlled_vote_target")
                    bungee_links = session.metadata.get("bungee_gum_links", {})
                    points_updated = False
                    if bungee_links:
                        t1, t2 = target1, target2
                        t1_action = session.night_actions.get(t1, {})
                        t2_action = session.night_actions.get(t2, {})
                        if t1_action.get("target_id") == t2 or t2_action.get("target_id") == t1:
                            points_updated = True
                    if not points_updated:
                        try:
                            await member.send(f"🃏 **You linked <@{target1}> and <@{target2}> with Bungee Gum. They did not visit each other tonight.**")
                        except Exception:
                            pass

            # Eren Jaeger feedback
            elif role_key == "eren_jaeger":
                current_night = session.metadata.get("night_num", 1)
                if current_night >= 9:
                    if target_id in dead_tonight:
                        try:
                            await member.send(f"{get_emoji('eren_jaeger')} **Rumbling: You successfully crushed <@{target_id}>!**")
                        except Exception:
                            pass
                    else:
                        try:
                            await member.send(f"{get_emoji('eren_jaeger')} **Rumbling: You attempted to crush <@{target_id}>, but they survived.**")
                        except Exception:
                            pass

            # Lower Moon Demon feedback
            elif role_key == "lower_moon":
                try:
                    await member.send(f"{get_emoji('lower_moon')} **Lower Moon: Your distraction successfully roleblocked <@{target_id}>!**")
                except Exception:
                    pass

            # Upper Moon Demon feedback
            elif role_key == "upper_moon":
                if target_id in dead_tonight:
                    try:
                        await member.send(f"{get_emoji('upper_moon')} **Upper Moon: Your demon strike successfully assassinated <@{target_id}>!**")
                    except Exception:
                        pass
                else:
                    try:
                        await member.send(f"{get_emoji('upper_moon')} **Upper Moon: You attempted to attack <@{target_id}>, but they survived or were healed.**")
                    except Exception:
                        pass

            # Default Villain feedback
            elif role_key == "default_villain":
                if target_id in dead_tonight:
                    try:
                        await member.send(f"{get_emoji('default_villain')} **Default Villain: Your assassination successfully eliminated <@{target_id}>!**")
                    except Exception:
                        pass
                else:
                    try:
                        await member.send(f"{get_emoji('default_villain')} **Default Villain: You decided to assassinate <@{target_id}> tonight, but they were healed or survived.**")
                    except Exception:
                        pass

            # Fallback for any role without a dedicated feedback branch above
            # (e.g. new roles) — always uses the "result"/"log" the role's own
            # night_action already wrote to context.payload, or a generic line.
            else:
                fallback_msg = payload.get("result") or payload.get("log")
                if not fallback_msg and target_id:
                    fallback_msg = f"Your action targeting <@{target_id}> was carried out."
                if fallback_msg:
                    try:
                        await member.send(f"{get_emoji('night')} **{fallback_msg}**")
                    except Exception:
                        pass

        # Clear temp variables
        session.metadata.pop("pending_kills", None)
        session.metadata.pop("healed_players", None)
        session.metadata.pop("bungee_gum_links", None)

    async def _notify_muzan_conversion(
        self,
        session: GameSession,
        converted_id: int,
        converted_state: GamePlayerState,
    ) -> None:
        """DMs the newly-converted demon about their new role and notifies existing mafia."""
        if not self.bot:
            return

        guild = self.bot.get_guild(session.game_handle.guild_id)
        if not guild:
            return

        role_meta = roles.ROLES_METADATA.get(converted_state.role_key or "", {})
        role_display = role_meta.get("name", converted_state.role_key or "Demon")

        # Collect the mafia roster for the converted player
        mafia_mentions = [
            f"<@{pid}>" for pid, ps in session.players.items()
            if ps.faction == RoleFaction.VILLAIN.value and ps.alive
        ]
        mafia_list_str = ", ".join(mafia_mentions)

        # DM the converted player
        converted_member = guild.get_member(converted_id)
        if converted_member:
            try:
                convert_embed = discord.Embed(
                    title=f"{get_emoji('muzan_kibutsuji')} You Have Been Transformed!",
                    description=(
                        f"**Muzan Kibutsuji** has infected you with his blood!\n\n"
                        f"**Your New Role:** {role_display}\n"
                        f"**Your New Faction:** Villain (Mafia)\n\n"
                        f"You now win with the Mafia. Your old role and abilities are gone.\n"
                        f"You can now communicate with your fellow Mafia members by sending me DMs."
                    ),
                    color=discord.Color.dark_red()
                )
                if role_meta.get("active_ability"):
                    convert_embed.add_field(
                        name="Active Ability", value=role_meta["active_ability"], inline=False
                    )
                if role_meta.get("passive_ability"):
                    convert_embed.add_field(
                        name="Passive Ability", value=role_meta["passive_ability"], inline=False
                    )
                await converted_member.send(embed=convert_embed)
                await converted_member.send(f"{get_emoji('group')} **Your Fellow Mafia Members:** {mafia_list_str}")
            except Exception:
                logger.exception("Failed to DM converted player %s", converted_id)

        # Notify existing mafia about the new recruit
        for pid, pstate in session.players.items():
            if pid == converted_id:
                continue
            if pstate.faction != RoleFaction.VILLAIN.value or not pstate.alive:
                continue
            member = guild.get_member(pid)
            if member:
                try:
                    await member.send(
                        f"{get_emoji('muzan_kibutsuji')} **New Mafia Member!** <@{converted_id}> has been transformed into "
                        f"a **{role_display}** by Muzan Kibutsuji and is now on your side!"
                    )
                except Exception:
                    pass

    async def _update_channel_mute(self, channel: discord.TextChannel, session: GameSession, mute: bool) -> None:
        """Sets message-sending overrides on `#mafia` text channel."""
        try:
            for pid, pstate in session.players.items():
                member = channel.guild.get_member(pid)
                if not member:
                    continue

                if mute:
                    await channel.set_permissions(member, read_messages=True, send_messages=False)
                else:
                    if pstate.alive:
                        await channel.set_permissions(member, read_messages=True, send_messages=True)
                    else:
                        await channel.set_permissions(member, read_messages=True, send_messages=False)
        except Exception:
            logger.exception("Failed to update channel mute overrides.")

    async def _update_channel_mute_trial(self, channel: discord.TextChannel, session: GameSession, defendant_id: int) -> None:
        """Mutes everyone except the player currently defending on the stand."""
        try:
            for pid, pstate in session.players.items():
                member = channel.guild.get_member(pid)
                if not member:
                    continue

                if pid == defendant_id:
                    await channel.set_permissions(member, read_messages=True, send_messages=True)
                else:
                    await channel.set_permissions(member, read_messages=True, send_messages=False)
        except Exception:
            logger.exception("Failed to set trial mute overrides.")
