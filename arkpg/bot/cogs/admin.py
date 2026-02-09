from sqlalchemy.ext.asyncio import AsyncSession
import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from arkpg.db.models import AuditLog, GameConfig, Item, Title, User, UserTitle
from arkpg.db.session import SessionLocal
from arkpg.game.progression import InventoryService, SeederService
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


    async def _grant_staff_title(self, session: AsyncSession, user: User) -> None:
        title_id = "arcpg_staff_team"
        title = await session.get(Title, title_id)
        if title is None:
            title = Title(
                id=title_id,
                name="ARCPG Staff Team",
                description="Exclusive title for ARCPG administration staff.",
                category="Staff",
                rarity="legendary",
                how_to_earn="Granted to ARCPG staff members.",
                is_hidden=False,
            )
            session.add(title)
            await session.flush()
        owned = (await session.execute(select(UserTitle).where(UserTitle.user_id == user.id, UserTitle.title_id == title_id))).scalar_one_or_none()
        if owned is None:
            session.add(UserTitle(user_id=user.id, title_id=title_id, source_event={"event_type": "staff_grant"}))

    @app_commands.command(description="Configure bot channels and multipliers.")
    async def config(self, interaction: discord.Interaction, announcement_channel: discord.TextChannel | None = None, log_channel: discord.TextChannel | None = None, economy_multiplier: app_commands.Range[float, 0.1, 5.0] = 1.0) -> None:
        if not self.is_admin(interaction):
            await interaction.response.send_message("This admin command is restricted.", ephemeral=True)
            return
        if interaction.guild is None:
            await interaction.response.send_message("Guild-only command.", ephemeral=True)
            return
        async with SessionLocal() as session:
            user = await get_or_create_user(session, interaction.user.id)
            await self._grant_staff_title(session, user)
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
            admin_user = await get_or_create_user(session, interaction.user.id)
            await self._grant_staff_title(session, admin_user)
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
            user = await get_or_create_user(session, interaction.user.id)
            await self._grant_staff_title(session, user)
            rows = (await session.execute(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(10))).scalars().all()
        content = "\n".join(f"`{r.created_at}` {r.event_type} {r.payload}" for r in rows) or "No events."
        await interaction.response.send_message(content, ephemeral=True)

    @app_commands.command(description="Admin: give yourself any item.")
    async def give(self, interaction: discord.Interaction, item: str, qty: app_commands.Range[int, 1, 999] = 1) -> None:
        if not self.is_admin(interaction):
            await interaction.response.send_message("This admin command is restricted.", ephemeral=True)
            return

        async with SessionLocal() as session:
            await SeederService.ensure_seed_data(session)
            user = await get_or_create_user(session, interaction.user.id)
            await self._grant_staff_title(session, user)
            item_row = None
            if item.isdigit():
                item_row = await session.get(Item, int(item))
            if item_row is None:
                item_row = (await session.execute(select(Item).where(Item.name.ilike(item)).limit(1))).scalar_one_or_none()
            if item_row is None:
                fuzzy = (await session.execute(select(Item).where(Item.name.ilike(f"%{item.strip()}%")).order_by(Item.name.asc()).limit(1))).scalar_one_or_none()
                item_row = fuzzy
            if item_row is None:
                await interaction.response.send_message("Item not found. Try part of the item name or ID.", ephemeral=True)
                return

            await InventoryService(session).add_item(user.id, item_row.id, qty)
            session.add(AuditLog(event_type="admin_give", payload={"admin": interaction.user.id, "item_id": item_row.id, "qty": qty}))
            await session.commit()

        await interaction.response.send_message(f"Granted **{item_row.name} x{qty}** to yourself.", ephemeral=True)


    @app_commands.command(description="Admin: list item categories and sample names.")
    async def items(self, interaction: discord.Interaction, category: str | None = None) -> None:
        if not self.is_admin(interaction):
            await interaction.response.send_message("This admin command is restricted.", ephemeral=True)
            return
        async with SessionLocal() as session:
            await SeederService.ensure_seed_data(session)
            user = await get_or_create_user(session, interaction.user.id)
            await self._grant_staff_title(session, user)
            rows = (await session.execute(select(Item).order_by(Item.type.asc(), Item.name.asc()))).scalars().all()
            await session.commit()

        grouped: dict[str, list[tuple[int, str]]] = {}
        for row in rows:
            key = row.type.value
            grouped.setdefault(key, []).append((row.id, row.name))

        if category:
            names = grouped.get(category.lower())
            if not names:
                await interaction.response.send_message("Unknown category. Use weapon, armor, gadget, component, blueprint, recyclable.", ephemeral=True)
                return
            preview = "\n".join(f"• `{item_id}` — {name}" for item_id, name in names[:40])
            await interaction.response.send_message(f"**{category.title()} Items ({len(names)})**\n{preview}", ephemeral=True)
            return

        lines = [f"• **{k.title()}**: {len(v)} items" for k, v in grouped.items()]
        await interaction.response.send_message("Item catalog loaded from DB:\n" + "\n".join(lines), ephemeral=True)



async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
