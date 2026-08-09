# Mafioso Multi-Issue Implementation Plan

## Context

The Mafioso Discord bot has 12+ accumulated bugs, feature gaps, and design improvements that need addressing in a coordinated sweep. The codebase is a Python `discord.py` bot with a `game_engine.py` (3769 lines) handling game flow, `roles/` modules defining abilities, `ui/` (Component V2 LayoutViews), and `config.py` centralizing emojis/images. No test infrastructure exists currently.

This plan fixes all reported issues, adds aura/reveal animations, normalizes DM styling, restructures message ordering, and creates temporary per-role validation tests.

---

## Implementation Order (9 phases, dependency-driven)

### Phase 0 — Foundation & Config (prerequisite for everything)
**Files:** `config.py`, `utils/helpers.py`

**Goal:** Centralize aura GIFs in config.py and add aura-queue + DM-builder helpers.

#### 0A. Add aura GIF placeholders to `config.py`
Add to `EVENT_IMAGES` (after existing entries, ~line 229):
```python
"blackbeard_tremor": "",       # placeholder — user fills later
"light_devils_ink": "",        # placeholder
"makima_contract": "",         # placeholder
"mahoraga_transform": "",      # placeholder
"gilgamesh_transform": "",     # placeholder
"tenma_save": "",              # placeholder
"ayanokoji_reveal": "",        # placeholder
```
Also add corresponding `get_event_image` keys and expose them via a `get_aura_image(key)` convenience function if desired (or just use `get_event_image` directly since it already handles empty strings).

#### 0B. Add aura-queue helpers to `utils/helpers.py`
Add two functions:
```python
def queue_aura(session, title: str, description: str, image_url: str | None = None) -> None:
    """Appends a channel aura embed to session metadata for display at day transition."""
    session.metadata.setdefault("aura_queue", []).append({
        "title": title,
        "description": description,
        "image_url": image_url,
    })

def build_aura_embed(entry: dict) -> discord.ui.LayoutView:
    """Builds a component-v2 aura embed from a queue entry."""
    from ui import build_v2_layout
    return build_v2_layout(
        title=entry["title"],
        description=entry["description"],
        image_url=entry.get("image_url"),
        color=discord.Color.from_rgb(255, 255, 255),
    )
```

#### 0C. Add `send_component_dm` helper to `utils/helpers.py`
A reusable helper for all role → player DMs using Component V2 (replaces scattered `message_queue.send(member, text)` calls).
```python
async def send_component_dm(bot, member: discord.Member, *, title: str, description: str, color: discord.Color = ..., image_url: str | None = None) -> None:
    from ui import build_v2_layout
    layout = build_v2_layout(title=title, description=description, color=color, image_url=image_url)
    try:
        bot.message_queue.send(member, view=layout)
    except Exception:
        logger.exception("Failed to send component DM to %s", member.id)
```

---

### Phase 1 — Blackbeard fixes (#1, #7)
**Files:** `roles/mafia.py`, `config.py`

#### 1A. Fix BB Tremor: remove immediate public dialogue, queue aura instead
In `BlackbeardTremorFruit.execute` (~line 120–129):
- **Remove** the immediate `message_queue.send(ch, dialogue)` call (the plain-text announcement).
- **Add** an aura queue entry via `queue_aura(session, ...)` with:
  - `title`: `f"{get_emoji('blackbeard')} ZEHAHAHA! THE EARTHQUAKE IS SHAKING THE LOBBY!"`
  - `description`: The same dramatic flavor text.
  - `image_url`: `get_event_image("blackbeard_tremor")` (placeholder gif).

#### 1B. Ensure BB gets a DM confirming tremor usage
The `get_night_feedback` at line 144–151 already returns text for tremor. Since Phase 4 will wrap all feedback in component embeds, this is handled automatically — no extra change needed here.

---

