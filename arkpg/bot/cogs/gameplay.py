import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import and_, select

from arkpg.core.config import get_settings
from arkpg.db.models import (
    Expedition,
    ExpeditionContribution,
    ExpeditionStage,
    ExpeditionStatus,
    Inventory,
    Item,
    Quest,
    QuestStatus,
    Squad,
    SquadMember,
    Title,
    Trade,
    TradeStatus,
    User,
    UserExpeditionState,
    UserQuest,
    UserTitle,
)
from arkpg.db.session import SessionLocal
from arkpg.game.constants import RARITY_COLORS, ZONE_CONFIG
from arkpg.game.progression import ActivityService, EventBus, ExpeditionService, QuestService, SeederService, TitleService
from arkpg.game.service import atomic_trade_confirm, claim_idle, extract_deployment, get_or_create_user, normalized_profile, start_deployment, update_user_profile


class GameplayCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.settings = get_settings()

    @app_commands.command(description="Claim your idle XP and credits.")
    async def claim(self, interaction: discord.Interaction) -> None:
        async with SessionLocal() as session:
            await SeederService.ensure_seed_data(session)
            user, minutes, xp, credits = await claim_idle(session, self.settings, interaction.user.id)
        embed = discord.Embed(title="Idle claim complete", color=0x2ECC71)
        embed.add_field(name="Recovered Time", value=f"{minutes} min")
        embed.add_field(name="XP", value=f"+{xp}")
        embed.add_field(name="Credits", value=f"+{credits}")
        embed.set_footer(text=f"Level {user.level}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(description="Start a deployment.")
    async def deploy(self, interaction: discord.Interaction, zone: str) -> None:
        if zone not in ZONE_CONFIG:
            await interaction.response.send_message("Unknown zone. Choose Residential, Industrial, or ARC Site.", ephemeral=True)
            return
        async with SessionLocal() as session:
            await SeederService.ensure_seed_data(session)
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
            await SeederService.ensure_seed_data(session)
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
        embed.description = "\n".join(f"• {item.name} x{inv.qty}" for inv, item in rows[:20]) if rows else "Your stash is empty."
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(description="View your customizable profile.")
    async def profile(self, interaction: discord.Interaction) -> None:
        async with SessionLocal() as session:
            user = await get_or_create_user(session, interaction.user.id)
            profile = normalized_profile(user)
            title = (await session.get(Title, user.equipped_title_id)).name if user.equipped_title_id else "Unassigned"
        embed = discord.Embed(title="Operator Profile", color=0x9B59B6)
        embed.add_field(name="Callsign", value=profile["callsign"], inline=False)
        embed.add_field(name="Equipped Title", value=title, inline=False)
        embed.add_field(name="Tagline", value=profile["title"], inline=False)
        embed.add_field(name="Custom Tagline", value=profile["title"], inline=False)
        embed.add_field(name="Bio", value=profile["bio"], inline=False)
        embed.add_field(name="Stats", value=f"Combat {user.stats.get('combat',10)} • Tech {user.stats.get('tech',10)} • Luck {user.stats.get('luck',10)}", inline=False)
        embed.set_footer(text=f"Level {user.level} • Scraps {user.credits}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(description="Update your profile fields.")
    async def profile_set(self, interaction: discord.Interaction, callsign: str | None = None, title: str | None = None, bio: str | None = None) -> None:
        if callsign is None and title is None and bio is None:
            await interaction.response.send_message("Provide at least one field to update.", ephemeral=True)
            return
        async with SessionLocal() as session:
            _, profile = await update_user_profile(session, interaction.user.id, callsign=callsign, title=title, bio=bio)
        embed = discord.Embed(title="Profile Updated", color=0x2ECC71)
        embed.add_field(name="Callsign", value=profile["callsign"], inline=False)
        embed.add_field(name="Custom Tagline", value=profile["title"], inline=False)
        embed.add_field(name="Bio", value=profile["bio"], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(description="List titles.")
    async def titles_list(self, interaction: discord.Interaction, filter: str = "earned") -> None:
        async with SessionLocal() as session:
            user = await get_or_create_user(session, interaction.user.id)
            earned_rows = (await session.execute(select(UserTitle.title_id).where(UserTitle.user_id == user.id))).scalars().all()
            earned_ids = set(earned_rows)
            rows = (await session.execute(select(Title).order_by(Title.category.asc(), Title.name.asc()))).scalars().all()
            if filter == "earned":
                rows = [r for r in rows if r.id in earned_ids]
            elif filter not in ("all", "earned"):
                rows = [r for r in rows if r.category.lower() == filter.lower() and (not r.is_hidden or r.id in earned_ids)]
            else:
                rows = [r for r in rows if not r.is_hidden or r.id in earned_ids]
        embed = discord.Embed(title="Titles", color=0x5865F2)
        embed.description = "\n".join(f"• {t.name} ({t.category}){' ✅' if t.id in earned_ids else ''}" for t in rows[:25]) or "No titles found."
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(description="Inspect a title and progress.")
    async def titles_inspect(self, interaction: discord.Interaction, title_id: str) -> None:
        async with SessionLocal() as session:
            user = await get_or_create_user(session, interaction.user.id)
            title = await session.get(Title, title_id)
            if not title:
                await interaction.response.send_message("Unknown title id.", ephemeral=True)
                return
            earned = (await session.execute(select(UserTitle).where(and_(UserTitle.user_id == user.id, UserTitle.title_id == title_id)))).scalar_one_or_none() is not None
            progress = await TitleService(session).progress_for(user, title_id)
        if title.is_hidden and not earned:
            await interaction.response.send_message("This title is hidden. Keep exploring unusual milestones.", ephemeral=True)
            return
        embed = discord.Embed(title=title.name, description=title.description, color=0xF1C40F)
        embed.add_field(name="Category", value=title.category)
        embed.add_field(name="Rarity", value=title.rarity or "n/a")
        embed.add_field(name="How to Earn", value=title.how_to_earn, inline=False)
        embed.add_field(name="Progress", value=f"{progress:.1f}%")
        embed.add_field(name="Earned", value="Yes" if earned else "No")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(description="Equip one of your earned titles.")
    async def title_equip(self, interaction: discord.Interaction, title_id: str) -> None:
        async with SessionLocal() as session:
            user = await get_or_create_user(session, interaction.user.id)
            owned = (await session.execute(select(UserTitle).where(and_(UserTitle.user_id == user.id, UserTitle.title_id == title_id)))).scalar_one_or_none()
            if not owned:
                await interaction.response.send_message("You have not earned that title.", ephemeral=True)
                return
            user.equipped_title_id = title_id
            await session.commit()
            title = await session.get(Title, title_id)
        await interaction.response.send_message(f"Equipped title: **{title.name}**", ephemeral=True)

    @app_commands.command(description="Show current expedition status.")
    async def expedition_status(self, interaction: discord.Interaction) -> None:
        async with SessionLocal() as session:
            svc = ExpeditionService(session)
            exp = await svc.active()
            if not exp:
                await interaction.response.send_message("No active expedition cycle.", ephemeral=True)
                return
            stages = (await session.execute(select(ExpeditionStage).where(ExpeditionStage.expedition_id == exp.id).order_by(ExpeditionStage.stage_number.asc()))).scalars().all()
            user = await get_or_create_user(session, interaction.user.id)
            my = (await session.execute(select(ExpeditionContribution).where(and_(ExpeditionContribution.expedition_id == exp.id, ExpeditionContribution.user_id == user.id)))).scalar_one_or_none()
        embed = discord.Embed(title=f"Expedition Season {exp.season_number}", color=0x1ABC9C)
        embed.add_field(name="Status", value=exp.status.value)
        embed.add_field(name="Departure Window", value=f"{exp.departure_starts_at:%Y-%m-%d} → {exp.departure_ends_at:%Y-%m-%d}", inline=False)
        embed.add_field(name="Your Score", value=str(my.score if my else 0))
        embed.add_field(name="Stages", value="\n".join(f"{s.stage_number}. {s.name} {'✅' if s.is_complete else '⏳'}" for s in stages), inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(description="Donate item quantity to expedition.")
    async def expedition_donate_item(self, interaction: discord.Interaction, item_id: int, qty: int) -> None:
        async with SessionLocal() as session:
            user = await get_or_create_user(session, interaction.user.id)
            try:
                score = await ExpeditionService(session).donate_item(user, item_id, qty)
            except ValueError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return
        await interaction.response.send_message(f"Donation accepted. Expedition score +{score}.", ephemeral=True)

    @app_commands.command(description="Donate credits to expedition.")
    async def expedition_donate_credits(self, interaction: discord.Interaction, credits: int) -> None:
        async with SessionLocal() as session:
            user = await get_or_create_user(session, interaction.user.id)
            try:
                score = await ExpeditionService(session).donate_credits(user, credits)
            except ValueError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return
        await interaction.response.send_message(f"Credits donated. Expedition score +{score}.", ephemeral=True)

    @app_commands.command(description="Depart during active departure window.")
    async def expedition_depart(self, interaction: discord.Interaction) -> None:
        async with SessionLocal() as session:
            user = await get_or_create_user(session, interaction.user.id)
            try:
                rewards = await ExpeditionService(session).depart(user)
            except ValueError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return
        await interaction.response.send_message(f"Departure complete. Permanent: {rewards['permanent']} | Temporary: {rewards['temp']}", ephemeral=True)

    @app_commands.command(description="View expedition rewards and catch-up state.")
    async def expedition_rewards(self, interaction: discord.Interaction) -> None:
        async with SessionLocal() as session:
            user = await get_or_create_user(session, interaction.user.id)
            state = await session.get(UserExpeditionState, user.id)
        if not state:
            await interaction.response.send_message("No expedition rewards earned yet.", ephemeral=True)
            return
        embed = discord.Embed(title="Expedition Rewards", color=0x16A085)
        embed.add_field(name="Permanent", value=str(state.permanent_rewards or {}), inline=False)
        embed.add_field(name="Temporary", value=str(state.temp_buffs or {}), inline=False)
        embed.add_field(name="Catch-up", value=str(state.catchup_state or {}), inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(description="Catch-up status for missed expedition permanent perks.")
    async def expedition_catchup_status(self, interaction: discord.Interaction) -> None:
        async with SessionLocal() as session:
            user = await get_or_create_user(session, interaction.user.id)
            state = await session.get(UserExpeditionState, user.id)
        catchup = (state.catchup_state if state else {}) or {}
        await interaction.response.send_message(f"Catch-up status: {catchup}", ephemeral=True)

    @app_commands.command(description="Admin: start expedition season.")
    async def expedition_start(self, interaction: discord.Interaction, season_number: int) -> None:
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("Manage Server required.", ephemeral=True)
            return
        async with SessionLocal() as session:
            exp = await ExpeditionService(session).create_default(season_number)
        await interaction.response.send_message(f"Expedition season {exp.season_number} started.", ephemeral=True)

    @app_commands.command(description="Admin: end expedition and open departure window.")
    async def expedition_end(self, interaction: discord.Interaction) -> None:
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("Manage Server required.", ephemeral=True)
            return
        async with SessionLocal() as session:
            exp = await ExpeditionService(session).active()
            if not exp:
                await interaction.response.send_message("No active expedition.", ephemeral=True)
                return
            exp.status = ExpeditionStatus.DEPARTURE
            await session.commit()
        await interaction.response.send_message("Departure window is now open.", ephemeral=True)

    @app_commands.command(description="Admin: configure expedition JSON keys.")
    async def expedition_configure(self, interaction: discord.Interaction, min_depart_score: int, catchup_discount: float) -> None:
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("Manage Server required.", ephemeral=True)
            return
        async with SessionLocal() as session:
            exp = await ExpeditionService(session).active()
            if not exp:
                await interaction.response.send_message("No active expedition.", ephemeral=True)
                return
            cfg = dict(exp.config or {})
            cfg["min_depart_score"] = min_depart_score
            cfg["catchup_discount"] = catchup_discount
            exp.config = cfg
            await session.commit()
        await interaction.response.send_message("Expedition configuration updated.", ephemeral=True)

    @app_commands.command(description="Check active quest progress.")
    async def quest_status(self, interaction: discord.Interaction) -> None:
        async with SessionLocal() as session:
            user = await get_or_create_user(session, interaction.user.id)
            await QuestService(session).ensure_track(user)
            rows = (await session.execute(select(UserQuest, Quest).join(Quest, UserQuest.quest_id == Quest.id).where(and_(UserQuest.user_id == user.id, UserQuest.status == QuestStatus.ACTIVE)).order_by(Quest.chapter.asc(), Quest.order_index.asc()))).all()
        embed = discord.Embed(title="Active Quests", color=0x7289DA)
        embed.description = "\n".join(f"• Ch{q.chapter}.{q.order_index} {q.name} — {uq.progress or {'current': 0, 'target': '?'}}" for uq, q in rows) or "No active quests."
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(description="Run a short scavenge for small loot.")
    async def scavenge(self, interaction: discord.Interaction) -> None:
        async with SessionLocal() as session:
            user = await get_or_create_user(session, interaction.user.id)
            try:
                result = await ActivityService(session).scavenge(user)
                await EventBus.emit(session, user, "SCAVENGE_COMPLETED", {"counter_updates": {"scavenge_runs": 1, "activity_credits_earned": result.credits}})
                await session.commit()
            except ValueError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return
        await interaction.response.send_message(f"{result.message} Seed `{result.seed}`", ephemeral=True)

    @app_commands.command(description="Convert recyclables into scraps/materials.")
    async def salvage(self, interaction: discord.Interaction) -> None:
        async with SessionLocal() as session:
            user = await get_or_create_user(session, interaction.user.id)
            try:
                result = await ActivityService(session).salvage(user)
                update = {"salvage_runs": 1, "scrapped": 1, "activity_credits_earned": result.credits}
                if result.items:
                    update["salvage_refined_hits"] = 1
                    update["hidden_salvage_jackpot"] = 1
                await EventBus.emit(session, user, "SALVAGE_COMPLETED", {"counter_updates": update})
                await session.commit()
            except ValueError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return
        await interaction.response.send_message(f"{result.message} Seed `{result.seed}`", ephemeral=True)

    @app_commands.command(description="Take a timed courier job with risk/reward.")
    async def courier(self, interaction: discord.Interaction, stake: int) -> None:
        async with SessionLocal() as session:
            user = await get_or_create_user(session, interaction.user.id)
            try:
                result = await ActivityService(session).courier(user, stake)
                update = {"courier_runs": 1}
                if result.success:
                    update["activity_credits_earned"] = max(result.credits, 0)
                await EventBus.emit(session, user, "COURIER_COMPLETED", {"counter_updates": update})
                await session.commit()
            except ValueError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return
        await interaction.response.send_message(f"{result.message} Net `{result.credits}` Seed `{result.seed}`", ephemeral=True)

    @app_commands.command(description="Create a squad.")
    async def squad_create(self, interaction: discord.Interaction, name: str) -> None:
        async with SessionLocal() as session:
            owner = await get_or_create_user(session, interaction.user.id)
            squad = Squad(name=name, owner_id=owner.id)
            session.add(squad)
            await session.flush()
            session.add(SquadMember(squad_id=squad.id, user_id=owner.id, role="owner"))
            await EventBus.emit(session, owner, "SQUAD_JOINED", {"counter_updates": {"squad_joins": 1}})
            await session.commit()
        await interaction.response.send_message(f"Squad **{name}** formed.", ephemeral=True)

    @app_commands.command(description="Join a squad by name.")
    async def squad_join(self, interaction: discord.Interaction, name: str) -> None:
        async with SessionLocal() as session:
            me = await get_or_create_user(session, interaction.user.id)
            squad = (await session.execute(select(Squad).where(Squad.name == name))).scalar_one_or_none()
            if squad is None:
                await interaction.response.send_message("Squad not found.", ephemeral=True)
                return
            session.add(SquadMember(squad_id=squad.id, user_id=me.id, role="member"))
            await EventBus.emit(session, me, "SQUAD_JOINED", {"counter_updates": {"squad_joins": 1}})
            await session.commit()
        await interaction.response.send_message(f"Joined **{name}**.", ephemeral=True)

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
            i_win = my_power >= their_power
            if i_win:
                await EventBus.emit(session, me, "PVP_WIN", {"counter_updates": {"pvp_wins": 1, "pvp_fair_wins": 1}})
            await session.commit()
        winner = interaction.user.mention if i_win else opponent.mention
        await interaction.response.send_message(f"Duel resolved. Winner: {winner}")

    @app_commands.command(description="Create a pending trade offer.")
    async def trade(self, interaction: discord.Interaction, target: discord.Member, offered_credits: int, requested_credits: int) -> None:
        async with SessionLocal() as session:
            src = await get_or_create_user(session, interaction.user.id)
            dst = await get_or_create_user(session, target.id)
            trade_row = Trade(from_user=src.id, to_user=dst.id, offered={"credits": offered_credits}, requested={"credits": requested_credits}, status=TradeStatus.PENDING)
            session.add(trade_row)
            await session.commit()
        await interaction.response.send_message(f"Trade #{trade_row.id} offered to {target.mention}.", ephemeral=True)

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
                await EventBus.emit(session, actor, "TRADE_COMPLETED", {"counter_updates": {"trade_completed": 1}})
            except ValueError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return
        await interaction.response.send_message(f"Trade #{trade_id} confirmed.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GameplayCog(bot))
