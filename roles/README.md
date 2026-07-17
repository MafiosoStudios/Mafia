# Adding, Modifying, and Removing Mafioso Roles

This guide explains how to easily customize the roles in the Mafioso Bot. 

---

## How it works
The role system uses a **metadata-first design**. 
1. The **text metadata** (name, description, abilities, win condition) is stored in `roles/roles.json`.
2. The **gameplay logic** (night action, passive, win condition checks) is written in python classes under `roles/town.py`, `roles/mafia.py`, or `roles/neutral.py`.
3. The initialization script `roles/__init__.py` automatically loads these metadata files at startup and dynamically binds the details to the python classes.

---

## 1. How to Add a New Role (Example: Goku)

Let's say we want to add a new Town (Hero) role: **Goku** (key: `goku`).

### Step A: Declare in `roles/roles.json`
Add a new entry with the `goku` key:

```json
  "goku": {
    "name": "Son Goku",
    "faction": "Hero",
    "win_condition": "Help the town win. (Wins with Town)",
    "description": "A legendary Saiyan seeking the ultimate fight.",
    "active_ability": "Kamehameha (Target a player; if they are mafia, block/stun them. Has a 1 night cooldown).",
    "passive_ability": "Super Saiyan (75% chance to survive a night attack, disabled once triggered)."
  }
```

### Step B: Write the Logic class in `roles/town.py`
Create a subclass of `BaseRole` in `roles/town.py` and register it with `@role_registry.register`:

```python
@role_registry.register
class Goku(BaseRole):
    role_key: ClassVar[str] = "goku"
    priority: ClassVar[int] = 4  # Runs in standard action priority

    async def night_action(self, context: RoleContext) -> None:
        target_id = context.target_id
        if not target_id:
            return

        session = context.payload.get("session")
        player_state = session.players[context.user_id]
        
        # Check cooldown
        current_night = session.metadata.get("night_num", 1)
        last_used = player_state.metadata.get("last_kamehameha_night", -1)
        if last_used == current_night - 1:
            context.payload["error"] = "Kamehameha is on cooldown."
            return

        player_state.metadata["last_kamehameha_night"] = current_night
        
        target_player = session.players.get(target_id)
        if target_player and target_player.faction == RoleFaction.VILLAIN.value:
            # If villain, roleblock/stun them!
            target_player.metadata["roleblocked"] = True
            context.payload["log"] = f"Goku hit <@{target_id}> with Kamehameha, roleblocking them!"
        else:
            context.payload["log"] = f"Goku used Kamehameha on <@{target_id}> but they are not Mafia."

    def win_condition_met(self, alive_factions: frozenset[str], context: RoleContext) -> bool:
        return RoleFaction.HERO.value in alive_factions
```

### Step C: Update the registration files (Automatic!)
Since `roles/__init__.py` imports `roles/town.py` and automatically calls `bind_metadata_to_roles()`, **you are completely done!** The bot will dynamically assign Son Goku to players and bind all descriptions.

---

## 2. How to Modify a Role
* **To change text/description**: Edit `roles/roles.json`. No code changes required!
* **To change active logic or priority**: Edit the respective subclass's `night_action` method in `roles/town.py`, `roles/mafia.py`, or `roles/neutral.py`.

---

## 3. How to Remove a Role
1. Delete the class from `roles/town.py`/`mafia.py`/`neutral.py`.
2. Delete the metadata entry from `roles/roles.json`.
3. (Optional) Remove the role key from `roles/balance.json` configuration pools if you set explicit pools.
