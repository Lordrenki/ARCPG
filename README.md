# ARCPG

ARCPG is a production-ready Discord idle RPG bot with extraction-run gameplay loops inspired by high-stakes scavenging fiction.

## Stack

- **Language**: Python
- **Bot framework**: discord.py 2.x slash commands
- **DB**: PostgreSQL + SQLAlchemy + Alembic

## Folder Structure

```text
arkpg/
  bot/
    cogs/
      admin.py
      gameplay.py
    client.py
  core/
    config.py
    logging.py
  db/
    base.py
    models.py
    session.py
  game/
    constants.py
    deployments.py
    economy.py
    loot.py
    progression.py
    quest_catalog.py
    title_catalog.py
    service.py
alembic/
  versions/
    0001_init.py
    0002_progression_systems.py
tests/
  test_deployments.py
  test_economy.py
  test_loot.py
  test_profile.py
  test_trade.py
```

## New Major Features

### A) Earnable Titles
- 40+ gameplay-earned titles across Raider, Crafter, Trader, Expedition, Squad, PvP, Collector, Events.
- Hidden-title support (10+ hidden) and inspectable progress via rule functions.
- `/titles_list`, `/titles_inspect`, `/title_equip`.
- Profile now shows equipped title plus editable callsign and bio.

### B) Expedition Project System
- Multi-stage seasonal expedition with donation-based progression.
- Transactional item/credit donations with row locks and contribution scoring.
- Departure window with permanent rewards + temporary stacked buffs.
- Catch-up state support for missed permanent progression.
- Commands:
  - `/expedition_status`
  - `/expedition_donate_item`
  - `/expedition_donate_credits`
  - `/expedition_depart`
  - `/expedition_rewards`
  - `/expedition_catchup_status`
  - Admin: `/expedition_start`, `/expedition_end`, `/expedition_configure`

### C) Quest System (+ 3 Non-raid Activities)
- 30 quests across 5 chapters (6 each), sequential progression with milestone rewards.
- Quest requirements support counters, activity completion, rarity/foundIn collection, and multi requirements.
- Added deterministic seeded activities:
  - `/scavenge` (short cooldown, low-risk loot)
  - `/salvage` (recycle items for scraps + rare refined jackpot)
  - `/courier <stake>` (timed risk/reward credits run)
- Unified EventBus updates quests and titles from emitted gameplay events.

## Items Seeding
- Seeder uses `/mnt/data/items.json` for item metadata.
- Rarity normalization: `common/uncommon/rare/epic/legendary`, null/malformed rarity defaults to `common`.
- If file is unavailable in local/dev environment, a tiny fallback seed is used to keep the bot bootable.

## Setup

1. Copy environment template:
   ```bash
   cp .env.example .env
   ```
2. Fill in `DISCORD_TOKEN` and DB connection values (on some hosts you can use `BOT_TOKEN`/`TOKEN` instead).
3. Start services:
   ```bash
   docker compose up --build
   ```
4. Run migrations:
   ```bash
   alembic upgrade head
   ```
5. Start the bot:
   ```bash
   python -m arkpg.main
   ```


## Required Environment Variables

At startup, ARCPG requires these variables to exist in the host panel/environment (or in `.env`):

- `DISCORD_TOKEN` (or `BOT_TOKEN` / `TOKEN`)
- `DATABASE_URL` **or** all of: `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`
- `REDIS_URL`

If any are missing, startup now exits early with a clear message listing exactly which variables are missing.

## Pterodactyl / Bot-Hosting.net startup note

- This repo includes a `requirements.txt` so hosts that auto-run `pip install -r ...`
  install all runtime dependencies before launch.
- Ensure your panel startup variable points to `requirements.txt` (often named
  `REQUIREMENTS_FILE`).
- If you see `ModuleNotFoundError: No module named 'discord'`, dependency install
  was skipped; rerun install or restart after fixing the requirements file path.

## Bot-Hosting.net: "I only have a Discord token" quick fix

If startup says `Missing required environment variables: DATABASE_URL, DISCORD_TOKEN`,
your bot token alone is not enough. ARCPG needs a SQL database connection string.

1. In **Databases** in Bot-Hosting.net, click **New Database**.
2. Create either PostgreSQL or MySQL credentials (host, port, database, username, password).
3. In your server startup/environment variables set:
   - `DISCORD_TOKEN` (or `BOT_TOKEN` / `TOKEN`)
   - `DATABASE_URL`
4. Use one of these URL formats:
   - PostgreSQL (recommended):
     `postgresql+asyncpg://USER:PASSWORD@HOST:PORT/DBNAME`
   - MySQL:
     `mysql+aiomysql://USER:PASSWORD@HOST:PORT/DBNAME`
5. If your panel only shows a JDBC string (starts with `jdbc:mysql://...`), remove `jdbc:` and change the prefix to `mysql+aiomysql://`.
6. If your DB password contains special characters (for example `@`, `/`, `:`), URL-encode the password portion before putting it into `DATABASE_URL`.
7. Restart the bot.

Example conversion for a Bot-Hosting MySQL endpoint like `us.mysql.db.bot-hosting.net:3306`:

```env
DISCORD_TOKEN=your_discord_bot_token_here
DATABASE_URL=mysql+aiomysql://DB_USER:DB_PASSWORD@us.mysql.db.bot-hosting.net:3306/DB_NAME
```

`REDIS_URL` is optional in this project and defaults to `redis://localhost:6379/0`.


### Alternate DB config (avoids URL-encoding mistakes)

If your MySQL password contains special characters and `DATABASE_URL` is error-prone, you can set
individual DB vars instead. ARCPG will build a safe SQLAlchemy URL for you:

```env
DB_HOST=us.mysql.db.bot-hosting.net
DB_PORT=3306
DB_NAME=your_database
DB_USER=your_user
DB_PASSWORD=your_raw_password
```

If both `DATABASE_URL` and `DB_*` values are set, `DB_*` takes precedence.

Some host panels expose these as `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_DATABASE`,
`MYSQL_USER`, `MYSQL_PASSWORD` (or Postgres-style `PG*` / `POSTGRES_*` names).
ARCPG accepts those aliases as well.

## Notes

- Monetization remains non-pay-to-win.
- Titles in this system are gameplay-earned only.
- RNG-relevant loops store deterministic seeds for auditability.
