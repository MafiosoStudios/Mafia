from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
from typing import Any

from config import PROJECT_ROOT, get_emoji

logger = logging.getLogger(__name__)

RANK_JSON_PATH = PROJECT_ROOT / "rank.json"

DEFAULT_RANK_CONFIG = {
    "levels": {
        "base_xp": 100,
        "growth_factor": 1.25,
        "max_level": 100
    },
    "ranks": [
        {"name": "Bronze", "min_xp": 0, "badge": "Bronze Ranks", "emoji_key": "rank_bronze", "color": "#CD7F32"},
        {"name": "Silver", "min_xp": 1000, "badge": "Silver Ranks", "emoji_key": "rank_silver", "color": "#C0C0C0"},
        {"name": "Gold", "min_xp": 3000, "badge": "Gold Ranks", "emoji_key": "rank_gold", "color": "#FFD700"},
        {"name": "Platinum", "min_xp": 6000, "badge": "Platinum Ranks", "emoji_key": "rank_platinum", "color": "#E5E4E2"},
        {"name": "Diamond", "min_xp": 10000, "badge": "Diamond Ranks", "emoji_key": "rank_diamond", "color": "#B9F2FF"},
        {"name": "Master", "min_xp": 16000, "badge": "Master Ranks", "emoji_key": "rank_master", "color": "#9932CC"},
        {"name": "Grandmaster", "min_xp": 25000, "badge": "Grandmaster Ranks", "emoji_key": "rank_grandmaster", "color": "#FF4500"},
        {"name": "Mafia Legend", "min_xp": 40000, "badge": "Mafia Legend", "emoji_key": "rank_legend", "color": "#FFD700"}
    ],
    "rewards": {
        "base_participation_xp": 100,
        "base_participation_gold": 40,
        "win_xp_bonus": 150,
        "win_gold_bonus": 60,
        "survival_xp_bonus": 50,
        "survival_gold_bonus": 25,
        "vote_xp_per_vote": 10,
        "vote_gold_per_vote": 5,
        "action_xp_per_action": 15,
        "action_gold_per_action": 8,
        "mvp_xp_bonus": 100,
        "mvp_gold_bonus": 50
    }
}


@dataclass(slots=True, frozen=True)
class LevelInfo:
    level: int
    xp_in_level: int
    xp_for_next: int
    total_xp: int


@dataclass(slots=True, frozen=True)
class MatchRewardResult:
    xp_gained: int
    gold_gained: int
    old_xp: int
    new_xp: int
    old_level: int
    new_level: int
    leveled_up: bool
    old_rank: str
    new_rank: str
    ranked_up: bool
    breakdown_lines: tuple[str, ...]


