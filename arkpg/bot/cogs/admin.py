import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import delete, select

from arkpg.db.models import AuditLog, GameConfig, User
from arkpg.db.session import SessionLocal
from arkpg.game.service import get_or_create_user


class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def is_admin(self, interaction: discord.Interaction) -> bool:
        return interaction.user.guild_permissions.manage_guild

    @app_commands.command(description="Configure bot channels and multipliers.")
    async def config(self, interaction: discord.Interaction, announcement_channel: discord.TextChannel | None = None, log_channel: discord.TextChannel | None = None, economy_multiplier: app_commands.Range[float, 0.1, 5.0] = 1.0) -> None:
        if not self.is_admin(interaction):
            await interaction.response.send_message("Missing Manage Server permission.", ephemeral=True)
            return
        if interaction.guild is None:
            await interaction.response.send_message("Guild-only command.", ephemeral=True)
            return
        async with SessionLocal() as session:
            cfg = (await session.execute(select(GameConfig).where(GameConfig.guild_id == interaction.guild.id))).scalar_one_or_none()
            if cfg is None:
                cfg = GameConfig(guild_id=interaction.guild.id)
                session.add(cfg)
            cfg.announcement_channel_id = announcement_channel.id if announcement_channel else cfg.announcement_channel_id
            cfg.log_channel_id = log_channel.id if log_channel else cfg.log_channel_id
            cfg.economy_multiplier = economy_multiplier
            await session.commit()
        await interaction.response.send_message("Configuration updated.", ephemeral=True)

    @app_commands.command(description="Wipe a test user's game data.")
    async def wipe(self, interaction: discord.Interaction, target: discord.Member) -> None:
        if not self.is_admin(interaction):
            await interaction.response.send_message("Missing Manage Server permission.", ephemeral=True)
            return
        async with SessionLocal() as session:
            user = (await session.execute(select(User).where(User.discord_id == target.id))).scalar_one_or_none()
            if user:
                await session.delete(user)
            session.add(AuditLog(event_type="admin_wipe", payload={"admin": interaction.user.id, "target": target.id}))
            await session.commit()
        await interaction.response.send_message(f"Wiped game data for {target.mention}.", ephemeral=True)

    @app_commands.command(description="Show suspicious activity events.")
    async def anti_exploit_log(self, interaction: discord.Interaction) -> None:
        if not self.is_admin(interaction):
            await interaction.response.send_message("Missing Manage Server permission.", ephemeral=True)
            return
        async with SessionLocal() as session:
            rows = (await session.execute(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(10))).scalars().all()
        content = "\n".join(f"`{r.created_at}` {r.event_type} {r.payload}" for r in rows) or "No events."
        await interaction.response.send_message(content, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
