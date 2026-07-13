# Anime Mafia

Anime-themed Discord Mafia bot built with Python 3.13, discord.py 2.x, SQLite, and aiosqlite.

## Current Status

- Core bot scaffold is in place.
- SQLite persistence covers players, games, game players, statistics, inventory, cosmetics, achievements, unlocked characters, and match history.
- Lobby, game, profile, shop, leaderboard, admin, and events cogs are wired.
- The engine and lobby flow persist game state to SQLite.
- Core commands are hybrid, so they work as both slash commands and prefix commands.
- Role content is intentionally deferred until you provide the roster.

## Run Requirements

Create a `.env` file from `.env.example` and set `DISCORD_TOKEN` before starting the bot.

## Command Examples

- Slash: `/lobby create`, `/profile`, `/shop inventory`
- Prefix: `!lobby create`, `!lobby join`, `!profile`, `!shop inventory`

## Project Layout

- `bot.py` - bot entrypoint and extension loader
- `config.py` - runtime configuration
- `database/` - database manager and dataclass models
- `cogs/` - slash command and event handlers
- `views/` - Discord UI components
- `utils/` - shared helpers, constants, and role base classes
- `db/` - SQLite files