### Phase 2 — Tenma, Ayano, Makima, BB, Light, Mahoraga, Gilgamesh ordering (#5, #6, #7, #8)
**Files:** `game_engine.py`, `roles/mafia.py`, `roles/neutral.py`, `roles/town.py`

#### 2A. Tenma save → move channel message to aura slot (#5)
In `_resolve_night_logic` at ~line 3266–3309 (the `if target_id in tenma_saved:` block):
- **Replace** the immediate `message_queue.send(ch, f"{get_emoji('shield')} **Emergency Surgery Successful**, ...")` with:
  ```python
  queue_aura(
      session,
      title=f"{get_emoji('shield')} Emergency Surgery Successful",
      description=f"<@{target_id}> was saved from fatal injuries by Doctor Tenma!",
      image_url=get_event_image("tenma_save"),
  )
  ```
- Keep the Tenma DM ("Compassion Successful") in place (will be component-ified in Phase 4).
- Keep the attacker anonymous DM in place.

#### 2B. Ayano public reveal → ensure position (aura slot after death messages) (#6)
In `_send_death_and_status_embeds` (~line 2393–2413): Move the Ayanokoji reveal block to AFTER the "other casualties" and BEFORE the status list. Currently it sits in that slot already (lines 2393–2413). Verify the ordering is:
1. Main death report embed
2. Other casualties embed
3. **Aura queue drain** (includes BB tremor, Tenma save, Ayano reveal)
4. Alive/dead status list

Restructure `_send_death_and_status_embeds` so that after sending the death report embed(s), we drain `session.metadata.pop("aura_queue", [])` and send each entry as a component-v2 embed. Then send the status list. The Ayanokoji reveal data (`session.metadata.pop("ayanokoji_public_reveal")`) should be queued as an aura entry instead of handled inline.

#### 2C. Makima president contract aura at trial moment (#7)
In `run_game_loop` at ~line 2073–2084 (the `elif def_state.role_key == "makima" and not ...pm_contract_activated` block):
- Replace the plain-text `message_queue.send` with a component-v2 layout embed (using `build_v2_layout`) with:
  - `title`: `f"{get_emoji('makima')} Prime Minister's Contract Activated!"`
  - `description`: the existing trigger text.
  - `image_url`: `get_event_image("makima_contract")` (placeholder gif).
  - `color`: `discord.Color.dark_red()`

#### 2D. Light Yagami Devil's Pen kill aura (#7)
In `_resolve_night_logic` at ~line 2939–2961 (the `devils_pen_deaths` processing loop):
- After adding `devils_pen_kill` to `pending_kills`, also queue an aura:
  ```python
  queue_aura(
      session,
      title=f"{get_emoji('light_yagami')} The Devil's Pen Has Claimed Another Soul",
      description=f"<@{pid}>'s name was written 3 nights ago. Right on schedule, their heart stopped.",
      image_url=get_event_image("light_devils_ink"),
  )
  ```

#### 2E. Mahoraga full adaptation aura (#8)
In `MahoragaAdaptation.execute` (neutral.py ~line 511–521) when `len(adapted) == 3`:
- Queue an aura:
  ```python
  queue_aura(
      session,
      title=f"{get_emoji('mahoraga')} WITH THIS WHEEL, I ADAPT TO ALL CREATION!",
      description=(
          "**Eight-Handled Sword Divergent Sila Divine General Mahoraga** has fully adapted to all three factions!\n\n"
          "• No faction can eliminate Mahoraga at night anymore.\n"
          "• The town can no longer vote Mahoraga out."
      ),
      image_url=get_event_image("mahoraga_transform"),
  )
  ```

#### 2F. Gilgamesh transformation aura (#8)
In `run_game_loop` at ~line 1604–1618 (the Gilgamesh transform check):
- **Move** this code INTO `_send_death_and_status_embeds` as an aura queue entry, so it's placed between death messages and the status list. Replace the inline `message_queue.send(mafia_channel, view=gilgamesh_layout)` with:
  ```python
  queue_aura(
      session,
      title=f"{get_emoji('gilgamesh')} KNEEL, MONGRELS! THE KING OF HEROES ASCENDS!",
      description=(
          "Gilgamesh has reclaimed every treasure and transformed into the **Horseman of Apocalypse**!\n"
          "Lynch him before the sun sets, or the **Gate of Babylon** will wipe every last soul from existence!"
      ),
      image_url=get_event_image("gilgamesh_transform"),
  )
  ```
