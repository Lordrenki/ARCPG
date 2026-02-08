
import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from arkpg.core.config import get_settings
from arkpg.db.models import Deployment, DeploymentStatus, Inventory, Item, Squad, SquadMember, Trade, TradeStatus, User
from arkpg.db.session import SessionLocal
from arkpg.game.constants import RARITY_COLORS, ZONE_CONFIG
from arkpg.game.service import (
    atomic_trade_confirm,
    claim_idle,
    extract_deployment,
    get_or_create_user,
    normalized_profile,
    start_deployment,
    update_user_profile,
)


class GameplayCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.settings = get_settings()

    @app_commands.command(description="Claim your idle XP and credits.")
    async def claim(self, interaction: discord.Interaction) -> None:
        async with SessionLocal() as session:
            user, minutes, xp, credits = await claim_idle(session, self.settings, interaction.user.id)
        embed = discord.Embed(title="Idle claim complete", color=0x2ECC71)
        embed.add_field(name="Recovered Time", value=f"{minutes} min")
        embed.add_field(name="XP", value=f"+{xp}")
        embed.add_field(name="Credits", value=f"+{credits}")
        embed.set_footer(text=f"Level {user.level}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(description="Start a deployment.")
    @app_commands.describe(zone="Choose a deployment zone")
    async def deploy(self, interaction: discord.Interaction, zone: str) -> None:
        if zone not in ZONE_CONFIG:
            await interaction.response.send_message("Unknown zone. Choose Residential, Industrial, or ARC Site.", ephemeral=True)
            return
        async with SessionLocal() as session:
            try:
                dep = await start_deployment(session, interaction.user.id, zone)
            except ValueError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return

        embed = discord.Embed(title=f"Deployment launched: {zone}", color=0x3498DB)
        embed.description = "You descend through static and dust. Keep your sensors alive and extract in time."
        embed.add_field(name="ETA", value=f"{dep.ends_at:%Y-%m-%d %H:%M UTC}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(description="Extract from your finished deployment.")
    async def extract(self, interaction: discord.Interaction) -> None:
        async with SessionLocal() as session:
            try:
                outcome = await extract_deployment(session, interaction.user.id)
            except ValueError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return
        color = RARITY_COLORS.get(outcome["loot"][0]["rarity"], 0x95A5A6) if outcome["loot"] else 0x95A5A6
        embed = discord.Embed(title=f"Extraction: {outcome['status'].title()}", color=color)
        embed.add_field(name="Event", value=outcome["event"], inline=False)
        embed.add_field(name="XP", value=f"+{outcome['xp']}")
        embed.add_field(name="Credits", value=f"+{outcome['credits']}")
        loot_text = "\n".join(f"• {x['name']} x{x['qty']}" for x in outcome["loot"]) if outcome["loot"] else "No recovered loot"
        embed.add_field(name="Recovered", value=loot_text, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(description="View your inventory.")
    async def inventory(self, interaction: discord.Interaction) -> None:
        async with SessionLocal() as session:
            user = await get_or_create_user(session, interaction.user.id)
            rows = (await session.execute(select(Inventory, Item).join(Item, Inventory.item_id == Item.id).where(Inventory.user_id == user.id))).all()
        embed = discord.Embed(title="Field Inventory", color=0x95A5A6)
        if not rows:
            embed.description = "Your stash is empty. Deploy and extract to fill it."
        else:
            lines = []
            for inv, item in rows[:20]:
                level = f" L{inv.weapon_level}" if inv.weapon_level else ""
                dura = f" ({inv.durability}% dura)" if inv.durability is not None else ""
                lines.append(f"• {item.name}{level}{dura} x{inv.qty}")
            embed.description = "\n".join(lines)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(description="Create a squad.")
    async def squad_create(self, interaction: discord.Interaction, name: str) -> None:
        async with SessionLocal() as session:
            owner = await get_or_create_user(session, interaction.user.id)
            squad = Squad(name=name, owner_id=owner.id)
            session.add(squad)
            await session.flush()
            session.add(SquadMember(squad_id=squad.id, user_id=owner.id, role="owner"))
            await session.commit()
        await interaction.response.send_message(f"Squad **{name}** formed. Rally your team.", ephemeral=True)

    @app_commands.command(description="Join a squad by name.")
    async def squad_join(self, interaction: discord.Interaction, name: str) -> None:
        async with SessionLocal() as session:
            me = await get_or_create_user(session, interaction.user.id)
            squad = (await session.execute(select(Squad).where(Squad.name == name))).scalar_one_or_none()
            if squad is None:
                await interaction.response.send_message("Squad not found.", ephemeral=True)
                return
            session.add(SquadMember(squad_id=squad.id, user_id=me.id, role="member"))
            await session.commit()
        await interaction.response.send_message(f"Joined **{name}**.", ephemeral=True)

    @app_commands.command(description="Leave your current squad.")
    async def squad_leave(self, interaction: discord.Interaction) -> None:
        async with SessionLocal() as session:
            me = await get_or_create_user(session, interaction.user.id)
            sm = (await session.execute(select(SquadMember).where(SquadMember.user_id == me.id))).scalar_one_or_none()
            if sm is None:
                await interaction.response.send_message("You're not in a squad.", ephemeral=True)
                return
            await session.delete(sm)
            await session.commit()
        await interaction.response.send_message("You left your squad.", ephemeral=True)

    @app_commands.command(description="Challenge another player to a duel.")
    async def duel(self, interaction: discord.Interaction, opponent: discord.Member) -> None:
        if opponent.bot:
            await interaction.response.send_message("Bots cannot duel.", ephemeral=True)
            return
        async with SessionLocal() as session:
            me = await get_or_create_user(session, interaction.user.id)
            them = await get_or_create_user(session, opponent.id)
        if abs(me.level - them.level) > 8:
            await interaction.response.send_message("Level difference too large. Find a closer rival.", ephemeral=True)
            return
        my_power = me.level + me.stats.get("combat", 10) + me.stats.get("luck", 10) * 0.2
        their_power = them.level + them.stats.get("combat", 10) + them.stats.get("luck", 10) * 0.2
        winner = interaction.user.mention if my_power >= their_power else opponent.mention
        await interaction.response.send_message(f"Duel resolved. Winner: {winner}")

    @app_commands.command(description="Create a pending trade offer.")
    async def trade(self, interaction: discord.Interaction, target: discord.Member, offered_credits: int, requested_credits: int) -> None:
        async with SessionLocal() as session:
            src = await get_or_create_user(session, interaction.user.id)
            dst = await get_or_create_user(session, target.id)
            trade = Trade(from_user=src.id, to_user=dst.id, offered={"credits": offered_credits}, requested={"credits": requested_credits}, status=TradeStatus.PENDING)
            session.add(trade)
            await session.commit()
        await interaction.response.send_message(f"Trade #{trade.id} offered to {target.mention}.", ephemeral=True)

    @app_commands.command(description="Confirm a trade by ID.")
    async def trade_confirm(self, interaction: discord.Interaction, trade_id: int) -> None:
        async with SessionLocal() as session:
            trade = (await session.execute(select(Trade).where(Trade.id == trade_id))).scalar_one_or_none()
            if trade is None:
                await interaction.response.send_message("Trade not found.", ephemeral=True)
                return
            actor = await get_or_create_user(session, interaction.user.id)
            if actor.id not in (trade.from_user, trade.to_user):
                await interaction.response.send_message("You're not a participant in this trade.", ephemeral=True)
                return
            try:
                await atomic_trade_confirm(session, trade_id)
            except ValueError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return
        await interaction.response.send_message(f"Trade #{trade_id} confirmed.", ephemeral=True)



    @app_commands.command(description="View your customizable profile.")
    async def profile(self, interaction: discord.Interaction) -> None:
        async with SessionLocal() as session:
            user = await get_or_create_user(session, interaction.user.id)
            profile = normalized_profile(user)
        embed = discord.Embed(title="Operator Profile", color=0x9B59B6)
        embed.add_field(name="Callsign", value=profile["callsign"], inline=False)
        embed.add_field(name="Title", value=profile["title"], inline=False)
        embed.add_field(name="Bio", value=profile["bio"], inline=False)
        embed.set_footer(text=f"Level {user.level} • Credits {user.credits}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(description="Update your customizable profile fields.")
    @app_commands.describe(callsign="Up to 32 chars", title="Up to 60 chars", bio="Up to 220 chars")
    async def profile_set(
        self,
        interaction: discord.Interaction,
        callsign: str | None = None,
        title: str | None = None,
        bio: str | None = None,
    ) -> None:
        if callsign is None and title is None and bio is None:
            await interaction.response.send_message("Provide at least one field to update.", ephemeral=True)
            return
        async with SessionLocal() as session:
            _, profile = await update_user_profile(session, interaction.user.id, callsign=callsign, title=title, bio=bio)
        embed = discord.Embed(title="Profile Updated", color=0x2ECC71)
        embed.add_field(name="Callsign", value=profile["callsign"], inline=False)
        embed.add_field(name="Title", value=profile["title"], inline=False)
        embed.add_field(name="Bio", value=profile["bio"], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(description="Leaderboard for level, credits, clears, and legendary finds.")
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        async with SessionLocal() as session:
            top = (await session.execute(select(User).order_by(User.level.desc(), User.xp.desc()).limit(10))).scalars().all()
            legend = sorted(top, key=lambda u: int(u.stats.get("legendary_finds", 0)), reverse=True)
        embed = discord.Embed(title="ARCPG Leaderboard", color=0xF1C40F)
        embed.add_field(name="Top Operators", value="\n".join(f"{i+1}. <@{u.discord_id}> — Lv {u.level}" for i, u in enumerate(top)) or "None", inline=False)
        embed.add_field(name="Legendary Finds", value="\n".join(f"{i+1}. <@{u.discord_id}> — {u.stats.get('legendary_finds', 0)}" for i, u in enumerate(legend)) or "None", inline=False)
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GameplayCog(bot))
