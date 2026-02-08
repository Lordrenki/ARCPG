import asyncio
import sys
from pathlib import Path

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

    settings = get_settings()
    configure_logging(settings.bot_log_level)
    bot = ArkpgBot()
    async with bot:
        await bot.start(settings.discord_token)


if __name__ == "__main__":
    asyncio.run(main())