- Remove the original inline send from `run_game_loop`.

#### 2G. Implement `_send_death_and_status_embeds` aura-drain slot
Restructure the function to:
1. Send main death report embed ( mafia deaths + other casualties — keep the existing structure)
2. **Drain `session.metadata.pop("aura_queue", [])`**: for each entry, send a component-v2 embed.
3. Send alive/dead status list embed.

```python
# After the death report embeds:
aura_queue = session.metadata.pop("aura_queue", [])
for aura in aura_queue:
    aura_layout = build_2_layout(
        title=aura["title"],
        description=aura["description"],
        image_url=aura.get("image_url"),
        color=discord.Color.from_rgb(255, 255, 255),
    )
    try:
        await self.bot.message_queue.send(channel, view=aura_layout)
        await asyncio.sleep(2.5)
    except Exception as err:
        logger.error("Failed to send aura embed: %s", err)
```

---

### Phase 3 — Night Alive/Dead Embed & Ping Logic (#9, #10)
**Files:** `game_engine.py`

#### 3A. Extract reusable `_build_alive_dead_embed(session, guild)` helper
In `game_engine.py`, create a method that builds the alive/dead status embed using **display names** (no `<@id>` mentions) to avoid pings:
```python
async def _build_alive_dead_embed(self, session, guild, *, title_prefix: str = "") -> ui.LayoutView:
    alive_lines = []
    dead_lines = []
    for pid, pstate in session.players.items():
        member = guild.get_member(pid)
        name = member.display_name if member else f"User {pid}"
        if pstate.alive:
            alive_lines.append(f"• {name}")
        else:
            role_meta = roles.ROLES_METADATA.get(pstate.role_key or "", {})
            role_display = role_meta.get("name", pstate.role_key or "Unknown")
            emoji = get_emoji(pstate.role_key) if pstate.role_key else ""
            dead_lines.append(f"• {name} ({emoji}{role_display})")
    
    desc = f"## Alive Players\n" + ("\n".join(alive_lines) if alive_lines else "None") + \
           "\n\n## Dead Players\n" + ("\n".join(dead_lines) if dead_lines else "None")
    
    return build_v2_layout(
        title=f"{title_prefix} Player Status",
        description=desc,
        color=discord.Color.blurple(),
        image_url="https://img.magnific.com/...",
    )
```

#### 3B. Use helper in `_send_death_and_status_embeds` (line 2415–2438)
Replace the inline status-embed code with `await self._build_alive_dead_embed(...)`.

#### 3C. Send alive/dead embed BEFORE night action embed (#9)
In `run_game_loop` night phase (~line 1507–1531), right before sending `night_view`:
```python
if not is_resume:
    alive_dead_layout = await self._build_alive_dead_embed(session, guild, title_prefix=f"Night {night_num}")
    await self.bot.message_queue.send(mafia_channel, view=alive_dead_layout)
    await asyncio.sleep(2)
```
This shows the current alive/dead list before the night action prompt.

#### 3D. Fix pings (#10)
- **Alive/dead status embeds**: The new `_build_alive_dead_embed` uses `display_name` (no `<@id>`), so pings are eliminated.
- **Day-transition alive ping**: In `run_game_loop`, when calling `_send_death_and_status_embeds` at day transition (~line 1598), send an alive-player ping line BEFORE the death embed:
  ```python
  alive_mentions = " ".join(f"<@{pid}>" for pid, ps in session.players.items() if ps.alive)
  await self.bot.message_queue.send(mafia_channel, f"{get_emoji('day')} **Day {session.metadata['day_num']} begins.** {alive_mentions}")
  ```
