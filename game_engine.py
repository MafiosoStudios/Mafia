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
from utils.roles import BaseRole, RoleContext, role_registry, NightAction
import roles
from ui import build_v2_layout
from config import (
    get_emoji, get_death_message, get_inaction_message, get_event_image, get_role_image,
    GAME_CATEGORY_NAME_TEMPLATE, GAME_CHANNEL_NAME_TEMPLATE,
)

logger = logging.getLogger(__name__)



def get_rules_text() -> str:
    return (
        f"** WELCOME TO MAFIOSO REMASTERED!**\n\n"
        f"**THE PROTOCOLS:**\n"
        "• Your secret identity has been sent directly to your DMs. Keep it secret, or else...\n"
        f"• The Factions: **Town (Protagonists) {get_emoji('Hero')}**, **Mafia (Villains) {get_emoji('Villain')}**, and **Neutrals (Wildcards) {get_emoji('Neutral')}**.\n"
        "• We cycle between **Night** phase, where you all can use your abilities, and **Day** phase, where you can discuss and vote a potential antagonist.\n\n"
        f"**{get_emoji('night')} THE NIGHT:**\n"
        "• Execute your abilities in secret via the action buttons. Can you pull off a big brain play? Or just be yet another passerby.\n"
        "• The Villains share a collective mind and can discuss plans in their dark corner where they can communicate with each other.\n\n"
        f"**{get_emoji('day')} THE DAY:**\n"
        "• Point fingers, accuse your friends, and vote to drag someone onto the stand!\n"
        "• The defendant has a brief moment to beg for their life (Plea Phase).\n"
        "• Everyone votes **Guilty** or **Innocent** to decide their fate.\n\n"
        f"**{get_emoji('victory')} THE ENDGAME:**\n"
        "• **Protagonists** win when all evil is erased from this server.\n"
        "• **Villains** win when they achieve numerical superiority and seize control.\n"
        "• **Neutrals**... well, they just want to watch the world burn. Check your specific win condition.\n\n"
        f"**{get_emoji('warning')} Trust no one. Let the mind games begin!**"
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

    @property
    def night_num(self) -> int:
        return self.metadata.get("night_num", 0)

    @night_num.setter
    def night_num(self, value: int) -> None:
        self.metadata["night_num"] = value

    @property
    def day_num(self) -> int:
        return self.metadata.get("day_num", 0)

    @day_num.setter
    def day_num(self, value: int) -> None:
        self.metadata["day_num"] = value


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

    async def save_session_state(self, session: GameSession) -> None:
        """Serializes and saves the current game session state to the database."""
        try:
            serialized = serialize_session(session)
            await self._database.save_active_game_state(session.game_handle.game_id, serialized)
        except Exception:
            logger.exception("Failed to save active game state for %s", session.game_handle.game_id)

    async def get_session(self, game_id: str) -> GameSession | None:
        async with self._lock:
            return self._sessions.get(game_id)

    async def assign_roles(self, game_id: str, role_keys: tuple[str, ...]) -> dict[int, str]:
        async with self._lock:
            session = self._require_session(game_id)
            player_ids = list(session.players)
            if len(role_keys) < len(player_ids):
                raise ValueError("Not enough roles for all players.")

            available_roles = list(role_keys)
            assignments = {}

            # 1. Fetch favorite characters for all players
            fav_characters = {}
            import roles
            for user_id in player_ids:
                prof = await self._database.get_player_profile(user_id, session.game_handle.guild_id)
                if prof and prof.favorite_character:
                    cleaned_fav = prof.favorite_character.lower().strip().replace(" ", "_")
                    for rkey in roles.ROLES_METADATA:
                        if rkey == cleaned_fav or roles.ROLES_METADATA[rkey].get("name", "").lower() == prof.favorite_character.lower():
                            fav_characters[user_id] = rkey
                            break

            # 2. Process players in a random order to apply the 2% bonus chance fairly
            import random
            shuffled_players = list(player_ids)
            random.shuffle(shuffled_players)

            assigned_players = set()
            for user_id in shuffled_players:
                fav_role = fav_characters.get(user_id)
                if fav_role and fav_role in available_roles:
                    if random.random() < 0.02:
                        assignments[user_id] = fav_role
                        available_roles.remove(fav_role)
                        assigned_players.add(user_id)
                        logger.info("Player %s won the 2%% bonus chance to get their favorite role: %s", user_id, fav_role)

            # 3. Assign remaining roles randomly to players who didn't win the bonus
            remaining_players = [pid for pid in player_ids if pid not in assigned_players]
            random.shuffle(available_roles)
            for index, user_id in enumerate(remaining_players):
                role_key = available_roles[index]
                assignments[user_id] = role_key

            # 4. Save assignments to session and database
            for user_id, role_key in assignments.items():
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
            await self.save_session_state(session)
            return dict(session.role_history)

    async def register_vote(self, game_id: str, voter_id: int, target_id: int | None) -> None:
        async with self._lock:
            session = self._require_session(game_id)
            if voter_id not in session.players:
                raise KeyError("Voter is not part of the session.")
            if session.phase != GamePhase.VOTING:
                raise RuntimeError("Voting has ended for this round.")

            # Wounded and Exhausted check
            voter_p = session.players.get(voter_id)
            if voter_p:
                day_num = session.metadata.get("day_num", 1)
                if voter_p.metadata.get("wounded_until_day") == day_num:
                    raise ValueError("You are Wounded and cannot vote today.")
                if voter_p.metadata.get("exhausted_until_day") == day_num:
                    raise ValueError("You are Exhausted and cannot vote today.")

            if target_id is None:
                session.votes.pop(voter_id, None)
            else:
                session.votes[voter_id] = target_id
                session.players[voter_id].votes_cast += 1
            await self.save_session_state(session)

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

            actor_p = session.players.get(user_id)
            if actor_p and actor_p.role_key:
                night_num = session.metadata.get("night_num", 1)
                
                # Wounded and Exhausted check
                if actor_p.metadata.get("wounded_until_night") == night_num:
                    raise ValueError("You are Wounded and cannot use abilities tonight.")
                if actor_p.metadata.get("exhausted_until_night") == night_num:
                    raise ValueError("You are Exhausted and cannot use abilities tonight.")

                # 1. Teammate validation: Mafia cannot target living Mafia teammates
                target_id = payload.get("target_id")
                controlled_vote_target = payload.get("controlled_vote_target")
                if actor_p.faction == RoleFaction.VILLAIN.value:
                    for tid in [target_id, controlled_vote_target]:
                        if tid is not None:
                            target_p = session.players.get(tid)
                            if target_p and target_p.faction == RoleFaction.VILLAIN.value and target_p.alive:
                                raise ValueError("You cannot target your own Mafia teammates.")

                # 2. Cooldown/night-restriction checks
                role_cls = role_registry.get(actor_p.role_key)
                role_inst = role_cls()
                
                action_index = payload.get("action_index")
                if action_index is not None and action_index < len(role_inst.abilities):
                    ability = role_inst.abilities[action_index]
                    if isinstance(ability, NightAction):
                        if actor_p.role_key == "doctor_tenma" and ability.name == "Emergency Surgery":
                            targets = payload.get("targets")
                            if targets:
                                last_pair = actor_p.metadata.get("tenma_last_pair")
                                if last_pair and set(targets) == set(last_pair):
                                    raise ValueError("You cannot pick the same 2 people as you did last night.")
                                    
                        can_use, reason = ability.can_use(session, actor_p)
                        if not can_use:
                            raise ValueError(reason or "This ability is currently unavailable.")
                else:
                    can_act, reason = role_inst.can_act_tonight(session, actor_p)
                    if not can_act:
                        raise ValueError(reason or "Your ability is currently unavailable.")

            session.night_actions[user_id] = payload
            session.players[user_id].night_actions_used += 1
            await self.save_session_state(session)

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
        killer_id: int | None = None,
    ) -> None:
        async with self._lock:
            session = self._require_session(game_id)
            player = session.players[user_id]
            player.alive = False
            player.metadata["death_cause"] = cause
            if killer_id:
                player.metadata["killer_id"] = killer_id

            # Clear Bungee Gum bond if one of the linked players dies
            bond = session.metadata.get("bungee_gum_bond")
            if bond and user_id in bond:
                session.metadata.pop("bungee_gum_bond", None)

            # Tōsen — release prisoner if Tōsen dies
            if player.role_key == "tosen":
                prisoner_id = player.metadata.get("detained_player_id")
                if prisoner_id:
                    prisoner = session.players.get(prisoner_id)
                    if prisoner:
                        prisoner.metadata.pop("detained", None)
                player.metadata.pop("detained_player_id", None)

            # Clear detained flag if the detained player dies inside Bankai
            if player.metadata.get("detained"):
                for pid, pstate in session.players.items():
                    if pstate.role_key == "tosen" and pstate.alive:
                        if pstate.metadata.get("detained_player_id") == user_id:
                            pstate.metadata["detained_player_id"] = None
                player.metadata.pop("detained", None)

            if cause == "frieza_kill":
                for pid, pstate in session.players.items():
                    if pstate.role_key == "frieza" and pstate.alive:
                        action = session.night_actions.get(pid)
                        if action and action.get("target_id") == user_id:
                            kills_count = pstate.metadata.get("frieza_kills", 0) + 1
                            pstate.metadata["frieza_kills"] = kills_count
                            if kills_count == 3 and not pstate.metadata.get("golden_frieza"):
                                pstate.metadata["golden_frieza"] = True
                                async def notify_transformation(eng=self, s=session, f_id=pid):
                                    guild = eng.bot.get_guild(s.game_handle.guild_id) if eng.bot else None
                                    if guild:
                                        mafia_ids = [k for k, p in s.players.items() if p.faction == RoleFaction.VILLAIN.value]
                                        msg = (
                                            "🌟 **Frieza Has Transformed!**\n"
                                            "Frieza has personally eliminated 3 players and evolved into **Golden Frieza**!\n"
                                            f"{get_emoji('meteor')} *Death Beam now ignores Basic Protection.*\n"
                                            f"{get_emoji('shield')} *Frieza is immune to Roleblocks and cannot be redirected.*"
                                        )
                                        for mid in mafia_ids:
                                            member = guild.get_member(mid)
                                            if member:
                                                try:
                                                    eng.bot.message_queue.send(member, msg)
                                                except Exception:
                                                    pass
                                asyncio.create_task(notify_transformation())

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

            # Set dead player overrides once so they cannot talk even when day un-mutes default_role
            mafia_channel_id = session.metadata.get("mafia_channel_id")
            if mafia_channel_id and self.bot:
                guild = self.bot.get_guild(session.game_handle.guild_id)
                if guild:
                    member = guild.get_member(user_id)
                    mafia_channel = guild.get_channel(mafia_channel_id)
                    if member and mafia_channel:
                        try:
                            import config
                            if user_id in config.ADMIN_IDS:
                                await mafia_channel.set_permissions(member, read_messages=True, send_messages=True)
                            else:
                                await mafia_channel.set_permissions(member, read_messages=True, send_messages=False)
                        except Exception:
                            pass

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
            await self.save_session_state(session)

        # Broadcast day death or suicide immediately to the mafia channel (outside the lock)
        if session.state == GameState.DAY or cause == "declared_peace":
            if cause != "execution":
                mafia_ch_id = session.metadata.get("mafia_channel_id")
                if mafia_ch_id and self.bot:
                    ch = self.bot.get_channel(mafia_ch_id)
                    if ch:
                        announcement = f"{get_emoji('death')} {death_message}"
                        try:
                            await self.bot.message_queue.send(ch, announcement)
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
                        death_view = build_v2_layout(
                            title=f"{get_emoji('death')} You Have Died",
                            description=(
                                f"You were eliminated during the game.\n\n"
                                f"**Role:** {role_display}\n"
                                f"**Cause of Death:** {cause.replace('_', ' ').title()}\n\n"
                                f"You may continue spectating, but you can no longer act or vote."
                            ),
                            color=discord.Color.dark_grey(),
                        )
                        self.bot.message_queue.send(member, view=death_view)
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
            # Resolve Bungee Gum Win Sharing
            bond = session.metadata.get("bungee_gum_bond")
            if bond:
                p1_id, p2_id = bond
                p1_state = session.players.get(p1_id)
                p2_state = session.players.get(p2_id)
                if p1_state and p2_state and p1_state.alive and p2_state.alive:
                    def player_wins_base(p_state):
                        if winner_faction == "Draw":
                            return False
                        if winner_faction == RoleFaction.HERO.value:
                            return p_state.faction == RoleFaction.HERO.value
                        if winner_faction == RoleFaction.VILLAIN.value:
                            return p_state.faction == RoleFaction.VILLAIN.value
                        if p_state.metadata.get("has_won"):
                            return True
                        r_key = p_state.role_key
                        if r_key and roles.ROLES_METADATA.get(r_key, {}).get("name") == winner_faction:
                            return True
                        return False
                    
                    if player_wins_base(p1_state) or player_wins_base(p2_state):
                        p1_state.metadata["has_won"] = True
                        p2_state.metadata["has_won"] = True

            for user_id, player in session.players.items():
                is_winner = False
                if winner_faction == "Draw":
                    is_winner = False
                elif winner_faction == RoleFaction.HERO.value:
                    if player.faction == RoleFaction.HERO.value:
                        is_winner = True
                elif winner_faction == RoleFaction.VILLAIN.value:
                    if player.faction == RoleFaction.VILLAIN.value:
                        is_winner = True
                else:
                    if player.metadata.get("has_won"):
                        is_winner = True
                    r_key = player.role_key
                    if r_key and roles.ROLES_METADATA.get(r_key, {}).get("name") == winner_faction:
                        is_winner = True

                if player.metadata.get("has_won"):
                    is_winner = True

                await self._database.update_statistics_for_match(
                    user_id=user_id,
                    guild_id=session.game_handle.guild_id,
                    player_faction=player.faction,
                    winner_faction=winner_faction,
                    has_won=is_winner,
                )
            await self._database.save_match_history(history)
            await self._database.clear_active_game_state(game_id)
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
                    # For hisoka who wins but game can continue
                    if p.role_key in ["hisoka"]:
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
        # purely random draw. Roles disabled via /roledisable are excluded.
        disabled_roles: list[str] = []
        if self._database is not None:
            try:
                disabled_roles = await self._database.get_disabled_roles(guild_id)
            except Exception:
                logger.exception("Failed to load disabled roles for guild %s; proceeding with full roster.", guild_id)
        assigned_keys = roles.build_role_pool(len(session.player_ids), disabled_roles=disabled_roles)

        # Apply role assignments
        await self.assign_roles(game_id, tuple(assigned_keys))

        # Distribute swords and do any other role-specific setups modularly
        for pid, pstate in session.players.items():
            role_cls = role_registry.get(pstate.role_key)
            role_inst = role_cls()
            await role_inst.on_game_start(session, pid)

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
            # Map faction to Protagonist/Antagonist for user display
            display_faction = "Protagonist" if pstate.faction == "Hero" else ("Antagonist" if pstate.faction == "Villain" else pstate.faction)
            faction_emoji = get_emoji(display_faction)
            role_emoji = get_emoji(pstate.role_key)

            # Faction-based colors: Green for Town (Hero), Red for Mafia (Villain), White for Neutral
            color_map = {
                "Hero": discord.Color.green(),
                "Town": discord.Color.green(),
                "Villain": discord.Color.red(),
                "Mafia": discord.Color.red(),
                "Neutral": discord.Color.from_rgb(255, 255, 255)
            }
            embed_color = color_map.get(pstate.faction, discord.Color.purple())

            role_emoji_prefix = f"{role_emoji} " if role_emoji else ""
            role_title = f"Your Role: {role_emoji_prefix}{role_meta.get('name', 'Unknown')}"
            
            from utils.helpers import get_emoji_url
            emoji_url = get_emoji_url(role_emoji) if role_emoji else None

            desc_parts = [role_meta.get('description', '')]
            desc_parts.append(f"• **Faction:** {faction_emoji} **{display_faction}**")
            desc_parts.append(f"• **Win Condition:** {role_meta.get('win_condition', '')}")

            active_ability = role_meta.get('active_ability', 'None')
            if "Max Ability:" in active_ability:
                parts = active_ability.split("Max Ability:")
                abilities = [parts[0].strip(), "Max Ability: " + parts[1].strip()]
            elif "Max Ability. " in active_ability:
                parts = active_ability.split("Max Ability. ")
                abilities = [parts[0].strip(), "Max Ability: " + parts[1].strip()]
            else:
                abilities = [a.strip() for a in active_ability.split(" / ") if a.strip()]

            if not abilities or (len(abilities) == 1 and not abilities[0]):
                desc_parts.append("• **Active Ability:** None")
            elif len(abilities) == 1:
                desc_parts.append(f"• **Active Ability:** {abilities[0]}")
            else:
                for idx, ability in enumerate(abilities, 1):
                    desc_parts.append(f"• **Active Ability {idx}:** {ability}")

            passive_ability = role_meta.get('passive_ability', 'None').strip()
            if passive_ability and passive_ability.lower() != "none":
                desc_parts.append(f"• **Passive Ability:** {passive_ability}")

            footer_text = role_meta.get("footer", "Keep your role secret!")

            from config import ROLE_IMAGES
            big_image = ROLE_IMAGES.get(pstate.role_key) or role_meta.get("image_url")

            role_dm_layout = build_v2_layout(
                title=role_title,
                description="\n\n".join(desc_parts),
                color=embed_color,
                thumbnail_url=emoji_url,
                image_url=big_image,
                footer_text=footer_text,
            )

            try:
                self.bot.message_queue.send(member, view=role_dm_layout)
                if pstate.faction == RoleFaction.VILLAIN.value and len(mafia_members) > 1:
                    self.bot.message_queue.send(member, f"{get_emoji('group')} **Your Fellow Antagonists:** {mafia_list_str}")
            except Exception:
                logger.exception("Failed to send DM to player %s", pid)

        # 2. Notify the host in the lobby channel with a "Start Game" button
        lobby_channel = self.bot.get_channel(session.game_handle.channel_id)
        if not isinstance(lobby_channel, discord.TextChannel):
            return

        host_id = session.game_handle.host_id
        from views.game_ui import StartGameView
        view = StartGameView(game_id, self)
        setup_view = build_v2_layout(
            title="Setup Complete!",
            description=(
                "All roles have been assigned and sent to DMs.\n"
                "Click **Start Game** below to create the game channel and begin the match!"
            ),
            color=discord.Color.green(),
            view=view,
        )
        await self.bot.message_queue.send(
            lobby_channel,
            f"<@{host_id}>",
            view=setup_view
        )

        logger.info("Setup complete for game_id: %s. Waiting for host to start.", game_id)

    async def run_game_loop_from_resume(self, game_id: str) -> None:
        """Starts the run_game_loop task for a deserialized game session."""
        asyncio.create_task(self.run_game_loop(game_id))

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

        # Check if this is a resumption
        resuming_phase = session.phase if session.phase not in (GamePhase.JOINING, GamePhase.CLEANUP) else None
        if resuming_phase and not session.metadata.get("mafia_channel_id"):
            resuming_phase = None

        if resuming_phase:
            logger.info("Resuming active game loop from phase: %s", resuming_phase)
            mafia_channel = self.bot.get_channel(session.metadata.get("mafia_channel_id"))
            if not mafia_channel:
                try:
                    mafia_channel = await self.bot.fetch_channel(session.metadata.get("mafia_channel_id"))
                except Exception:
                    pass
            if not mafia_channel:
                logger.error("Mafia channel not found on resume, aborting.")
                return
        else:
            # 1. Setup mafia channel inside the category of the start command
            lobby_chan = self.bot.get_channel(session.game_handle.channel_id)
            if not lobby_chan:
                try:
                    lobby_chan = await self.bot.fetch_channel(session.game_handle.channel_id)
                except Exception:
                    pass
            
            category = lobby_chan.category if (lobby_chan and hasattr(lobby_chan, "category")) else None

            # Create #mafia channel with proper permissions
            channel_name = "mafia"
            mafia_channel = None
            try:
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(read_messages=False, send_messages=False),
                    guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
                }
                # Add overwrites for each player to read but not send initially
                for pid in session.player_ids:
                    member = guild.get_member(pid)
                    if not member:
                        try:
                            member = await guild.fetch_member(pid)
                        except discord.NotFound:
                            logger.warning("Player %s not found in guild %s, skipping channel overwrite.", pid, guild_id)
                            continue
                    overwrites[member] = discord.PermissionOverwrite(read_messages=True, send_messages=None)

                import config
                for admin_id in config.ADMIN_IDS:
                    admin_member = guild.get_member(admin_id)
                    if not admin_member:
                        try:
                            admin_member = await guild.fetch_member(admin_id)
                        except discord.HTTPException:
                            continue
                    if admin_member:
                        overwrites[admin_member] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

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

            if not mafia_channel:
                return

            # Send spectate invite in lobby channel
            lobby_channel = self.bot.get_channel(session.game_handle.channel_id)
            if lobby_channel:
                from views.game_ui import SpectateView
                view = SpectateView(game_id, self)
                spectate_view = build_v2_layout(
                    title="👀 Spectate Mafioso",
                    description=(
                        "A new match has started!\n"
                        f"Click the button below to spectate the match channel <#{mafia_channel.id}>."
                    ),
                    color=discord.Color.blue(),
                    view=view,
                )
                self.bot.message_queue.send(lobby_channel, view=spectate_view)

            # 2. Ping all alive players so they can find the channel easily
            player_mentions = " ".join(f"<@{pid}>" for pid in session.player_ids)
            await self.bot.message_queue.send(mafia_channel, f"{get_emoji('lobby')} {player_mentions}")

            # 3. Send rules layout
            rules_view = build_v2_layout(
                title=f"{get_emoji('lobby')} Mafioso Remastered — Game Rules",
                description=get_rules_text(),
                color=discord.Color.from_rgb(0, 0, 0),
                image_url=get_event_image("rules"),
                footer_text="Roles have been sent to your DMs. Good luck!",
            )
            await self.bot.message_queue.send(mafia_channel, view=rules_view)

            # Wait a few seconds for players to read rules
            await asyncio.sleep(8)

            match_start_view = build_v2_layout(
                title="THE GAME HAS BEGUN!",
                description="Every player now wears a mask. Some seek justice, others crave blood, and a few answer only to Governments and themselves. From this moment on, every word matters, every vote has consequences..",
                color=discord.Color.from_rgb(255, 255, 255),
                image_url=get_event_image("match_start"),
            )
            await self.bot.message_queue.send(mafia_channel, view=match_start_view)
            await asyncio.sleep(3)

            # 4. Game Cycles
            session.metadata["night_num"] = 0
            session.metadata["day_num"] = 0

        try:
            while session.state != GameState.ENDED:
                if resuming_phase is None or resuming_phase == GamePhase.NIGHT_ACTIONS:
                    is_resume = (resuming_phase == GamePhase.NIGHT_ACTIONS)
                    resuming_phase = None

                    if not is_resume:
                        # Increment night
                        session.metadata["night_num"] += 1
                        session.state = GameState.NIGHT
                        session.phase = GamePhase.NIGHT_ACTIONS
                        session.night_actions.clear()
                        session.votes.clear()

                        # Reset temporary per-night flags and vote weights
                        for pstate in session.players.values():
                            pstate.metadata.pop("roleblocked", None)
                            pstate.vote_weight = 1
                        session.metadata.pop("geass_target", None)

                        # Mute all in #mafia for night
                        await self._update_channel_mute(mafia_channel, session, mute=True)

                        # Announce Night
                        night_num = session.metadata["night_num"]
                        from views.game_ui import NightActionView
                        night_action_view = NightActionView(game_id, self)
                        night_view = build_v2_layout(
                            title=f"Night {night_num}",
                            description=(
                                "Darkness shrouds the arena. The innocent sleep, unaware of the plots brewing in the shadows.\n"
                                "Check your DMs or use the buttons below to take your action before sunrise!"
                            ),
                            color=discord.Color.dark_blue(),
                            image_url=get_event_image("night"),
                            view=night_action_view,
                        )
                        await self.bot.message_queue.send(mafia_channel, view=night_view)

                        await self.bot.message_queue.send(mafia_channel, embed=night_embed)

                    night_num = session.metadata["night_num"]
                    # Send action interface (button that opens ephemeral select menu)
                    from views.game_ui import NightActionView
                    action_view = NightActionView(game_id, self)
                    prompt_text = (
                        f"{get_emoji('refresh')} **Game Resumed.** {get_emoji('night')} **Night Action Phase**\nClick below to prepare your move. The shadows will hide your secret."
                        if is_resume else
                        f"**Night Action Phase**\nClick below to use your role's ability."
                    )
                    night_msg = await self.bot.message_queue.send(
                        mafia_channel,
                        prompt_text,
                        view=action_view
                    )

                    # Wait for Night timeout (or all actions completed)
                    if not is_resume:
                        session.metadata["phase_ends_at"] = utcnow().timestamp() + settings.get("night_duration", 90)
                        await self.save_session_state(session)

                    while utcnow().timestamp() < session.metadata.get("phase_ends_at", 0):
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
                        session.metadata["day_num"] = session.metadata.get("day_num", 0) + 1
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

                if resuming_phase is None or resuming_phase == GamePhase.DISCUSSION:
                    is_resume = (resuming_phase == GamePhase.DISCUSSION)
                    resuming_phase = None

                    if not is_resume:
                        # Transition to Day
                        session.metadata["day_num"] += 1
                        session.state = GameState.DAY
                        session.phase = GamePhase.DISCUSSION

                        # Post the death report and the alive/dead roster as two
                        # separate embeds (they used to be one combined embed).
                        await self._send_death_and_status_embeds(
                            mafia_channel, guild, session,
                            title=f"Day {session.metadata['day_num']}",
                        )

                        # Check if Gilgamesh has transformed and is preparing apocalypse
                        for pid, pstate in list(session.players.items()):
                            if pstate.role_key == "gilgamesh" and pstate.metadata.get("transformed") and pstate.alive:
                                gilgamesh_layout = build_v2_layout(
                                    title=f"{get_emoji('warning')} Warning!",
                                    description=(
                                        f"{get_emoji('zap')} **Gilgamesh has retrieved all of his swords and "
                                        f"transformed into the Horseman of Apocalypse!**\n"
                                        f"You have until the end of today to find and lynch him, "
                                        f"or he will unleash the Gates of Babylon and wipe everyone out!"
                                    ),
                                    color=discord.Color.red(),
                                )
                                await self.bot.message_queue.send(
                                    mafia_channel,
                                    view=gilgamesh_layout
                                )

                        # Unmute alive in #mafia for discussion
                        await self._update_channel_mute(mafia_channel, session, mute=False)

                    if is_resume:
                        await self._update_channel_mute(mafia_channel, session, mute=False)
                        await self.bot.message_queue.send(mafia_channel, f"{get_emoji('refresh')} **Game Resumed.** Discussion phase is active.")

                    # Discussion Timer
                    if not is_resume:
                        session.metadata["phase_ends_at"] = utcnow().timestamp() + settings.get("day_duration", 120)
                        session.metadata.pop("rebellion_triggered", None)
                        await self.save_session_state(session)

                    while utcnow().timestamp() < session.metadata.get("phase_ends_at", 0):
                        if session.metadata.get("rebellion_triggered"):
                            break
                        await asyncio.sleep(2)

                # Day Voting Loop (supports returning to voting phase on successful retrial)
                break_to_voting = False
                while True:
                    if resuming_phase is None or resuming_phase == GamePhase.VOTING:
                        is_resume = (resuming_phase == GamePhase.VOTING)
                        resuming_phase = None

                        if not is_resume:
                            # Day Voting
                            session.phase = GamePhase.VOTING
                            session.votes.clear()
                            session.metadata.pop("skip_votes", None)

                            # Send Vote Layout
                            from views.game_ui import VoteUISelectView
                            vote_view = VoteUISelectView(game_id, self)
                            vote_layout = build_v2_layout(
                                title=f"Day {session.metadata['day_num']} - Nomination Phase",
                                description=(
                                    "Accusations are flying, friendship is a myth! It's time to choose who gets dragged onto the stand.\n"
                                    "Click the button below to nominate someone to face judgment, or vote to skip today's trial."
                                ),
                                color=discord.Color.red(),
                                image_url=get_event_image("vote") or "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcTkzVOSwfpSbFQmCQiOFDVQ6HYJZSlaPFTif988sFYfU5mV6F7x3SpsAas&s=10",
                                view=vote_view,
                            )

                            vote_msg = await self.bot.message_queue.send(
                                mafia_channel,
                                view=vote_layout
                            )

                        if is_resume:
                            from views.game_ui import VoteUISelectView
                            vote_view = VoteUISelectView(game_id, self)
                            vote_layout = build_v2_layout(
                                title=f"🔄 Game Resumed — Day {session.metadata['day_num']} - Nomination Phase",
                                description=(
                                    "Accusations are flying, nomination buttons have been refreshed!\n"
                                    "Click the button below to nominate someone to face judgment, or vote to skip today's trial."
                                ),
                                color=discord.Color.red(),
                                view=vote_view,
                            )
                            vote_msg = await self.bot.message_queue.send(
                                mafia_channel,
                                view=vote_layout
                            )

                        # Wait for Voting timeout
                        if not is_resume:
                            session.metadata["phase_ends_at"] = utcnow().timestamp() + settings.get("vote_duration", 60)
                            await self.save_session_state(session)

                        while utcnow().timestamp() < session.metadata.get("phase_ends_at", 0):
                            if session.metadata.get("deadly_sentencing_triggered"):
                                break
                            alive_count_check = sum(1 for p in session.players.values() if p.alive)
                            total_votes = len(session.votes) + len(session.metadata.get("skip_votes", set()))
                            if total_votes >= alive_count_check:
                                break
                            await asyncio.sleep(2)

                        # Remove vote view
                        try:
                            closed_vote_layout = build_v2_layout(
                                title=f"Day {session.metadata['day_num']} - Nomination Phase Closed",
                                description="The nomination window has closed. The ballots are being counted...",
                                color=discord.Color.red(),
                            )
                            await vote_msg.edit(view=closed_vote_layout)
                        except Exception:
                            pass


                        # Check if Deadly Sentencing was run
                        if session.metadata.get("deadly_sentencing_run") or session.metadata.get("deadly_sentencing_triggered"):
                            # Wait for the execution drama to completely finish
                            while session.metadata.get("deadly_sentencing_active"):
                                await asyncio.sleep(0.5)
                            
                            # Add a 3 seconds delay after all messages are completed
                            await asyncio.sleep(3)
                            
                            session.metadata.pop("deadly_sentencing_run", None)
                            session.metadata.pop("deadly_sentencing_triggered", None)
                            session.metadata.pop("deadly_sentencing_active", None)
                            session.metadata.pop("defendant_id", None)
                            session.metadata.pop("verdicts", None)
                            await self.bot.message_queue.send(mafia_channel, f"{get_emoji('court')} **Deadly Sentencing completed. Skipping normal trial.**")
                            await asyncio.sleep(2)
                            break

                        # Calculate Vote Results
                        tally = {}
                        geass_target = session.metadata.get("geass_target")
                        for voter_id, nominated_id in session.votes.items():
                            voter_state = session.players.get(voter_id)
                            weight = voter_state.vote_weight if voter_state else 1
                            if nominated_id == geass_target:
                                weight *= 2
                            tally[nominated_id] = tally.get(nominated_id, 0) + weight

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
                            vote_details_view = build_v2_layout(
                                title=f"{get_emoji('vote')} Vote Details",
                                description="\n".join(vote_detail_lines),
                                color=discord.Color.blue(),
                            )
                            await self.bot.message_queue.send(
                                mafia_channel,
                                view=vote_details_view
                            )

                    majority_passed = False
                    if resuming_phase in (GamePhase.TRIAL, GamePhase.EXECUTION):
                        target_id = session.metadata.get("defendant_id")
                        defendant_mem = guild.get_member(target_id) if target_id else None
                        defendant_name = defendant_mem.display_name if defendant_mem else f"User {target_id}"
                        majority_passed = True
                    else:
                        # Check if majority voted a player on stand
                        if target_id and max_votes >= majority and max_votes > skip_count:
                            majority_passed = True
                            defendant_mem = guild.get_member(target_id)
                            defendant_name = defendant_mem.display_name if defendant_mem else f"User {target_id}"

                            # Mahoraga full-adapt vote immunity check
                            target_pstate = session.players.get(target_id)
                            if (
                                session.metadata.get("mahoraga_vote_immune")
                                and target_pstate
                                and target_pstate.role_key == "mahoraga"
                                and target_pstate.metadata.get("mahoraga_adapt_complete")
                            ):
                                # Reveal Mahoraga's role and block the trial
                                mahoraga_view = build_v2_layout(
                                    title="🌀 Adaptation — Absolute!",
                                    description=(
                                        f"**{defendant_name}** has fully adapted to all three factions!\n\n"
                                        f"They are **immune to all votes and trials**. "
                                        f"No conventional force can remove them from this game.\n\n"
                                        f"Their role has been revealed: **Eight-Handled Sword Divergent Sila Divine General Mahoraga** 🌀\n\n"
                                        f"Only an unstoppable one-hit ability can end their reign now."
                                    ),
                                    color=discord.Color.from_rgb(110, 58, 190),
                                )
                                await self.bot.message_queue.send(
                                    mafia_channel,
                                    view=mahoraga_view
                                )
                                session.votes.clear()
                                session.metadata.pop("skip_votes", None)
                                majority_passed = False
                                break  # skip the voting phase entirely for this cycle

                            # Mute all EXCEPT defendant (but do not mute the text channel during plea)
                            session.phase = GamePhase.TRIAL
                            session.metadata["defendant_id"] = target_id
                            await self._update_channel_mute_trial(mafia_channel, session, target_id)


                    if majority_passed:
                        if resuming_phase is None or resuming_phase == GamePhase.TRIAL:
                            is_resume = (resuming_phase == GamePhase.TRIAL)
                            resuming_phase = None

                            if not is_resume:
                                plea_time = settings.get("plea_duration", 60)
                                plea_view = build_v2_layout(
                                    title="Trial: Defendant on the Stand",
                                    description=(
                                        f"**{defendant_name}** has been dragged onto the stand by majority vote!\n"
                                        f"They have {plea_time} seconds to defend themselves before the court decides their fate. Speak, or get voted out."
                                    ),
                                    color=discord.Color.orange(),
                                    image_url=get_event_image("plea"),
                                )
                                await self.bot.message_queue.send(
                                    mafia_channel,
                                    view=plea_view
                                )
                            else:
                                await self.bot.message_queue.send(
                                    mafia_channel,
                                    f"{get_emoji('refresh')} **Game Resumed.** **{defendant_name}** is on the stand. Please speak in your defense."
                                )

                            # Plea Timer
                            if not is_resume:
                                session.metadata["phase_ends_at"] = utcnow().timestamp() + settings.get("plea_duration", 60)
                                await self.save_session_state(session)

                            while utcnow().timestamp() < session.metadata.get("phase_ends_at", 0):
                                await asyncio.sleep(1)

                        # Verdict Loop (supports retrial failure redirecting back to guilty/inno selection)
                        break_to_voting = False
                        while True:
                            if resuming_phase is None or resuming_phase == GamePhase.EXECUTION:
                                is_resume = (resuming_phase == GamePhase.EXECUTION)
                                resuming_phase = None

                                if not is_resume:
                                    # Verdict Phase
                                    session.phase = GamePhase.EXECUTION
                                    session.metadata["verdicts"] = {}

                                    # Unmute everyone for verdict buttons
                                    await self._update_channel_mute(mafia_channel, session, mute=False)

                                    from views.game_ui import VerdictUISelectView
                                    verdict_view = VerdictUISelectView(game_id, self)
                                    verdict_layout = build_v2_layout(
                                        title="Verdict Phase: Life or Death",
                                        description=(
                                            f"Cast your final judgment on defendant **{defendant_name}**.\n"
                                            "Will they walk free, or face the hangman's noose? Choose Guilty or Innocent below."
                                        ),
                                        color=discord.Color.red(),
                                        image_url=get_event_image("verdict"),
                                        view=verdict_view,
                                    )

                                    verdict_msg = await self.bot.message_queue.send(
                                        mafia_channel,
                                        view=verdict_layout
                                    )

                                if is_resume:
                                    await self._update_channel_mute(mafia_channel, session, mute=False)
                                    from views.game_ui import VerdictUISelectView
                                    verdict_view = VerdictUISelectView(game_id, self)
                                    verdict_layout = build_v2_layout(
                                        title=f"🔄 Game Resumed — {get_emoji('trial')} Verdict Phase: Life or Death",
                                        description=(
                                            f"Cast your final judgment on defendant **{defendant_name}**.\n"
                                            "Verdict buttons have been refreshed! Choose Guilty or Innocent below."
                                        ),
                                        color=discord.Color.red(),
                                        view=verdict_view,
                                    )
                                    verdict_msg = await self.bot.message_queue.send(
                                        mafia_channel,
                                        view=verdict_layout
                                    )

                                if not is_resume:
                                    session.metadata["phase_ends_at"] = utcnow().timestamp() + settings.get("verdict_duration", 30)
                                    await self.save_session_state(session)

                                while utcnow().timestamp() < session.metadata.get("phase_ends_at", 0):
                                    if session.metadata.get("retrial_triggered"):
                                        break
                                    await asyncio.sleep(1)

                                # Remove verdict view
                                try:
                                    closed_verdict_layout = build_v2_layout(
                                        title="Verdict Phase: Closed",
                                        description="The verdict phase has closed. The court is deciding...",
                                        color=discord.Color.red(),
                                    )
                                    await verdict_msg.edit(view=closed_verdict_layout)
                                except Exception:
                                    pass


                            # Check if Retrial was triggered during this verdict phase
                            if session.metadata.get("retrial_triggered"):
                                session.metadata.pop("retrial_triggered", None)
                                retrial_defendant = session.metadata.get("retrial_defendant")
                                retrial_by = session.metadata.get("retrial_by")

                                # wait a bit
                                await asyncio.sleep(2)

                                # send "WE ARE HAVING A RETRIAL!!!" 3 times delayed by like 1s
                                for _ in range(3):
                                    await self.bot.message_queue.send(mafia_channel, f"**WE ARE HAVING A RETRIAL!!!**")
                                    await asyncio.sleep(1)

                                # wait a bit
                                await asyncio.sleep(2)

                                def_player = session.players.get(retrial_defendant)
                                if def_player and def_player.faction == RoleFaction.HERO.value:
                                    # Successful Retrial (Saved Town player)
                                    acquittal_layout = build_v2_layout(
                                        title=f"{get_emoji('trial')} RETRIAL: SUCCESSFUL ACQUITTAL",
                                        description=(
                                            f"Defendant <@{retrial_defendant}> has been proven beyond a reasonable doubt to be a **Protagonist**!\n"
                                            f"Their execution is canceled. The court has released them.\n\n"
                                            f"Returning to the Nomination/Voting phase to choose a new target."
                                        ),
                                        color=discord.Color.green(),
                                    )
                                    await self.bot.message_queue.send(
                                        mafia_channel,
                                        view=acquittal_layout
                                    )
                                    # wait a bit before starting next phase
                                    await asyncio.sleep(3)

                                    # Reset defendant metadata
                                    session.metadata.pop("defendant_id", None)
                                    session.metadata.pop("verdicts", None)
                                    break_to_voting = True
                                    break
                                else:
                                    # Failed Retrial (Target is not Town)
                                    higuruma_p = session.players.get(retrial_by)
                                    if higuruma_p:
                                        higuruma_p.metadata["retrial_uses"] = 0
                                        
                                    def_role_display = def_player.role_key.replace('_', ' ').title() if def_player else "Unknown"
                                    confirmed_layout = build_v2_layout(
                                        title=f"{get_emoji('trial')} RETRIAL: JUDGMENT CONFIRMED",
                                        description=(
                                            f"An attempt to acquit <@{retrial_defendant}> failed! They are **not a Protagonist**.\n"
                                            f"• The defendant's true identity is revealed as **{def_role_display}**.\n\n"
                                            f"Returning to the Verdict phase to seal their fate."
                                        ),
                                        color=discord.Color.red(),
                                    )
                                    await self.bot.message_queue.send(
                                        mafia_channel,
                                        view=confirmed_layout
                                    )
                                    # wait a bit before returning to verdict selection
                                    await asyncio.sleep(3)
                                    continue

                            # No retrial triggered, process the verdict normally
                            verdict_data = session.metadata.get("verdicts", {})
                            geass_target = session.metadata.get("geass_target")
                            guilty_count = 0
                            inno_count = 0
                            for voter_id, decision in verdict_data.items():
                                voter_state = session.players.get(int(voter_id))
                                weight = voter_state.vote_weight if voter_state else 1
                                if decision == "guilty":
                                    if target_id == geass_target:
                                        weight *= 2
                                    guilty_count += weight
                                elif decision == "innocent":
                                    inno_count += weight

                            # Verdict results output
                            verdict_report_lines = []
                            for pid, decision in verdict_data.items():
                                v_mem = guild.get_member(int(pid))
                                v_name = v_mem.display_name if v_mem else f"User {pid}"
                                verdict_report_lines.append(f"• **{v_name}**: {decision.upper()}")

                            if not anon and verdict_report_lines:
                                verdict_logs_layout = build_v2_layout(
                                    title=f"{get_emoji('trial')} Verdict Logs",
                                    description="\n".join(verdict_report_lines),
                                    color=discord.Color.blue(),
                                )
                                await self.bot.message_queue.send(
                                    mafia_channel,
                                    view=verdict_logs_layout
                                )

                            await self.bot.message_queue.send(
                                mafia_channel,
                                f"{get_emoji('trial')} Verdict Totals: **{guilty_count} Guilty** vs **{inno_count} Innocent**."
                            )

                            if guilty_count > inno_count:
                                # Perform lynch
                                def_state = session.players[target_id]
                                if def_state.metadata.get("lynch_immune_day") == session.metadata.get("day_num", 0):
                                    await self.bot.message_queue.send(mafia_channel, f"{get_emoji('mahoraga')} **Mahoraga is immune to being lynched today!** The trial is dismissed.")
                                elif def_state.role_key == "makima" and not def_state.metadata.get("pm_contract_activated"):
                                    def_state.metadata["pm_contract_activated"] = True
                                    await self.bot.message_queue.send(
                                        mafia_channel,
                                        f"{get_emoji('trial')} **Prime Minister's Contract Triggered!**\n"
                                        f"An invisible force has prevented the execution! The defendant survives.\n"
                                        f"The Day ends immediately with no execution."
                                    )
                                    session.metadata.pop("defendant_id", None)
                                    session.metadata.pop("verdicts", None)
                                    break_to_voting = False
                                    break
                                else:
                                    # Check Lelouch Zero Requiem lynch trigger
                                    if def_state.role_key == "lelouch":
                                        def_state.metadata["lelouch_lynched"] = True
                                        zero_requiem_layout = build_v2_layout(
                                            title=f"{get_emoji('crown')} Zero Requiem Activated!",
                                            description=(
                                                f"**{defendant_name}** (Lelouch Lamperouge) has been executed by the town!\n\n"
                                                f"This was all part of his master plan to focus the world's hatred on himself and die, breaking the cycle of hatred.\n\n"
                                                f"{get_emoji('victory')} **Lelouch Lamperouge wins the game!**"
                                            ),
                                            color=discord.Color.purple(),
                                        )
                                        await self.bot.message_queue.send(
                                            mafia_channel,
                                            view=zero_requiem_layout
                                        )

                                    # Check Hisoka Post-Mortem Nen lynch trigger
                                    if def_state.role_key == "hisoka" and night_num <= 5:
                                        def_state.metadata["post_mortem_win"] = True
                                        def_state.metadata["revived"] = True
                                        def_state.metadata["revived_days_left"] = 3
                                        await self.bot.message_queue.send(mafia_channel, f"{get_emoji('hisoka')} **Hisoka was lynched! His Post-Mortem Nen will activate tomorrow...**")

                                    # Perform elimination
                                    role_meta = roles.ROLES_METADATA.get(def_state.role_key, {})
                                    role_display = role_meta.get("name", def_state.role_key or "Unknown")
                                    role_emoji = get_emoji(def_state.role_key) if def_state.role_key else ""
                                    role_emoji_prefix = f"{role_emoji} " if role_emoji else ""
                                    await self.eliminate_player(game_id, target_id, "execution")
                                    exec_layout = build_v2_layout(
                                        title=f"{get_emoji('death')} Execution",
                                        description=f"**{defendant_name}** was executed by the town! Their role was **{role_emoji_prefix}{role_display}**.",
                                        color=discord.Color.red(),
                                    )
                                    await self.bot.message_queue.send(
                                        mafia_channel,
                                        view=exec_layout
                                    )

                            else:
                                await self.bot.message_queue.send(mafia_channel, f"{get_emoji('peace')} The town has voted to release the defendant.")

                            # Reset defendant metadata and break the verdict loop
                            session.metadata.pop("defendant_id", None)
                            session.metadata.pop("verdicts", None)

                            # Announce trial concluded
                            await self.bot.message_queue.send(mafia_channel, f"{get_emoji('trial')} **Trial concluded.**")
                            break
                        
                        if break_to_voting:
                            continue
                        else:
                            break
                    else:
                        await self.bot.message_queue.send(mafia_channel, f"Voting skipped. No one is on trial today.")
                        break

                # Check Victory after day phase
                winner = self._evaluate_victory(session)
                if winner:
                    session.state = GameState.ENDED
                    session.winner_faction = winner
                    break

                # Make sure all day/trial messages have finished sending
                if self.bot and hasattr(self.bot, "message_queue"):
                    try:
                        await self.bot.message_queue._queue.join()
                    except Exception:
                        pass

                # Wait 8 seconds before locking the channel and starting the next night
                await asyncio.sleep(8)

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
                await self.bot.message_queue.send(mafia_channel, f"{get_emoji('warning')} **This channel will be deleted in 20 seconds...**")
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
        """Sends a detailed victory V2 layout view with Winners and Losers lists."""
        faction_display_map = {
            RoleFaction.HERO.value: f"Protagonists Win!",
            RoleFaction.VILLAIN.value: f"Antagonists Win!",
            "Draw": f"{get_emoji('peace')} It's a Draw!",
        }
        title = faction_display_map.get(winner_faction, f"{winner_faction} Wins!")

        winners_lines = []
        losers_lines = []

        for pid, rkey in history.roles.items():
            member = guild.get_member(pid)
            name = member.display_name if member else f"User {pid}"
            role_meta = roles.ROLES_METADATA.get(rkey, {})
            role_display = role_meta.get("name", rkey)
            role_emoji = get_emoji(rkey) if rkey else ""
            role_emoji_prefix = f"{role_emoji} " if role_emoji else ""
            pstate = session.players.get(pid)
            status = "Alive" if (pstate and pstate.alive) else "Dead"

            player_line = f"• **{name}** — {role_display}  ({status})"

            is_winner = False
            if winner_faction == "Draw":
                is_winner = False
            elif winner_faction == RoleFaction.HERO.value:
                if pstate and pstate.faction == RoleFaction.HERO.value:
                    is_winner = True
            elif winner_faction == RoleFaction.VILLAIN.value:
                if pstate and pstate.faction == RoleFaction.VILLAIN.value:
                    is_winner = True
            else:
                if pstate and pstate.metadata.get("has_won"):
                    is_winner = True
                elif pstate and rkey and roles.ROLES_METADATA.get(rkey, {}).get("name") == winner_faction:
                    is_winner = True

            if is_winner:
                winners_lines.append(player_line)
            else:
                if pstate and pstate.metadata.get("has_won"):
                    winners_lines.append(player_line)
                else:
                    losers_lines.append(player_line)

        desc_sections = []
        if winners_lines:
            desc_sections.append(f"## {get_emoji('victory')} Winners\n" + "\n".join(winners_lines))
        if losers_lines:
            desc_sections.append(f"## {get_emoji('death')} Losers\n" + "\n".join(losers_lines))
        if winner_faction == "Draw":
            desc_sections.append(f"## {get_emoji('chat')} All Players\n" + ("\n".join(winners_lines + losers_lines) if (winners_lines or losers_lines) else "No players."))

        minutes = history.duration_seconds // 60
        seconds = history.duration_seconds % 60
        footer_text = f"Match Duration: {minutes}m {seconds}s"

        image_key = {
            RoleFaction.HERO.value: "victory_hero",
            RoleFaction.VILLAIN.value: "victory_villain",
            "Draw": "draw",
        }.get(winner_faction, "victory_neutral")
        image_url = get_event_image(image_key)

        victory_view = build_v2_layout(
            title=title,
            description="\n\n".join(desc_sections),
            color=discord.Color.gold(),
            image_url=image_url,
            footer_text=footer_text,
        )

        await self.bot.message_queue.send(channel, view=victory_view)

    async def _send_death_and_status_embeds(
        self,
        channel: discord.TextChannel,
        guild: discord.Guild,
        session: GameSession,
        *,
        title: str,
    ) -> None:
        """Sends the night's death report and the alive/dead roster as two
        separate layout views (kept apart so each is easy to read on its own)."""
        dead_this_round = session.metadata.pop("dead_this_round", [])

        mafia_deaths = []
        other_deaths = []
        MAFIA_DEATH_CAUSES = {"mafia_strike", "frieza_kill", "demon_strike", "light_guess", "bang_kill"}

        for dpid in dead_this_round:
            pstate = session.players.get(dpid)
            cause = pstate.metadata.get("death_cause") if pstate else None
            msg = pstate.metadata.get("death_message") if pstate else None
            if not msg:
                member = guild.get_member(dpid)
                mname = member.display_name if member else f"User {dpid}"
                msg = get_death_message(cause, mname)
            
            if cause in MAFIA_DEATH_CAUSES:
                mafia_deaths.append(msg)
            else:
                other_deaths.append(msg)

        # 1. Main Mafia Death Report
        if mafia_deaths:
            death_description = "\n".join(f"{get_emoji('death')} {msg}" for msg in mafia_deaths)
        else:
            death_description = f"No one was targeted by the Antagonists tonight.. How weird.."

        death_layout = build_v2_layout(
            title=f"{title} - Death Report",
            description=death_description,
            color=discord.Color.dark_red() if mafia_deaths else discord.Color.gold(),
            image_url=get_event_image("death" if mafia_deaths else "day"),
        )
        await self.bot.message_queue.send(channel, view=death_layout)
        await asyncio.sleep(2.5)

        # 2. Other Casualties Report
        if other_deaths:
            other_description = "\n".join(f"{get_emoji('death')} {msg}" for msg in other_deaths)
            other_layout = build_v2_layout(
                title=f"{title} - Other Casualties",
                description=other_description,
                color=discord.Color.dark_orange(),
                image_url=get_event_image("death"),
            )
            await self.bot.message_queue.send(channel, view=other_layout)
            await asyncio.sleep(2.5)

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
                role_emoji = get_emoji(pstate.role_key) if pstate.role_key else ""
                role_emoji_prefix = f"{role_emoji} " if role_emoji else ""
                dead_list.append(f"• ~~{mname}~~ ({role_emoji_prefix}{role_display})")

        status_desc = (
            "## Alive Players\n" + ("\n".join(alive_list) if alive_list else "None") +
            "\n\n## Dead Players\n" + ("\n".join(dead_list) if dead_list else "None")
        )

        status_layout = build_v2_layout(
            title=f"{title} - Player Status",
            description=status_desc,
            color=discord.Color.blurple(),
            image_url="https://img.magnific.com/free-vector/anime-cloud-blue-heaven-sky-vector-background-summer-abstract-cloudy-air-design-with-gradient-sun-light-with-reflection-beautiful-calm-morning-game-outdoor-panorama-with-sunshine-painting_107791-23777.jpg",
        )
        await self.bot.message_queue.send(channel, view=status_layout)
        await asyncio.sleep(2.5)


    async def _all_active_submitted(self, session: GameSession) -> bool:
        """Checks if all alive players who have active night actions have submitted."""
        for pid, pstate in session.players.items():
            if not pstate.alive:
                continue
            if pstate.role_key in ["villager", "demon", "mahoraga"]:
                continue
            if pstate.metadata.get("roleblocked"):
                continue
            if pstate.metadata.get("detained"):
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
        
        # New modular protection queues
        session.metadata["doctor_heals"] = {}
        session.metadata["flying_thunder_counters"] = {}
        session.metadata["magical_barriers"] = {}
        session.metadata["life_supports"] = {}

        # Pre-populate Hisoka's Bloodlust challenges lookup early
        session.metadata["bloodlust_challenges"] = {}
        for pid, pstate in session.players.items():
            if pstate.role_key == "hisoka" and pstate.alive:
                if not pstate.metadata.get("roleblocked"):
                    payload = session.night_actions.get(pid)
                    if payload and payload.get("action_index") == 2:
                        target_id = payload.get("target_id")
                        if target_id:
                            session.metadata["bloodlust_challenges"][target_id] = pid

        # 0. Check Makima controls before processing actions and visits
        makima_id = None
        for pid, pstate in session.players.items():
            if pstate.role_key == "makima" and pstate.alive:
                makima_id = pid
                break

        if makima_id and makima_id in session.night_actions:
            makima_payload = session.night_actions[makima_id]
            action_idx = makima_payload.get("action_index", 0)
            if action_idx == 0:  # Control
                controlled_pid = makima_payload.get("target_id")
                redirect_pid = makima_payload.get("redirect_target")
                
                controlled_state = session.players.get(controlled_pid) if controlled_pid else None
                makima_state = session.players.get(makima_id)
                
                if controlled_state and controlled_state.alive and controlled_state.faction != RoleFaction.VILLAIN.value:
                    if controlled_state.role_key == "kishibe" and not controlled_state.metadata.get("battle_hardened_used"):
                        controlled_state.metadata["battle_hardened_used"] = True
                        makima_payload["control_success"] = False
                        makima_payload["error"] = "Your target resisted your ability."
                        makima_payload["log"] = f"Makima attempted to control <@{controlled_pid}>, but they resisted!"
                    elif controlled_state.role_key in ("dazai", "asta"):
                        makima_payload["control_success"] = False
                        makima_payload["error"] = "Your target resisted your ability."
                        makima_payload["log"] = f"Makima attempted to control <@{controlled_pid}>, but they resisted!"
                    else:
                        last_controlled = makima_state.metadata.get("last_controlled_player")
                        if last_controlled != controlled_pid:
                            makima_state.metadata["last_controlled_player"] = controlled_pid
                        
                        # Target must perform an active visit (be in night_actions and have target_id or targets)
                        if controlled_pid in session.night_actions:
                            controlled_payload = session.night_actions[controlled_pid]
                            has_active_target = False
                            if controlled_payload.get("target_id") is not None:
                                has_active_target = True
                            elif controlled_payload.get("targets"):
                                has_active_target = True
                                
                            if has_active_target:
                                # Successful redirection!
                                if "target_id" in controlled_payload and controlled_payload["target_id"] is not None:
                                    controlled_payload["target_id"] = redirect_pid
                                if "targets" in controlled_payload and controlled_payload["targets"]:
                                    controlled_payload["targets"] = (redirect_pid,) * len(controlled_payload["targets"])
                                    
                                # Track unique controlled targets
                                controlled_history = makima_state.metadata.setdefault("controlled_targets_history", [])
                                if controlled_pid not in controlled_history:
                                    controlled_history.append(controlled_pid)
                                makima_state.metadata["controlled_count"] = len(controlled_history)
                                
                                makima_payload["control_success"] = True
                                makima_payload["target_id"] = controlled_pid
                                makima_payload["redirect_target"] = redirect_pid
                                makima_payload["log"] = f"Makima controlled <@{controlled_pid}> and redirected their action to <@{redirect_pid}>."
                            else:
                                makima_payload["control_success"] = False
                                makima_payload["error"] = "Target player did not perform an active visit."
                        else:
                            makima_payload["control_success"] = False
                            makima_payload["error"] = "Target player did not perform an active visit."
                else:
                    makima_payload["control_success"] = False
                    makima_payload["error"] = "Invalid target."

        # Apply Hisoka's Bloodlust redirects directly to session.night_actions
        challenges = session.metadata.get("bloodlust_challenges", {})
        for actor_id, hisoka_id in challenges.items():
            actor_state = session.players.get(actor_id)
            if actor_state and actor_state.role_key in ("dazai", "asta"):
                continue  # Dazai and Asta are immune to redirects
            payload = session.night_actions.get(actor_id)
            if payload:
                if payload.get("target_id") == hisoka_id:
                    payload["target_id"] = actor_id
                ts = payload.get("targets", ())
                if ts:
                    new_ts = tuple(actor_id if target == hisoka_id else target for target in ts)
                    if new_ts != ts:
                        payload["targets"] = new_ts
                if payload.get("controlled_vote_target") == hisoka_id:
                    payload["controlled_vote_target"] = actor_id

        # Collect visits for history (to support Maomao)
        history = session.metadata.setdefault("night_visits_history", {})
        night_visits = history.setdefault(night_num, {})
        for actor_id, payload in list(session.night_actions.items()):
            actor_state = session.players.get(actor_id)
            is_blocked = actor_state.metadata.get("roleblocked") and not (actor_state.role_key == "frieza" and actor_state.metadata.get("golden_frieza"))
            if not actor_state or not actor_state.alive or is_blocked:
                continue
            targets = []
            t_id = payload.get("target_id")
            if t_id is not None:
                targets.append(t_id)
            for t in payload.get("targets", ()):
                targets.append(t)
            for t in targets:
                night_visits.setdefault(t, []).append(actor_id)

        # 1. Gather all actions
        action_list = []
        for actor_id, payload in list(session.night_actions.items()):
            actor_state = session.players.get(actor_id)
            if not actor_state or not actor_state.alive:
                continue

            # Check roleblock / detention early
            is_blocked = actor_state.metadata.get("roleblocked") and not (actor_state.role_key == "frieza" and actor_state.metadata.get("golden_frieza"))
            if is_blocked:
                continue
            if actor_state.metadata.get("detained"):
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
            # Check if actor got roleblocked or detained during the resolution
            actor_state = session.players.get(actor_id)
            is_blocked = actor_state.metadata.get("roleblocked") and not (actor_state.role_key == "frieza" and actor_state.metadata.get("golden_frieza"))
            if is_blocked:
                continue
            if actor_state.metadata.get("detained"):
                continue

            # Dazai No Longer Human nullification
            if actor_state.metadata.get("nullified"):
                continue

            # Asta Black Divider nullification
            if actor_state.metadata.get("black_divider_nullified"):
                import asyncio
                async def notify_null(s=session, a_id=actor_id, bot=self.bot):
                    if bot:
                        guild = bot.get_guild(s.game_handle.guild_id)
                        member = guild.get_member(a_id) if guild else None
                        if member:
                            try:
                                bot.message_queue.send(member, f"{get_emoji('cross')} **Your ability was nullified tonight.**")
                            except Exception:
                                pass
                asyncio.create_task(notify_null())
                continue

            # Asta Devil Union nullification
            if session.metadata.get("devil_union_active"):
                if actor_state.faction in (RoleFaction.VILLAIN.value, RoleFaction.NEUTRAL.value):
                    targets_town = False
                    t_id = payload.get("target_id")
                    if t_id:
                        t_st = session.players.get(t_id)
                        if t_st and t_st.faction == RoleFaction.HERO.value:
                            targets_town = True
                    targets_list = payload.get("targets", ())
                    if targets_list:
                        for t in targets_list:
                            t_st = session.players.get(t)
                            if t_st and t_st.faction == RoleFaction.HERO.value:
                                targets_town = True
                    if targets_town:
                        import asyncio
                        async def notify_union(s=session, a_id=actor_id, bot=self.bot):
                            if bot:
                                guild = bot.get_guild(s.game_handle.guild_id)
                                member = guild.get_member(a_id) if guild else None
                                if member:
                                    try:
                                        bot.message_queue.send(member, f"{get_emoji('cross')} **Your action failed due to Asta's Devil Union!**")
                                    except Exception:
                                        pass
                        asyncio.create_task(notify_union())
                        continue

            # Invisibility check (Potion of Invisibility)
            if actor_state.role_key != "maomao":
                t_id = payload.get("target_id")
                if t_id:
                    t_st = session.players.get(t_id)
                    if t_st and t_st.metadata.get("invisible"):
                        payload["error"] = "Your target was invisible tonight."
                        payload["log"] = f"{actor_state.character_name} attempted to target <@{t_id}>, but they were invisible."
                        if self.bot:
                            g = self.bot.get_guild(session.game_handle.guild_id)
                            m = g.get_member(actor_id) if g else None
                            if m:
                                try:
                                    self.bot.message_queue.send(m, f"{get_emoji('cross')} **Your action tonight failed because your target was invisible!**")
                                except Exception:
                                    pass
                        continue
                targets_list = payload.get("targets", ())
                if targets_list:
                    if any(session.players.get(t) and session.players[t].metadata.get("invisible") for t in targets_list if session.players.get(t)):
                        payload["error"] = "One of your targets was invisible tonight."
                        payload["log"] = f"{actor_state.character_name} attempted to target an invisible player."
                        if self.bot:
                            g = self.bot.get_guild(session.game_handle.guild_id)
                            m = g.get_member(actor_id) if g else None
                            if m:
                                try:
                                    self.bot.message_queue.send(m, f"{get_emoji('cross')} **Your action tonight failed because one of your targets was invisible!**")
                                except Exception:
                                    pass
                        continue

            # Tōsen Bankai protection: prevent most players from targeting a detained prisoner
            if actor_state.role_key != "tosen":
                t_id = payload.get("target_id")
                if t_id:
                    t_st = session.players.get(t_id)
                    if t_st and t_st.metadata.get("detained"):
                        continue
                targets_list = payload.get("targets", ())
                if targets_list:
                    if any(session.players.get(t) and session.players[t].metadata.get("detained") for t in targets_list if session.players.get(t)):
                        continue

            context = RoleContext(
                game_id=session.game_handle.game_id,
                guild_id=session.game_handle.guild_id,
                user_id=actor_id,
                target_id=payload.get("target_id"),
                targets=payload.get("targets", ()),
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
                                    intel_layout = build_v2_layout(
                                        title=f"{emoji} {role_display} Intel",
                                        description=context.payload["result"],
                                        color=discord.Color.blue(),
                                    )
                                    self.bot.message_queue.send(actor_member, view=intel_layout)

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
                
                # Notify Light Yagami that the target was hit
                for ly_id, ly_state in session.players.items():
                    if ly_state.role_key == "light_yagami" and ly_state.alive:
                        guild_id = session.game_handle.guild_id
                        g = self.bot.get_guild(guild_id)
                        if g:
                            ly_member = g.get_member(ly_id)
                            if ly_member:
                                try:
                                    self.bot.message_queue.send(
                                        ly_member,
                                        f"🍎 **Devil's Pen:** The 3 nights have passed. Your target <@{pid}> has been written out of existence!"
                                    )
                                except Exception:
                                    pass

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


        # 4. Kishibe Veteran's Instinct — Alert kills
        for pid, pstate in session.players.items():
            if pstate.role_key == "kishibe" and pstate.alive:
                payload = session.night_actions.get(pid)
                if not payload:
                    continue
                action_idx = payload.get("action_index", 0)
                is_alert = action_idx in (0, 1)  # 0 = Alert, 1 = Broken Screw
                if not is_alert:
                    continue

                visitors = night_visits.get(pid, [])
                for visitor_id in visitors:
                    v_state = session.players.get(visitor_id)
                    if v_state and v_state.alive:
                        kills = session.metadata.setdefault("pending_kills", {})
                        kills[visitor_id] = kills.get(visitor_id, []) + ["kishibe_alert_kill"]

                # Broken Screw: if the screw target visited, charge is saved
                saved_charge = False
                if action_idx == 1:
                    screw_target = payload.get("target_id")
                    if screw_target and screw_target in visitors:
                        saved_charge = True

                if not saved_charge:
                    pstate.metadata["alerts_left"] = max(0, pstate.metadata.get("alerts_left", 3) - 1)

        # Populate heals history for the night
        heals_history = session.metadata.setdefault("heals_history", {})
        night_heals = heals_history.setdefault(night_num, {})
        
        doc_heals = session.metadata.get("doctor_heals", {})
        for tid, doc_id in doc_heals.items():
            night_heals[tid] = True
            session.metadata.setdefault("healed_players", {})[tid] = doc_id
            session.metadata["healed_players"][tid + 1000000] = doc_id
            
        # (Water walls replaced by Flying Thunder Counter)
        magical_barriers = session.metadata.get("magical_barriers", {})
        for tid in magical_barriers:
            night_heals[tid] = True

        # 5. Apply Heals/Protections vs Attacks
        pending_kills = session.metadata.get("pending_kills", {})
        healed_players = session.metadata.get("healed_players", {})
        life_supports = session.metadata.get("life_supports", {})

        # Doctor Tenma's Emergency Surgery pair calculation
        tenma_saved = set()
        tenma_pair = session.metadata.get("tenma_surgery")
        if tenma_pair:
            a, b = tenma_pair
            
            def would_die(pid):
                pstate = session.players.get(pid)
                if not pstate or not pstate.alive:
                    return False
                if pid not in pending_kills:
                    return False
                
                # Check protections
                sources = pending_kills[pid]
                ignore_protection = any(src in ["tosen_kill", "light_guess", "bang_kill", "frieza_golden_kill"] or "ignore_protection" in src for src in sources)
                if ignore_protection:
                    return True
                    
                if pid in healed_players:
                    return False
                if pid in session.metadata.get("flying_thunder_counters", {}):
                    return False
                if pid in session.metadata.get("magical_barriers", {}):
                    return False
                    
                return True

            a_dies = would_die(a)
            b_dies = would_die(b)
            
            if a_dies != b_dies:
                if a_dies:
                    tenma_saved.add(a)
                if b_dies:
                    tenma_saved.add(b)

        for target_id, sources in list(pending_kills.items()):
            target_state = session.players.get(target_id)
            if not target_state or not target_state.alive:
                continue

            # 0. Tobirama's Flying Thunder Counter
            flying_thunder_counters = session.metadata.get("flying_thunder_counters", {})
            if target_id in flying_thunder_counters:
                tobirama_id = flying_thunder_counters[target_id]
                
                # Find all attackers targeting this player tonight
                attackers = []
                for pid, action in session.night_actions.items():
                    if pid == target_id:
                        continue
                    pstate = session.players.get(pid)
                    if not pstate:
                        continue
                    t_id = action.get("target_id")
                    targets = action.get("targets", ())
                    if t_id == target_id or target_id in targets or action.get("controlled_vote_target") == target_id:
                        is_attacker = False
                        if pstate.role_key in ("frieza", "upper_moon", "makima", "light_yagami", "levi_ackerman", "kishibe"):
                            is_attacker = True
                        elif pstate.faction in (RoleFaction.VILLAIN.value, RoleFaction.NEUTRAL.value):
                            is_attacker = True
                        
                        if is_attacker and pid not in attackers:
                            attackers.append(pid)
                            
                # Handle unstoppable sources that might not be in night_actions tonight
                for src in sources:
                    if src == "devils_pen_kill":
                        for pid, pstate in session.players.items():
                            if pstate.role_key == "light_yagami" and pid not in attackers:
                                attackers.append(pid)
                    elif src == "gates_of_babylon":
                        for pid, pstate in session.players.items():
                            if pstate.role_key == "gilgamesh" and pid not in attackers:
                                attackers.append(pid)
                                
                # Notify Tobirama Senju of the attackers (always runs)
                if self.bot:
                    tobirama_member = guild.get_member(tobirama_id) if guild else None
                    if tobirama_member:
                        attackers_str = ", ".join([f"<@{atk}>" for atk in attackers]) if attackers else "an unknown force"
                        msg = (
                            f"{get_emoji('zap')} **Flying Thunder Counter Triggered!**\n"
                            f"You countered the attack on <@{target_id}>.\n"
                            f"{get_emoji('detective')} **Attacker(s) detected:** {attackers_str}"
                        )
                        self.bot.message_queue.send(tobirama_member, msg)
                        
                # Determine if there's any unstoppable/ignore-protection attack
                has_unstoppable = False
                unpreventable_sources = ("devils_pen_kill", "gates_of_babylon", "bang_kill")
                if any(src in unpreventable_sources for src in sources):
                    has_unstoppable = True
                    
                if "levi_kill" in sources:
                    for pid, pstate in session.players.items():
                        if pstate.role_key == "levi_ackerman" and pstate.metadata.get("levi_precision_active"):
                            has_unstoppable = True
                            
                if "frieza_kill" in sources:
                    for pid, pstate in session.players.items():
                        if pstate.role_key == "frieza" and pstate.metadata.get("golden_frieza"):
                            has_unstoppable = True
                            
                if "tosen_kill" in sources or "kishibe_alert_kill" in sources:
                    has_unstoppable = True
                    
                if not has_unstoppable:
                    # Also notify the target player they were saved
                    if self.bot:
                        target_member = guild.get_member(target_id) if guild else None
                        if target_member:
                            self.bot.message_queue.send(
                                target_member,
                                f"{get_emoji('zap')} **Flying Thunder Counter!** You were targeted for an attack tonight, but Tobirama Senju intercepted and nullified it!"
                            )
                    # Register the save in heals history and skip further damage processing
                    session.metadata.setdefault("heals_history", {}).setdefault(night_num, {})[target_id] = True
                    continue

            # Check unpreventable kills (Devils Pen/Apocalypse/Bang)
            unpreventable_sources = ("devils_pen_kill", "gates_of_babylon", "bang_kill")
            if any(src in unpreventable_sources for src in sources):
                target_mem = guild.get_member(target_id) if guild else None
                target_name = target_mem.display_name if target_mem else f"User {target_id}"
                cause_key = next(src for src in unpreventable_sources if src in sources)
                if cause_key == "bang_kill":
                    death_msg = f"{get_emoji('makima')} **{target_name} was blown to pieces by an invisible force.**"
                else:
                    death_msg = get_death_message(cause_key, target_name)
                
                # Determine killer_id
                killer_id = None
                if cause_key == "devils_pen_kill":
                    killer_id = next((pid for pid, pstate in session.players.items() if pstate.role_key == "light_yagami"), None)
                elif cause_key == "gates_of_babylon":
                    killer_id = next((pid for pid, pstate in session.players.items() if pstate.role_key == "gilgamesh"), None)
                elif cause_key == "bang_kill":
                    killer_id = next((pid for pid, pstate in session.players.items() if pstate.role_key == "makima"), None)
                
                await self.eliminate_player(session.game_handle.game_id, target_id, "darkness", death_message=death_msg, killer_id=killer_id)
                continue

            # Determine if this attack ignores protection (Levi's Precision strike)
            ignore_protection = False
            if "levi_kill" in sources:
                for pid, pstate in session.players.items():
                    if pstate.role_key == "levi_ackerman":
                        if pstate.metadata.get("levi_precision_active"):
                            ignore_protection = True
                            pstate.metadata["levi_precision_active"] = False

            if "frieza_kill" in sources:
                for pid, pstate in session.players.items():
                    if pstate.role_key == "frieza":
                        if pstate.metadata.get("golden_frieza"):
                            ignore_protection = True

            if "tosen_kill" in sources:
                ignore_protection = True

            if "kishibe_alert_kill" in sources:
                ignore_protection = True

            # 1. Frieren's Hidden status
            if target_state.metadata.get("hidden_until_night") == night_num and not ignore_protection:
                continue

            # 2. Frieren's Magical Barrier
            opposite_barrier = False
            if target_id in magical_barriers and not ignore_protection:
                target_faction = target_state.faction
                for src in sources:
                    src_faction = None
                    if src in ("mafia_strike", "frieza_kill", "demon_strike", "upper_moon"):
                        src_faction = RoleFaction.VILLAIN.value
                    elif src in ("levi_kill",):
                        src_faction = RoleFaction.HERO.value
                    
                    if src_faction:
                        if target_faction == RoleFaction.HERO.value and src_faction == RoleFaction.VILLAIN.value:
                            opposite_barrier = True
                        elif target_faction == RoleFaction.VILLAIN.value and src_faction == RoleFaction.HERO.value:
                            opposite_barrier = True
                        elif target_faction == "Neutral":
                            opposite_barrier = True
            
            if opposite_barrier:
                session.metadata.setdefault("heals_history", {}).setdefault(night_num, {})[target_id] = True
                continue

            # (Water Wall check removed, now handled by Flying Thunder Counter above)

            # 4. Doctor Tenma heal protection
            if target_id in healed_players and not ignore_protection:
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
                                        self.bot.message_queue.send(
                                            doc_member,
                                            f"{get_emoji('shield')} **Compassion Successful!** You saved <@{target_id}> from an attack! "
                                            f"Saves: **{doc_saves}/3**."
                                        )
                                    except Exception:
                                        pass
                continue

            # 5. Doctor Tenma Emergency Surgery link save (prevents death via medical link)
            if target_id in tenma_saved:
                mafia_ch_id = session.metadata.get("mafia_channel_id")
                if mafia_ch_id:
                    ch = self.bot.get_channel(mafia_ch_id)
                    if ch:
                        self.bot.message_queue.send(
                            ch,
                            f"🩺 **Emergency Surgery Successful!** <@{target_id}> was saved from fatal injuries by Doctor Tenma's medical link!"
                        )
                # Notify Tenma
                tenma_id = session.metadata.get("tenma_doctor_id")
                if tenma_id:
                    tenma_state = session.players.get(tenma_id)
                    if tenma_state:
                        doc_saves = tenma_state.metadata.get("saves_count", 0) + 1
                        tenma_state.metadata["saves_count"] = doc_saves
                        
                        guild = self.bot.get_guild(session.game_handle.guild_id) if (self.bot and session.game_handle) else None
                        if guild:
                            tenma_member = guild.get_member(tenma_id)
                            if tenma_member:
                                try:
                                    self.bot.message_queue.send(
                                        tenma_member,
                                        f"{get_emoji('shield')} **Compassion Successful!** Your medical link saved <@{target_id}> from death tonight! "
                                        f"Saves: **{doc_saves}/3**."
                                    )
                                except Exception:
                                    pass
                continue

            # Check modular role-specific survival passives (Muzan, Mahoraga)
            if "tosen_kill" in sources:
                # Tōsen's absolute judgment bypasses all death-evasion passives
                pass
            elif session.metadata.get("zoltraak_active") and target_state.faction != RoleFaction.HERO.value:
                # Zoltraak disables passives of all opposing faction members (Villains and Neutrals)
                pass
            else:
                target_role_cls = role_registry.get(target_state.role_key)
                target_role_inst = target_role_cls()
                target_ctx = RoleContext(
                    game_id=session.game_handle.game_id,
                    guild_id=session.game_handle.guild_id,
                    user_id=target_id,
                    payload={"session": session},
                    bot=self.bot
                )
                if await target_role_inst.resolve_protection(target_ctx, sources):
                    continue

            # Eliminate player — pick the flavor line for whichever kill source landed
            # (config.DEATH_MESSAGES), so every role's kill gets real variety instead
            # of only the first few hardcoded sources.
            target_mem = guild.get_member(target_id) if guild else None
            target_name = target_mem.display_name if target_mem else f"User {target_id}"
            cause_key = sources[-1] if sources else None
            death_msg = get_death_message(cause_key, target_name)
            
            # Trace killer_id from cause_key and session.night_actions
            killer_id = None
            if cause_key:
                for pid, action in session.night_actions.items():
                    if pid == target_id:
                        continue
                    t_id = action.get("target_id")
                    targets = action.get("targets", ())
                    if t_id == target_id or target_id in targets or action.get("controlled_vote_target") == target_id:
                        pstate = session.players.get(pid)
                        if pstate:
                            match = False
                            if pstate.role_key == "frieza" and cause_key == "frieza_kill":
                                match = True
                            elif pstate.role_key == "upper_moon" and cause_key in ("demon_strike", "upper_moon"):
                                match = True
                            elif pstate.role_key == "tosen" and cause_key == "tosen_kill":
                                match = True
                            elif pstate.role_key == "levi_ackerman" and cause_key == "levi_kill":
                                match = True
                            elif pstate.role_key == "kishibe" and cause_key == "kishibe_alert_kill":
                                match = True
                            elif pstate.role_key == "makima" and cause_key == "bang_kill":
                                match = True
                            elif pstate.role_key == "light_yagami" and cause_key in ("light_guess", "devils_pen_kill"):
                                match = True
                            elif pstate.faction == RoleFaction.VILLAIN.value and cause_key == "mafia_strike":
                                match = True
                            
                            if match:
                                killer_id = pid
                                break
                                
            await self.eliminate_player(session.game_handle.game_id, target_id, cause_key or "attack", death_message=death_msg, killer_id=killer_id)

            # Tōsen execution faction penalty
            if "tosen_kill" in sources:
                for tosen_id, tosen_state in session.players.items():
                    if tosen_state.role_key == "tosen" and tosen_state.alive:
                        tosen_state.metadata["detained_player_id"] = None
                        if target_state.faction == RoleFaction.HERO.value:
                            tosen_state.metadata["lost_execution_ability"] = True
                            tosen_state.metadata["executions_left"] = 0
                            async def _notify_tosen_penalty(eng=self, s=session, t_id=tosen_id):
                                g = eng.bot.get_guild(s.game_handle.guild_id) if eng.bot else None
                                m = g.get_member(t_id) if g else None
                                if m:
                                    try:
                                        eng.bot.message_queue.send(m, f"{get_emoji('warning')} **Judicial Penalty!** You executed a fellow **Vanguard** member. You have permanently lost the ability to execute players.")
                                    except Exception:
                                        pass
                            asyncio.create_task(_notify_tosen_penalty())
                        else:
                            execs = tosen_state.metadata.setdefault("executions_left", 3)
                            tosen_state.metadata["executions_left"] = max(0, execs - 1)
                            async def _notify_tosen_exec(eng=self, s=session, t_id=tosen_id, ex=max(0, tosen_state.metadata.get("executions_left", 3) - 1)):
                                g = eng.bot.get_guild(s.game_handle.guild_id) if eng.bot else None
                                m = g.get_member(t_id) if g else None
                                if m:
                                    try:
                                        eng.bot.message_queue.send(m, f"🌑 **Execution Complete.** Executions remaining: **{ex}/3**.")
                                    except Exception:
                                        pass
                            asyncio.create_task(_notify_tosen_exec())
                        break

        # Check Frieren's Ancient Binding
        ancient_bindings = session.metadata.get("ancient_bindings", {})
        for frieren_id, bound_pair in list(ancient_bindings.items()):
            if len(bound_pair) < 2:
                continue
            p1, p2 = bound_pair[0], bound_pair[1]
            p1_state = session.players.get(p1)
            p2_state = session.players.get(p2)
            p1_died = p1 in session.metadata.get("dead_this_round", [])
            p2_died = p2 in session.metadata.get("dead_this_round", [])
            
            if p1_died and not p2_died and p2_state and p2_state.alive:
                p2_state.metadata["hidden_until_night"] = night_num + 1
                frieren_state = session.players.get(frieren_id)
                if frieren_state:
                    frieren_state.metadata["frieren_binding_cooldown_until_day"] = session.metadata.get("day_num", 1) + 2
            elif p2_died and not p1_died and p1_state and p1_state.alive:
                p1_state.metadata["hidden_until_night"] = night_num + 1
                frieren_state = session.players.get(frieren_id)
                if frieren_state:
                    frieren_state.metadata["frieren_binding_cooldown_until_day"] = session.metadata.get("day_num", 1) + 2

        # Check Levi's Survivor's Guilt
        for pid, pstate in session.players.items():
            if pstate.role_key == "levi_ackerman" and pstate.alive:
                for dead_id in session.metadata.get("dead_this_round", []):
                    dead_pstate = session.players.get(dead_id)
                    if dead_pstate and dead_pstate.faction == RoleFaction.HERO.value:
                        kill_info = pending_kills.get(dead_id)
                        if kill_info and "levi_kill" in kill_info:
                            pstate.metadata["exhausted_until_day"] = session.metadata.get("day_num", 1) + 1
                            pstate.metadata["exhausted_until_night"] = session.metadata.get("night_num", 1) + 1
                            mafia_ch_id = session.metadata.get("mafia_channel_id")
                            if mafia_ch_id:
                                ch = self.bot.get_channel(mafia_ch_id)
                                if ch:
                                    self.bot.message_queue.send(
                                        ch,
                                        f"{get_emoji('sword')} **Survivor's Guilt!** Levi Ackerman (<@{pid}>) killed a Town member and is now Exhausted. They cannot speak or vote tomorrow."
                                    )

        # Tobirama's Master Sensor passive feedback
        for pid, pstate in session.players.items():
            if pstate.role_key == "tobirama_senju" and pstate.alive:
                tobirama_visits = night_visits.get(pid, [])
                if tobirama_visits:
                    visitors_str = ", ".join([f"<@{v}>" for v in tobirama_visits])
                    msg = f"{get_emoji('wave')} **Master Sensor:** You sensed chakra from the following players visiting you tonight: {visitors_str}."
                else:
                    msg = f"{get_emoji('wave')} **Master Sensor:** You did not sense anyone visiting you tonight."
                member = guild.get_member(pid) if guild else None
                if member:
                    self.bot.message_queue.send(member, msg)

        # Set dead_last_night for Maomao
        session.metadata["dead_last_night"] = list(session.metadata.get("dead_this_round", []))

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
                    self.bot.message_queue.send(member, f"{get_emoji('night')} {get_inaction_message()}")
                except Exception:
                    pass
                continue

            # Roleblocked feedback
            is_blocked = actor_state.metadata.get("roleblocked") and not (actor_state.role_key == "frieza" and actor_state.metadata.get("golden_frieza"))
            if is_blocked:
                try:
                    self.bot.message_queue.send(member, f"{get_emoji('cross')} **Your action failed because you were roleblocked tonight!**")
                except Exception:
                    pass
                continue

            # Modular role feedback
            role_cls = role_registry.get(actor_state.role_key)
            role_inst = role_cls()
            context = RoleContext(
                game_id=session.game_handle.game_id,
                guild_id=session.game_handle.guild_id,
                user_id=actor_id,
                target_id=payload.get("target_id"),
                targets=payload.get("targets", ()),
                payload={**payload, "session": session},
                bot=self.bot
            )
            try:
                # If the feedback was already sent as an embed in the resolution phase, skip it here
                if "result" in payload:
                    continue
                feedback = await role_inst.get_night_feedback(context)
                if feedback:
                    self.bot.message_queue.send(member, feedback)
            except Exception:
                logger.exception("Failed to get night feedback for user %s", actor_id)

        # Clear temp variables
        for pstate in session.players.values():
            pstate.metadata.pop("disguised_faction", None)
            pstate.metadata.pop("disguised_category", None)
            pstate.metadata.pop("nullified", None)
            pstate.metadata.pop("black_divider_nullified", None)
            pstate.metadata.pop("invisible", None)

        session.metadata.pop("pending_kills", None)
        session.metadata.pop("healed_players", None)
        session.metadata.pop("bungee_gum_links", None)
        session.metadata.pop("devil_union_active", None)
        session.metadata.pop("zoltraak_active", None)
        session.metadata.pop("tenma_surgery", None)
        session.metadata.pop("tenma_doctor_id", None)

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
                desc_parts = [
                    f"**Muzan Kibutsuji** has infected you with his blood!\n\n"
                    f"**Your New Role:** {role_display}\n"
                    f"**Your New Faction:** Villain (Mafia)\n\n"
                    f"You now win with the Mafia. Your old role and abilities are gone.\n"
                    f"You can now communicate with your fellow Mafia members by sending me DMs."
                ]
                if role_meta.get("active_ability"):
                    desc_parts.append(f"• **Active Ability:** {role_meta['active_ability']}")
                if role_meta.get("passive_ability"):
                    desc_parts.append(f"• **Passive Ability:** {role_meta['passive_ability']}")

                convert_layout = build_v2_layout(
                    title=f"{get_emoji('muzan_kibutsuji')} You Have Been Transformed!",
                    description="\n\n".join(desc_parts),
                    color=discord.Color.dark_red(),
                )
                self.bot.message_queue.send(converted_member, view=convert_layout)
                self.bot.message_queue.send(converted_member, f"{get_emoji('group')} **Your Fellow Mafia Members:** {mafia_list_str}")

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
                    self.bot.message_queue.send(
                        member,
                        f"{get_emoji('muzan_kibutsuji')} **New Mafia Member!** <@{converted_id}> has been transformed into "
                        f"a **{role_display}** by Muzan Kibutsuji and is now on your side!"
                    )
                except Exception:
                    pass

    async def _update_channel_mute(self, channel: discord.TextChannel, session: GameSession, mute: bool) -> None:
        """Sets message-sending overrides on `#mafia` text channel using default_role."""
        try:
            guild = channel.guild
            day_num = session.metadata.get("day_num", 1)
            import config
            
            # 1. Update default_role override
            default_ow = channel.overwrites.get(guild.default_role)
            target_send = False if mute else True
            if not default_ow or default_ow.send_messages != target_send or default_ow.read_messages != False:
                await channel.set_permissions(guild.default_role, read_messages=False, send_messages=target_send)

            # 2. Selectively update player overrides only when necessary
            for pid, pstate in session.players.items():
                if pstate.alive:
                    member = guild.get_member(pid)
                    if not member:
                        try:
                            member = await guild.fetch_member(pid)
                        except discord.NotFound:
                            continue
                    
                    current_ow = channel.overwrites.get(member)
                    if pid in config.ADMIN_IDS:
                        if not current_ow or current_ow.send_messages != True:
                            await channel.set_permissions(member, read_messages=True, send_messages=True)
                    else:
                        is_wounded = pstate.metadata.get("wounded_until_day") == day_num
                        is_exhausted = pstate.metadata.get("exhausted_until_day") == day_num
                        if is_wounded or is_exhausted:
                            if not current_ow or current_ow.send_messages != False:
                                await channel.set_permissions(member, read_messages=True, send_messages=False)
                        else:
                            target_player_send = False if mute else True
                            if not current_ow or current_ow.send_messages != target_player_send:
                                await channel.set_permissions(member, read_messages=True, send_messages=target_player_send)

            # Non-player admins can also speak
            for admin_id in config.ADMIN_IDS:
                if admin_id not in session.players:
                    admin_member = guild.get_member(admin_id)
                    if not admin_member:
                        try:
                            admin_member = await guild.fetch_member(admin_id)
                        except discord.HTTPException:
                            continue
                    if admin_member:
                        current_ow = channel.overwrites.get(admin_member)
                        if not current_ow or current_ow.send_messages != True:
                            await channel.set_permissions(admin_member, read_messages=True, send_messages=True)
        except Exception:
            logger.exception("Failed to update channel mute overrides.")

    async def _update_channel_mute_trial(self, channel: discord.TextChannel, session: GameSession, defendant_id: int) -> None:
        """Mutes everyone except the player currently defending on the stand."""
        try:
            guild = channel.guild
            day_num = session.metadata.get("day_num", 1)
            import config
            
            # 1. Mute default_role
            default_ow = channel.overwrites.get(guild.default_role)
            if not default_ow or default_ow.send_messages != False or default_ow.read_messages != False:
                await channel.set_permissions(guild.default_role, read_messages=False, send_messages=False)

            # 2. Setup standard players to inherit from default_role (send_messages=None)
            for pid, pstate in session.players.items():
                if pstate.alive and pid != defendant_id:
                    member = guild.get_member(pid)
                    if not member:
                        try:
                            member = await guild.fetch_member(pid)
                        except discord.NotFound:
                            continue
                    
                    current_ow = channel.overwrites.get(member)
                    if pid in config.ADMIN_IDS:
                        if not current_ow or current_ow.send_messages != True:
                            await channel.set_permissions(member, read_messages=True, send_messages=True)
                    else:
                        is_wounded = pstate.metadata.get("wounded_until_day") == day_num
                        is_exhausted = pstate.metadata.get("exhausted_until_day") == day_num
                        if is_wounded or is_exhausted:
                            if not current_ow or current_ow.send_messages != False:
                                await channel.set_permissions(member, read_messages=True, send_messages=False)
                        else:
                            if not current_ow or current_ow.send_messages != False:
                                await channel.set_permissions(member, read_messages=True, send_messages=False)

            # 3. Unmute the defendant explicitly
            defendant = guild.get_member(defendant_id)
            if not defendant:
                try:
                    defendant = await guild.fetch_member(defendant_id)
                except discord.NotFound:
                    defendant = None
            if defendant:
                def_state = session.players.get(defendant_id)
                is_wounded = def_state.metadata.get("wounded_until_day") == day_num if def_state else False
                is_exhausted = def_state.metadata.get("exhausted_until_day") == day_num if def_state else False
                
                current_ow = channel.overwrites.get(defendant)
                if defendant_id in config.ADMIN_IDS:
                    if not current_ow or current_ow.send_messages != True:
                        await channel.set_permissions(defendant, read_messages=True, send_messages=True)
                elif is_wounded or is_exhausted:
                    if not current_ow or current_ow.send_messages != False:
                        await channel.set_permissions(defendant, read_messages=True, send_messages=False)
                else:
                    if not current_ow or current_ow.send_messages != True:
                        await channel.set_permissions(defendant, read_messages=True, send_messages=True)

            # Non-player admins can also speak
            for admin_id in config.ADMIN_IDS:
                if admin_id not in session.players:
                    admin_member = guild.get_member(admin_id)
                    if not admin_member:
                        try:
                            admin_member = await guild.fetch_member(admin_id)
                        except discord.HTTPException:
                            continue
                    if admin_member:
                        current_ow = channel.overwrites.get(admin_member)
                        if not current_ow or current_ow.send_messages != True:
                            await channel.set_permissions(admin_member, read_messages=True, send_messages=True)
        except Exception:
            logger.exception("Failed to set trial mute overrides.")


def _stringify_keys(obj: Any) -> Any:
    """Recursively convert any dict with non-string keys to string keys (MongoDB requirement)."""
    if isinstance(obj, dict):
        return {str(k): _stringify_keys(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_stringify_keys(i) for i in obj]
    return obj


def serialize_session(session: GameSession) -> dict[str, Any]:
    from dataclasses import asdict
    players_dict = {}
    for uid, pstate in session.players.items():
        players_dict[str(uid)] = {
            "user_id": pstate.user_id,
            "role_key": pstate.role_key,
            "faction": pstate.faction,
            "alive": pstate.alive,
            "disconnected": pstate.disconnected,
            "vote_weight": pstate.vote_weight,
            "votes_cast": pstate.votes_cast,
            "night_actions_used": pstate.night_actions_used,
            "metadata": _stringify_keys(pstate.metadata),
        }

    return {
        "game_handle": {
            "game_id": session.game_handle.game_id,
            "guild_id": session.game_handle.guild_id,
            "channel_id": session.game_handle.channel_id,
            "host_id": session.game_handle.host_id,
            "state": session.game_handle.state,
            "created_at": session.game_handle.created_at,
        },
        "player_ids": list(session.player_ids),
        "min_players": session.min_players,
        "max_players": session.max_players,
        "created_at": session.created_at,
        "state": session.state.value,
        "phase": session.phase.value,
        "players": players_dict,
        "role_history": {str(k): v for k, v in session.role_history.items()},
        "votes": {str(k): v for k, v in session.votes.items()},
        "night_actions": {str(k): v for k, v in session.night_actions.items()},
        "winner_faction": session.winner_faction,
        "draw_reason": session.draw_reason,
        "metadata": _stringify_keys(session.metadata),
    }


def deserialize_session(data: dict[str, Any]) -> GameSession:
    from game_manager import ActiveGameHandle
    from game_engine import GameSession, GamePlayerState
    from utils.constants import GameState, GamePhase

    handle_data = data["game_handle"]
    game_handle = ActiveGameHandle(
        game_id=handle_data["game_id"],
        guild_id=handle_data["guild_id"],
        channel_id=handle_data["channel_id"],
        host_id=handle_data["host_id"],
        state=handle_data["state"],
        created_at=handle_data["created_at"],
    )

    players = {}
    for uid_str, pdata in data["players"].items():
        uid = int(uid_str)
        players[uid] = GamePlayerState(
            user_id=pdata["user_id"],
            role_key=pdata["role_key"],
            faction=pdata["faction"],
            alive=pdata["alive"],
            disconnected=pdata["disconnected"],
            vote_weight=pdata["vote_weight"],
            votes_cast=pdata["votes_cast"],
            night_actions_used=pdata["night_actions_used"],
            metadata=pdata["metadata"],
        )

    return GameSession(
        game_handle=game_handle,
        player_ids=tuple(data["player_ids"]),
        min_players=data["min_players"],
        max_players=data["max_players"],
        created_at=data["created_at"],
        state=GameState(data["state"]),
        phase=GamePhase(data["phase"]),
        players=players,
        role_history={int(k): v for k, v in data["role_history"].items()},
        votes={int(k): v for k, v in data["votes"].items()},
        night_actions={int(k): v for k, v in data["night_actions"].items()},
        winner_faction=data["winner_faction"],
        draw_reason=data["draw_reason"],
        metadata=data["metadata"],
    )
