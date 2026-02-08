# ARKPG

ARKPG is a production-ready Discord idle RPG bot with extraction-run gameplay loops inspired by high-stakes scavenging fiction.

## Folder Structure

```text
arkpg/
  bot/
    cogs/
      admin.py
      gameplay.py
    client.py
    views.py
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
    service.py
  scripts/
    simulate_deployments.py
alembic/
  versions/
    0001_init.py
  env.py
  script.py.mako
tests/
  test_deployments.py
  test_economy.py
  test_loot.py
  test_trade.py
Dockerfile
docker-compose.yml
.env.example
pyproject.toml
```

## Core Features

- Slash-command only Discord UX.
- Ephemeral responses for sensitive data (`/claim`, `/inventory`, `/trade`).
- Idle progression with anti-abuse caps and diminishing returns.
- Deployment/extraction loop with deterministic RNG seeds for auditability.
- Rarity tiers and color mapping:
  - Common (Grey)
  - Uncommon (Green)
  - Rare (Blue)
  - Epic (Purple/Pink)
  - Legendary (Orange)
- Gear durability hooks and repair-ready schema fields.
- Squads, duels, secure trade confirmation flow, leaderboard, and admin moderation tools.
- PostgreSQL schema + Alembic migrations.
- Audit log stream for suspicious behavior.

## Commands (slash)

### Player
- `/claim`
- `/deploy <zone>`
- `/extract`
- `/inventory`
- `/squad_create <name>`
- `/squad_join <name>`
- `/squad_leave`
- `/duel <@user>`
- `/trade <@user> <offered_credits> <requested_credits>`
- `/trade_confirm <trade_id>`
- `/leaderboard`

### Admin (Manage Server required)
- `/config`
- `/wipe <@user>`
- `/anti_exploit_log`

## Setup

1. Copy environment template:
   ```bash
   cp .env.example .env
   ```
2. Fill in `DISCORD_TOKEN` in `.env`.
3. Start services:
   ```bash
   docker compose up --build
   ```
4. Run migrations (inside bot container shell):
   ```bash
   alembic upgrade head
   ```

## Local Dev

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
pytest
python -m arkpg.scripts.simulate_deployments
```

## Balancing Knobs

- `IDLE_CLAIM_CAP_HOURS`: Maximum idle accumulation window.
- `IDLE_XP_PER_MINUTE`, `IDLE_CREDITS_PER_MINUTE`: Passive baseline.
- Zone risk/reward in `arkpg/game/constants.py`.
- Rarity weights in `arkpg/game/constants.py`.
- Deployment duration per zone in `arkpg/game/constants.py`.
- Repair pressure can be tuned by `durability_loss` in deployment resolver.
- Economy-wide scalar via `ECONOMY_MULTIPLIER` and guild config override.

## Supporter Perks (non-pay-to-win)

Config supports optional monetization toggles (`SUPPORTER_FEATURES_ENABLED`, `monetization_enabled`) for:
- cosmetic badges/titles,
- QoL stash size/loadout slots,
- supporter-only cosmetic missions.

Combat power is intentionally unaffected.
