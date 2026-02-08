import asyncio

from arkpg.bot.client import ArkpgBot
from arkpg.core.config import get_settings
from arkpg.core.logging import configure_logging


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.bot_log_level)
    bot = ArkpgBot()
    async with bot:
        await bot.start(settings.discord_token)


if __name__ == "__main__":
    asyncio.run(main())