- **Game-start ping** (line 1452): Keep as-is (all players alive at start; needed for channel discovery).

---

### Phase 4 — DM Styling: Component V2 for ALL Role DMs (#3, #4)
**Files:** `game_engine.py`, `roles/mafia.py`, `roles/neutral.py`, `roles/town.py`

#### 4A. Remove the generic "Intel" DM block from `_resolve_night_logic` (line 2897–2917)
Delete the block:
```python
# Check L / Ayanokoji scan results and deliver to their DMs
if "result" in context.payload:
    ...
```
This block sends a duplicate "Intel" embed to every role that sets `payload["result"]` — causing double DMs (Asta, Tenma, L, Tobirama, Maomao, Frieren, etc.).

#### 4B. Convert the feedback loop DMs to Component V2 (line 3479–3523)
In the "Send outcome feedback DMs" loop, change:
```python
# OLD:
self.bot.message_queue.send(member, feedback)
```
to:
```python
# NEW:
role_meta = roles.ROLES_METADATA.get(actor_state.role_key or "", {})
role_display = role_meta.get("name", actor_state.role_key or "Unknown")
role_emoji = get_emoji(actor_state.role_key) or get_emoji("search")
layout = build_v2_layout(
    title=f"{role_emoji} {role_display} — Night Feedback",
    description=feedback,
    color=discord.Color.blue(),
)
self.bot.message_queue.send(member, view=layout)
```

#### 4C. Convert roleblocked/nullified/detained/union DMs to Component V2
In the action loop, convert the existing plain-text notification blocks to component-v2 embeds:
- **Roleblocked** (~line 2734–2747): already builds `build_v2_layout` ✓
- **Detained** (~line 2752–2765): already builds `build_v2_layout` ✓
- **Nullified** (~line 2771–2784): already builds `build_v2_layout` ✓
- **Devil Union** (~line 2804–2818): already builds `build_v2_layout` ✓
- **Invisible** (~line 2828–2842): already builds `build_v2_layout` ✓
- **Inaction message** (~line 3500–3503): currently plain text. Wrap in `build_v2_layout`.

#### 4D. Convert role-file DMs to Component V2
Scan roles files for `message_queue.send(member, text)` calls and wrap in component-v2:
- **MuzanRegen** (roles/mafia.py:342): wrap in `build_v2_layout`
- **Mahoraga adaptation shield** (roles/neutral.py:624): already uses DMs — convert
- **Tosen detain** (roles/town.py:853): currently plain text → wrap
- **Dazai nullified** (roles/town.py:1014): currently plain text → wrap

#### 4E. Convert the BB tremor public dialogue to Component V2
The old dialogue at roles/mafia.py:120–129 is replaced by the aura queue (Phase 1), so no DM conversion needed here.

---

### Phase 5 — Maomao Intelligence Potion Notification (#2)
**File:** `roles/town.py`

In `MaomaoBrewPotion.execute` under `potion_choice == "intelligence"` (~line 666–668):
After setting `target_player.vote_weight = 2`, add a notification to the target player:
```python
import discord
async def notify_intelligence(session=session, target_id=context.target_id, bot=context.bot):
    if bot:
        guild = bot.get_guild(session.game_handle.guild_id)
        target_member = guild.get_member(target_id) if guild else None
        if target_member:
            from utils.helpers import send_component_dm
            await send_component_dm(
                bot, target_member,
                title=f"{get_emoji('maomao')} Potion of Intelligence",
                description="You have been granted **+1 Vote** for tomorrow's vote phase! (Total weight: 2)",
                color=discord.Color.blue(),
            )
from utils.helpers import safe_create_task
safe_create_task(notify_intelligence(), "maomao_intelligence_notify")
```

---

### Phase 6 — Profile Command Redesign (#11)
**File:** `cogs/profile.py`

#### Current state (line 58–76):
Basic text-only v2 layout showing rank, level, gold, fav character, and match stats.

