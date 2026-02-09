import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from arkpg.db.models import AuditLog, GameConfig, Item, User
from arkpg.db.session import SessionLocal
from arkpg.game.progression import InventoryService
from arkpg.game.service import get_or_create_user


ADMIN_ROLE_ID = 927355923364720651
ADMIN_GUILD_ID = 927355923314380901


class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def is_admin(self, interaction: discord.Interaction) -> bool:
        if interaction.guild is None or interaction.guild.id != ADMIN_GUILD_ID:
            return False
        member = interaction.user if isinstance(interaction.user, discord.Member) else interaction.guild.get_member(interaction.user.id)
        if member is None:
            return False
        return any(role.id == ADMIN_ROLE_ID for role in member.roles)

    @app_commands.command(description="Configure bot channels and multipliers.")
    async def config(self, interaction: discord.Interaction, announcement_channel: discord.TextChannel | None = None, log_channel: discord.TextChannel | None = None, economy_multiplier: app_commands.Range[float, 0.1, 5.0] = 1.0) -> None:
        if not self.is_admin(interaction):
            await interaction.response.send_message("This admin command is restricted.", ephemeral=True)
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
            await interaction.response.send_message("This admin command is restricted.", ephemeral=True)
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
            await interaction.response.send_message("This admin command is restricted.", ephemeral=True)
            return
        async with SessionLocal() as session:
            rows = (await session.execute(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(10))).scalars().all()
        content = "\n".join(f"`{r.created_at}` {r.event_type} {r.payload}" for r in rows) or "No events."
        await interaction.response.send_message(content, ephemeral=True)

    @app_commands.command(description="Admin: give yourself any item.")
    async def give(self, interaction: discord.Interaction, item: str, qty: app_commands.Range[int, 1, 999] = 1) -> None:
        if not self.is_admin(interaction):
            await interaction.response.send_message("This admin command is restricted.", ephemeral=True)
            return

        async with SessionLocal() as session:
            user = await get_or_create_user(session, interaction.user.id)
            item_row = None
            if item.isdigit():
                item_row = await session.get(Item, int(item))
            if item_row is None:
                item_row = (await session.execute(select(Item).where(Item.name.ilike(item)).limit(1))).scalar_one_or_none()
            if item_row is None:
                await interaction.response.send_message("Item not found. Use exact name or ID.", ephemeral=True)
                return

            await InventoryService(session).add_item(user.id, item_row.id, qty)
            session.add(AuditLog(event_type="admin_give", payload={"admin": interaction.user.id, "item_id": item_row.id, "qty": qty}))
            await session.commit()

        await interaction.response.send_message(f"Granted **{item_row.name} x{qty}** to yourself.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
