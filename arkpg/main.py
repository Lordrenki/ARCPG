import asyncio
import sys
from pathlib import Path

from pydantic import ValidationError

# Allow running this file directly (e.g. `python arkpg/main.py`) in hosting
# environments that don't start it as a module.
if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arkpg.core.config import get_settings
from arkpg.core.logging import configure_logging


async def main() -> None:
    try:
        from arkpg.bot.client import ArkpgBot
    except ModuleNotFoundError as exc:
        if exc.name == "discord":
            raise SystemExit(
                "Missing dependency: discord.py is not installed. "
                "Install dependencies with `pip install -r requirements.txt` "
                "or configure your host REQUIREMENTS_FILE to requirements.txt."
            ) from exc
        raise

    try:
        settings = get_settings()
    except ValidationError as exc:
        missing_keys = []
        for err in exc.errors():
            if err.get("type") == "missing":
                loc = err.get("loc", ())
                if loc:
                    missing_keys.append(str(loc[-1]))

        if missing_keys:
            keys = ", ".join(sorted(set(missing_keys)))
            raise SystemExit(
                "Missing required environment variables: "
                f"{keys}. Set these in your host panel/environment (or a .env file). "
                "DISCORD_TOKEN can also be provided as BOT_TOKEN or TOKEN."
            ) from exc
        raise

    configure_logging(settings.bot_log_level)
    bot = ArkpgBot()
    async with bot:
        await bot.start(settings.discord_token)


if __name__ == "__main__":
    asyncio.run(main())
