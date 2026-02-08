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
- Profile now shows equipped title + editable tagline.

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
- `DATABASE_URL`
- `REDIS_URL`

If any are missing, startup now exits early with a clear message listing exactly which variables are missing.

## Pterodactyl / Bot-Hosting.net startup note

- This repo includes a `requirements.txt` so hosts that auto-run `pip install -r ...`
  install all runtime dependencies before launch.
- Ensure your panel startup variable points to `requirements.txt` (often named
  `REQUIREMENTS_FILE`).
- If you see `ModuleNotFoundError: No module named 'discord'`, dependency install
  was skipped; rerun install or restart after fixing the requirements file path.

## Notes

- Monetization remains non-pay-to-win.
- Titles in this system are gameplay-earned only.
- RNG-relevant loops store deterministic seeds for auditability.