#### New design (dark luxury anime-card):
```
┌─────────────────────────────────────────────┐
│  🏆 <user_avatar_thumbnail>                 │
│  # <username>'s Dossier                     │
│  ──────────────────────                     │
│  ## ⚔️ Combat Record                        │
│  🔵 Wins: `X`  |  🔴 Losses: `Y`           │
│  🤝 Draws: `Z`  |  📊 Win Rate: `XX.X%`   │
│  🎮 Total Games: `N`                        │
│  ──────────────────────                     │
│  ## 📈 Progression                          │
│  👑 Rank: `Diamond 💠`  |  ⭐ Level: `42`   │
│  ████░░░░ 120/250 XP                       │
│  💰 Gold: `1,234`                           │
│  ──────────────────────                     │
│  ## 🎭 Favorite Character                   │
│  <:makima:...> **Makima** (Villain)         │
│  ──────────────────────                     │
│  -# Mafioso Dossier                         │
└─────────────────────────────────────────────┘
```

Implementation:
- Use `get_emoji()` for all stat labels (rank_bronze, xp, coin, level_up, etc.)
- Use `get_role_image(favorite_character)` for the fav character thumbnail
- Use rank badge images from `get_event_image()` or a new `PROFILE_BADGE_IMAGES` dict in config.py
- Add `color=discord.Color.from_rgb(10, 10, 18)` (deep dark)
- Add `thumbnail_url` = user avatar
- Use `small_footer()` for bottom text
- Use `bold()` and `subheading()` for sections

---

### Phase 7 — Game-End Reward DM Redesign (#12)
**File:** `game_engine.py` (lines 892–925)

#### Current state:
Inline `dm_desc` with text-based stats. `Your rewards :3` title.

#### New design (dark luxury anime-card):
```
┌─────────────────────────────────────────────────┐
│  🏆 <user_avatar_thumbnail>                     │
│  # MATCH COMPLETE                               │
│  ────────────────────                            │
│  ## 🎭 Your Role                                │
│  <:makima:...> **Makima** — Villain ⚔️         │
│  Status: ✅ Alive / ☠️ Eliminated               │
│  ────────────────────                            │
│  ## 🪙 Rewards Earned                           │
│  ✨ +150 XP  |  💰 +50 Gold                     │
│  ────────────────────                            │
│  ## 📈 Progression Update                       │
│  👑 Rank: `Gold 🥇` → `Gold 🥇`               │
│  ⭐ Level: `8` | ████░░░░ 120/250 XP           │
│  💰 Total Gold: `847`                           │
│  ────────────────────                            │
│  ⚡ LEVEL UP! → Level `9`                       │
│  🏷️ Promotion: `Platinum 💎`                   │
│  ────────────────────                            │
│  -# Mafioso Match Rewards                       │
└─────────────────────────────────────────────────┘
```

Implementation:
- Title: dynamic based on outcome — `"🏆 Match Victory!"` / `"💀 Defeat"` / `"🤝 Draw"`
- Add role emoji and name as a section
- Add "Alive" / "Eliminated" status badge
- Show rewards with ✨/💰 emojis
- Show progression with rank medal image, progress bar
- Level-up/rank-up as highlighted callout sections
- `image_url`: victory gif from `get_event_image("victory_hero")` / `victory_villain` / `victory_neutral` / `draw`
- Use `thumbnail_url`: user avatar

---

### Phase 8 — Patch Notes Update
**File:** `views/patchnotes_view.py`