class ProgressionManager:
    _cached_config: dict[str, Any] | None = None

    @classmethod
    def get_config(cls) -> dict[str, Any]:
        if cls._cached_config is not None:
            return cls._cached_config

        if RANK_JSON_PATH.exists():
            try:
                with open(RANK_JSON_PATH, "r", encoding="utf-8") as f:
                    cls._cached_config = json.load(f)
                    logger.info("Successfully loaded rank.json configuration.")
                    return cls._cached_config
            except Exception:
                logger.exception("Failed to parse rank.json, using default progression config.")

        cls._cached_config = DEFAULT_RANK_CONFIG
        return cls._cached_config

    @classmethod
    def reload_config(cls) -> dict[str, Any]:
        cls._cached_config = None
        return cls.get_config()

    @classmethod
    def calculate_level_info(cls, total_xp: int) -> LevelInfo:
        config = cls.get_config()
        level_cfg = config.get("levels", DEFAULT_RANK_CONFIG["levels"])
        base_xp = float(level_cfg.get("base_xp", 100))
        growth = float(level_cfg.get("growth_factor", 1.25))
        max_level = int(level_cfg.get("max_level", 100))

        level = 1
        accumulated_xp = 0

        while level < max_level:
            req_for_this_level = int(base_xp * (level ** growth))
            if accumulated_xp + req_for_this_level > total_xp:
                xp_in_level = total_xp - accumulated_xp
                return LevelInfo(
                    level=level,
                    xp_in_level=xp_in_level,
                    xp_for_next=req_for_this_level,
                    total_xp=total_xp,
                )
            accumulated_xp += req_for_this_level
            level += 1

        # Max level reached
        req_for_last = int(base_xp * (max_level ** growth))
        return LevelInfo(
            level=max_level,
            xp_in_level=total_xp - accumulated_xp,
            xp_for_next=req_for_last,
            total_xp=total_xp,
        )

    @classmethod
    def get_rank_info(cls, total_xp: int) -> dict[str, Any]:
        config = cls.get_config()
        ranks = config.get("ranks", DEFAULT_RANK_CONFIG["ranks"])
        sorted_ranks = sorted(ranks, key=lambda r: int(r.get("min_xp", 0)), reverse=True)

        for r in sorted_ranks:
            if total_xp >= int(r.get("min_xp", 0)):
                return r

        return sorted_ranks[-1] if sorted_ranks else {"name": "Bronze", "badge": "Bronze Ranks", "emoji_key": "rank_bronze", "color": "#CD7F32"}

    @classmethod
    def calculate_rank_name(cls, total_xp: int) -> str:
        return str(cls.get_rank_info(total_xp).get("name", "Bronze"))

    @classmethod
    def format_progress_bar(cls, current: int, total: int, length: int = 10) -> str:
        if total <= 0:
            pct = 1.0
        else:
            pct = max(0.0, min(1.0, current / total))
        filled = int(round(pct * length))
        bar = "█" * filled + "░" * (length - filled)
        return f"`[{bar}]` `{current}/{total}` (`{int(pct * 100)}%`)"

    @classmethod
    def calculate_match_rewards(
        cls,
        *,
        old_xp: int,
        old_coins: int,
        is_winner: bool,
        is_alive: bool,
        votes_cast: int = 0,
        actions_performed: int = 0,
        is_mvp: bool = False,
    ) -> MatchRewardResult:
        config = cls.get_config()
        rewards_cfg = config.get("rewards", DEFAULT_RANK_CONFIG["rewards"])

        xp_gained = int(rewards_cfg.get("base_participation_xp", 100))
        gold_gained = int(rewards_cfg.get("base_participation_gold", 40))

        breakdown: list[str] = [
            f"• **Participation Base**: +{xp_gained} XP | +{gold_gained} Gold"
        ]

        if is_winner:
            w_xp = int(rewards_cfg.get("win_xp_bonus", 150))
            w_gold = int(rewards_cfg.get("win_gold_bonus", 60))
            xp_gained += w_xp
            gold_gained += w_gold
            breakdown.append(f"• **Victory Bonus**: +{w_xp} XP | +{w_gold} Gold")

        if is_alive:
            s_xp = int(rewards_cfg.get("survival_xp_bonus", 50))
            s_gold = int(rewards_cfg.get("survival_gold_bonus", 25))
            xp_gained += s_xp
            gold_gained += s_gold
            breakdown.append(f"• **Survival Bonus**: +{s_xp} XP | +{s_gold} Gold")

        if votes_cast > 0:
            v_xp_rate = int(rewards_cfg.get("vote_xp_per_vote", 10))
            v_gold_rate = int(rewards_cfg.get("vote_gold_per_vote", 5))
            v_xp = votes_cast * v_xp_rate
            v_gold = votes_cast * v_gold_rate
            xp_gained += v_xp
            gold_gained += v_gold
            breakdown.append(f"• **Votes Cast ({votes_cast})**: +{v_xp} XP | +{v_gold} Gold")

        if actions_performed > 0:
            a_xp_rate = int(rewards_cfg.get("action_xp_per_action", 15))
            a_gold_rate = int(rewards_cfg.get("action_gold_per_action", 8))
            a_xp = actions_performed * a_xp_rate
            a_gold = actions_performed * a_gold_rate
            xp_gained += a_xp
            gold_gained += a_gold
            breakdown.append(f"• **Actions Submitted ({actions_performed})**: +{a_xp} XP | +{a_gold} Gold")

        if is_mvp:
            m_xp = int(rewards_cfg.get("mvp_xp_bonus", 100))
            m_gold = int(rewards_cfg.get("mvp_gold_bonus", 50))
            xp_gained += m_xp
            gold_gained += m_gold
            breakdown.append(f"• **MVP Title Bonus**: +{m_xp} XP | +{m_gold} Gold")

        new_xp = old_xp + xp_gained
        old_lvl_info = cls.calculate_level_info(old_xp)
        new_lvl_info = cls.calculate_level_info(new_xp)
        leveled_up = new_lvl_info.level > old_lvl_info.level

        old_rank = cls.calculate_rank_name(old_xp)
        new_rank = cls.calculate_rank_name(new_xp)
        ranked_up = old_rank != new_rank

        return MatchRewardResult(
            xp_gained=xp_gained,
            gold_gained=gold_gained,
            old_xp=old_xp,
            new_xp=new_xp,
            old_level=old_lvl_info.level,
            new_level=new_lvl_info.level,
            leveled_up=leveled_up,
            old_rank=old_rank,
            new_rank=new_rank,
            ranked_up=ranked_up,
            breakdown_lines=tuple(breakdown),
        )
