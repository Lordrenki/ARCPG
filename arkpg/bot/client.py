import discord
from discord.ext import commands

from arkpg.core.config import get_settings


class ArkpgBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.members = True
        super().__init__(command_prefix="/", intents=intents)
        self.settings = get_settings()

    async def setup_hook(self) -> None:
        await self.load_extension("arkpg.bot.cogs.gameplay")
        await self.load_extension("arkpg.bot.cogs.admin")
        if self.settings.sync_commands_guild_id:
            guild = discord.Object(id=self.settings.sync_commands_guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()