Append a new entry to `PATCHES` (after v1.0.8):
```python
{
    "version": "1.0.9",
    "date": "<current date>",
    "title": "Version 1.0.9 — Aura System, DM Overhaul & Bug Fixes",
    "description": "...",
    "changes": [
        "**Blackbeard Tremor Fruit** — BB now receives a DM confirming usage; aura announcement in channel after death report",
        "**Maomao Intelligence Potion** — Target is now notified when granted +1 Vote via Potion of Intelligence",
        "**Asta Double DM Fix** — Removed duplicate Intel DMs; all role feedback now uses a single Component V2 embed",
        "**All Role DMs — Component V2** — Every role DM (roleblocked, nullified, detained, inaction, etc.) now uses styled V2 LayoutViews",
        "**Tenma Emergency Surgery** — Save message now appears in the aura slot (after death report, before alive/dead list) instead of during night resolution",
        "**Ayanokoji Public Reveal** — Positioned in the aura slot between death report and alive/dead status embed",
        "**Makima President Contract** — Now announced with a styled V2 embed + GIF when the contract saves her from lynching",
        "**Light Yagami Devil's Pen Kill** — Aura announced in channel when the delayed kill activates (3 nights after writing)",
        "**Mahoraga Full Adaptation** — Aura announcement when Mahoraga completes adaptation to all three factions",
        "**Gilgamesh Apocalypse Transform** — Aura now positioned in the aura slot (before alive/dead list, after death report)",
        "**Night Alive/Dead Embed** — An alive/dead status list is now sent before the night action embed every night",
        "**Ping Fix** — Alive/dead status embeds no longer ping players (uses display names); alive players are pinged at day transitions only",
        "**Profile Command Redesign** — Dark luxury anime-card with rank badges, avatar thumbnail, progress bar, and stat sections",
        "**Match Rewards DM Redesign** — Styled dark luxury card showing role played, rewards, progression, and victory/defeat visuals",
    ],
},
```

---

### Phase 9 — Temporary Per-Role Validation Tests
**Files:** `tests/roles/test_<role_key>.py` (one per role, ~27 files)

#### Infrastructure setup
- Install pytest: `uv add --dev pytest` (or `pip install pytest`)
- Create `tests/__init__.py` and `tests/roles/__init__.py`
- Create `tests/conftest.py` with shared fixtures:
  ```python
  import pytest
  from game_engine import GameSession, GamePlayerState
  from game_manager import ActiveGameHandle
  from utils.helpers import utcnow
  
  @pytest.fixture
  def mock_session():
      """Creates a minimal GameSession with n players, no Discord deps."""
      handle = ActiveGameHandle(
          game_id="test-game",
          guild_id=1,
          channel_id=1,
          host_id=1,
      )
      players = {}
      for i in range(1, 11):
          players[i] = GamePlayerState(user_id=i)
      session = GameSession(
          game_handle=handle,
          player_ids=tuple(range(1, 11)),
          min_players=5,
          max_players=15,
      )
      session.players = players
      session.metadata["night_num"] = 1
      session.metadata["day_num"] = 0
      return session
  
  @pytest.fixture
  def make_context():
      """Creates a RoleContext with minimal fields."""
      def _make(user_id, session, target_id=None):
          from utils.roles import RoleContext
          return RoleContext(
              game_id="test-game",
              guild_id=1,
              user_id=user_id,
              target_id=target_id,
              targets=(target_id,) if target_id else (),
              payload={"session": session},
              bot=None,
          )
      return _make
  ```

#### Test structure per role
Each `test_<role_key>.py` file:
1. Import the role class from `roles.town`, `roles.mafia`, or `roles.neutral`
2. Test `can_use()` with various conditions (cooldowns, use limits)
3. Test `get_eligible_targets()` (excludes self, excludes dead, etc.)
4. Test `execute()` → verify `session.metadata["pending_kills"]` / side effects
5. Test `get_night_feedback()` → verify returns non-None text

Example (`tests/roles/test_blackbeard.py`):
```python
def test_tremor_roleblocks_non_mafia(mock_session):
    """Tremor fruit should roleblock all non-Villain players."""
    # Set up factions
    mock_session.players[1].faction = "Villain"  # BB
    mock_session.players[2].faction = "Villain"  # Mafia teammate
    mock_session.players[3].faction = "Hero"     # Town
    mock_session.players[4].faction = "Neutral"  # Neutral
    mock_session.players[1].alive = True
    mock_session.players[2].alive = True
    mock_session.players[3].alive = True
    mock_session.players[4].alive = True
    
    bb = Blackbeard()
    ctx = make_context(1, mock_session)
    asyncio.run(bb.abilities[1].execute(ctx))  # TremorFruit
    
    assert not mock_session.players[1].metadata.get("roleblocked")  # BB not blocked
    assert not mock_session.players[2].metadata.get("roleblocked")  # Mafia not blocked
    assert mock_session.players[3].metadata.get("roleblocked")       # Town blocked
    assert mock_session.players[4].metadata.get("roleblocked")       # Neutral blocked

def test_tremor_cooldown(mock_session):
    """Tremor fruit should fail on second use."""
    mock_session.players[1].metadata["tremor_used"] = True
    bb = Blackbeard()
    can_use, reason = bb.abilities[1].can_use(mock_session, mock_session.players[1])
    assert not can_use
    assert "already been used" in reason
```

#### Run cycle
1. Create all 27 test files
2. Run `python -m pytest tests/roles/ -v`
3. Fix any import errors or test failures
4. Rerun until all pass
5. **Delete the entire `tests/` directory** (user requested temp validation only)

---

## Critical Files Summary

| File | Changes |
|------|---------|
| `config.py` | Add aura GIF placeholder keys to `EVENT_IMAGES` |
| `utils/helpers.py` | Add `queue_aura()`, `send_component_dm()` helpers |
| `game_engine.py` | Restructure `_send_death_and_status_embeds` (aura slot), add `_build_alive_dead_embed()`, add alive ping at day transition, send alive/dead embed before night view, remove generic Intel DM block, convert feedback DMs to component V2, add Gilgamesh/Devil Pen aura entries, refactor tenma/ayanokoji into aura queue |
| `roles/mafia.py` | BB tremor: remove immediate dialogue, queue aura; convert DMs to component V2 |
| `roles/neutral.py` | Mahoraga adapt-complete aura queue entry; convert DMs to component V2 |
| `roles/town.py` | Maomao intelligence potion notification; convert Tosen/Dazai DMs to component V2 |
| `cogs/profile.py` | Full profile card redesign (dark luxury anime-card) |
| `views/patchnotes_view.py` | Append v1.0.9 patch notes entry |
| `tests/roles/` | 27 temp test files (created, run, fixed, deleted) |

---

## Message Order Reference (After Implementation)

### Day Transition (when night ends → day begins)
1. **Ping alive players** → `Day X begins. @alive1 @alive2 ...`
2. **Death report embed** → `Day X - Death Report` (mafia deaths)
3. **Other casualties embed** → `Day X - Other Casualties` (non-mafia deaths)
4. **Aura queue drain** → BB tremor aura, Tenma save aura, Light Devil's Pen aura, Ayano reveal, Mahoraga adapt aura, Gilgamesh transform aura (as applicable)
5. **Alive/dead status embed** → `Day X - Player Status` (display names, no pings)

### Every Night
1. **Alive/dead status embed** → `Night X - Player Status` (display names, no pings)
2. **Night action embed** → `Night X` (action buttons)

### Trial (Lynch Verdict)
1. Verdict logs embed (if non-anonymous)
2. Verdict totals
3. **Outcome**: execution embed, immunity block, or Makima contract V2 embed with gif

---

## Verification Plan

After implementation:
1. **Syntax check**: `python -m py_compile game_engine.py roles/mafia.py roles/town.py roles/neutral.py cogs/profile.py`
2. **Import check**: `python -c "import game_engine; import roles; import config"`
3. **Run pytest suite** (Phase 9) — all pass, then delete tests
4. **Manual review**: Grep for any remaining `<@` mentions in status embeds (should find none)
5. **Grep for plain-text DM sends**: `grep -rn "message_queue.send(member, f" --include="*.py"` — should be minimal/none
6. **Verify patch notes**: read the new entry is well-formatted in PATCHES list
