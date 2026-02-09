from datetime import datetime, timezone
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import and_, select

from arkpg.bot.profile_card import render_profile_card
from arkpg.bot.views import PaginatedEmbedView
from arkpg.core.config import get_settings
from arkpg.db.models import (
    Deployment,
    DeploymentStatus,
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
from arkpg.game.profile_backgrounds import PROFILE_BACKGROUNDS, get_background
from arkpg.game.progression import ActivityService, EventBus, ExpeditionService, QuestService, SeederService, TitleService
from arkpg.game.crafting import crafting_recipe_for_item, is_craftable_item
from arkpg.game.economy import level_from_xp
from arkpg.game.service import (
    atomic_trade_confirm,
    claim_idle,
    craft_item,
    equip_loadout_item,
    extract_deployment,
    get_equipped_loadout,
    collect_profile_background,
    get_or_create_user,
    normalized_profile,
    start_deployment,
    update_user_profile,
)


ADMIN_ROLE_ID = 927355923364720651
ADMIN_GUILD_ID = 927355923314380901
ADMIN_PROFILE_BACKGROUND_PATH = Path(__file__).resolve().parents[2] / "assets" / "admin_staff_team.png"


class GameplayCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.settings = get_settings()




    def _is_super_admin(self, interaction: discord.Interaction) -> bool:
        if interaction.guild is None or interaction.guild.id != ADMIN_GUILD_ID:
            return False
        member = interaction.user if isinstance(interaction.user, discord.Member) else interaction.guild.get_member(interaction.user.id)
        if member is None:
            return False
        return any(role.id == ADMIN_ROLE_ID for role in member.roles)

    def _relative_time(self, dt: datetime) -> str:
        target = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        seconds = int((target - datetime.now(timezone.utc)).total_seconds())
        if seconds <= 0:
            return "ready now"
        hours, rem = divmod(seconds, 3600)
        minutes, _ = divmod(rem, 60)
        if hours:
            return f"in {hours} hour" + ("s" if hours != 1 else "") + (f" {minutes} minute" + ("s" if minutes != 1 else "") if minutes else "")
        return f"in {max(1, minutes)} minute" + ("s" if minutes != 1 else "")

    def _styled_embed(self, title: str, description: str | None = None, color: int = 0x7A1F2B) -> discord.Embed:
        embed = discord.Embed(title=title, description=description, color=color)
        embed.set_footer(text="ARCPG Alpha V.0.5")
        return embed

    def _format_requirement(self, req: dict, progress: dict | None = None) -> str:
        progress = progress or {}
        current = progress.get("current", 0)
        target = progress.get("target", req.get("count", "?"))
        req_type = req.get("type")
        if req_type == "activity_count":
            return f"{req.get('activity', 'activity').title()} runs: {current}/{target}"
        if req_type == "counter":
            label = str(req.get("key", "counter")).replace("_", " ").title()
            return f"{label}: {current}/{target}"
        if req_type == "collect_rarity":
            return f"Collect {req.get('rarity', 'item').title()} items: {current}/{target}"
        if req_type == "collect_found_in":
            return f"Collect {req.get('found_in', 'zone').title()} finds: {current}/{target}"
        if req_type == "multi":
            return " + ".join(self._format_requirement(sub, {}) for sub in req.get("all", []))
        return f"Progress: {current}/{target}"

    @staticmethod
    def _flatten_commands(cmds: list[app_commands.Command | app_commands.Group]) -> list[app_commands.Command]:
        flat: list[app_commands.Command] = []
        for cmd in cmds:
            if isinstance(cmd, app_commands.Group):
                flat.extend(GameplayCog._flatten_commands(cmd.commands))
            else:
                flat.append(cmd)
        return flat

    @app_commands.command(description="Browse all player commands.")
    async def help(self, interaction: discord.Interaction) -> None:
        tree_commands = interaction.client.tree.get_commands()
        commands_list = [
            cmd
            for cmd in self._flatten_commands(tree_commands)
            if not cmd.name.startswith("admin")
        ]
        entries = sorted(
            [(f"/{cmd.qualified_name}", cmd.description or "No description available.") for cmd in commands_list],
            key=lambda x: x[0],
        )

        per_page = 10
        pages: list[discord.Embed] = []
        for idx in range(0, len(entries), per_page):
            chunk = entries[idx : idx + per_page]
            embed = self._styled_embed(title="ARCPG Command Guide")
            embed.description = "\n".join(f"`{name}` — {description}" for name, description in chunk)
            embed.set_footer(text=f"ARCPG Alpha V.0.5 • Page {idx // per_page + 1}/{max(1, (len(entries) + per_page - 1) // per_page)}")
            pages.append(embed)

        if not pages:
            pages.append(self._styled_embed(title="ARCPG Command Guide", description="No commands available."))

        view = PaginatedEmbedView(owner_id=interaction.user.id, pages=pages)
        await interaction.response.send_message(embed=view.current_embed(), view=view)

    @app_commands.command(description="Initialize your raider profile and open the quick-start guide.")
    async def start(self, interaction: discord.Interaction) -> None:
        async with SessionLocal() as session:
            existing = (await session.execute(select(User).where(User.discord_id == interaction.user.id))).scalar_one_or_none()
            user = await get_or_create_user(session, interaction.user.id)
            await SeederService.ensure_seed_data(session)
            await session.commit()

        profile = normalized_profile(user)
        pages: list[discord.Embed] = []

        page1 = self._styled_embed(title="Welcome to ARCPG", color=0x7A1F2B)
        page1.description = "Your raider record is now initialized."
        page1.add_field(name="Status", value="Existing raider detected." if existing else "New raider created.", inline=False)
        page1.add_field(name="Callsign", value=profile["callsign"], inline=False)
        page1.add_field(name="Next", value="Use the **Next** button for a quick tour.", inline=False)
        page1.set_footer(text="ARCPG Alpha V.0.5 • Page 1/3")
        pages.append(page1)

        page2 = self._styled_embed(title="Core Loop", color=0x7A1F2B)
        page2.description = "Run missions, recover loot, and improve your build over time."
        page2.add_field(name="1) /deploy", value="Start a run in Residential, Industrial, or ARC Site.", inline=False)
        page2.add_field(name="2) /extract", value="Collect loot and rewards after the timer finishes.", inline=False)
        page2.add_field(name="3) /claim", value="Collect idle XP and credits between active runs.", inline=False)
        page2.set_footer(text="ARCPG Alpha V.0.5 • Page 2/3")
        pages.append(page2)

        page3 = self._styled_embed(title="Profile & Social", color=0x7A1F2B)
        page3.description = "Customize identity and progress with other players."
        page3.add_field(name="Profile", value="Use **/profile** and **/profile_set** to edit callsign and bio.", inline=False)
        page3.add_field(name="Progression", value="Use **/titles_list**, **/titles_inspect**, and **/title_equip**.", inline=False)
        page3.add_field(name="Multiplayer", value="Try **/squad_create**, **/squad_join**, and **/trade**.", inline=False)
        page3.set_footer(text="ARCPG Alpha V.0.5 • Page 3/3")
        pages.append(page3)

        view = PaginatedEmbedView(owner_id=interaction.user.id, pages=pages)
        await interaction.response.send_message(embed=view.current_embed(), view=view, ephemeral=True)

    @app_commands.command(description="Claim your idle XP and credits.")
    async def claim(self, interaction: discord.Interaction) -> None:
        async with SessionLocal() as session:
            await SeederService.ensure_seed_data(session)
            user, minutes, xp, credits = await claim_idle(session, self.settings, interaction.user.id)
        embed = self._styled_embed(title="Idle claim complete")
        embed.add_field(name="Recovered Time", value=f"{minutes} min")
        embed.add_field(name="XP", value=f"+{xp}")
        embed.add_field(name="Credits", value=f"+{credits}")
        embed.set_footer(text=f"ARCPG Alpha V.0.5 • Level {user.level}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(description="Start a deployment.")
    @app_commands.choices(zone=[app_commands.Choice(name=zone, value=zone) for zone in ZONE_CONFIG.keys()])
    async def deploy(self, interaction: discord.Interaction, zone: str) -> None:
        if zone not in ZONE_CONFIG:
            await interaction.response.send_message("Unknown zone. Choose Residential, Industrial, or ARC Site.", ephemeral=True)
            return
        async with SessionLocal() as session:
            await SeederService.ensure_seed_data(session)
            try:
                dep = await start_deployment(session, interaction.user.id, zone)
            except ValueError as exc:
                if "active deployment" in str(exc).lower():
                    user = await get_or_create_user(session, interaction.user.id)
                    active_dep = (await session.execute(select(Deployment).where(and_(Deployment.user_id == user.id, Deployment.status.in_([DeploymentStatus.ACTIVE, DeploymentStatus.READY_TO_EXTRACT]))).order_by(Deployment.started_at.desc()))).scalar_one_or_none()
                    if active_dep:
                        await interaction.response.send_message(f"You already have an active deployment. Extraction available {self._relative_time(active_dep.ends_at)}.", ephemeral=True)
                        return
                await interaction.response.send_message(str(exc), ephemeral=True)
                return

        embed = self._styled_embed(title=f"Deployment launched: {zone}")
        embed.description = "You descend through static and dust. Keep your sensors alive and extract in time."
        embed.add_field(name="ETA", value=self._relative_time(dep.ends_at))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(description="Extract from your finished deployment.")
    async def extract(self, interaction: discord.Interaction) -> None:
        async with SessionLocal() as session:
            await SeederService.ensure_seed_data(session)
            try:
                outcome = await extract_deployment(session, interaction.user.id)
            except ValueError as exc:
                if "still running" in str(exc).lower():
                    user = await get_or_create_user(session, interaction.user.id)
                    active_dep = (await session.execute(select(Deployment).where(and_(Deployment.user_id == user.id, Deployment.status.in_([DeploymentStatus.ACTIVE, DeploymentStatus.READY_TO_EXTRACT]))).order_by(Deployment.started_at.desc()))).scalar_one_or_none()
                    if active_dep:
                        await interaction.response.send_message(f"Deployment is still running. You can extract {self._relative_time(active_dep.ends_at)}.")
                        return
                await interaction.response.send_message(str(exc))
                return
        color = RARITY_COLORS.get(outcome["loot"][0]["rarity"], 0x95A5A6) if outcome["loot"] else 0x95A5A6
        embed = self._styled_embed(title=f"Extraction: {outcome['status'].title()}", color=color)
        embed.add_field(name="Event", value=outcome["event"], inline=False)
        embed.add_field(name="XP", value=f"+{outcome['xp']}")
        embed.add_field(name="Credits", value=f"+{outcome['credits']}")
        loot_text = "\n".join(f"• {x['name']} x{x['qty']}" for x in outcome["loot"]) if outcome["loot"] else "No recovered loot"
        embed.add_field(name="Recovered", value=loot_text, inline=False)
        survivability = outcome.get("survivability") or {}
        if survivability:
            embed.add_field(name="Damage", value=f"Taken {survivability.get('effective_damage', 0)} • HP {survivability.get('health_after', '?')}" + (" • Auto-heal used" if survivability.get("healing_used") else ""), inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(description="View your inventory.")
    async def inventory(self, interaction: discord.Interaction) -> None:
        async with SessionLocal() as session:
            user = await get_or_create_user(session, interaction.user.id)
            rows = (await session.execute(select(Inventory, Item).join(Item, Inventory.item_id == Item.id).where(Inventory.user_id == user.id))).all()
        embed = self._styled_embed(title="Field Inventory")
        embed.description = "\n".join(f"• {item.name} x{inv.qty}" for inv, item in rows[:20]) if rows else "Your stash is empty."
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(description="View your equipped combat loadout.")
    async def loadout(self, interaction: discord.Interaction) -> None:
        async with SessionLocal() as session:
            _user, loadout = await get_equipped_loadout(session, interaction.user.id)

        weapons = [w for w in (loadout.get("weapons") or []) if w]
        gadget = loadout.get("gadget")
        healing = loadout.get("healing")
        shield = loadout.get("shield")

        embed = self._styled_embed(title="Combat Loadout")
        embed.add_field(name="Weapons", value="\n".join(f"• {w['name']}" for w in weapons) or "None equipped", inline=False)
        embed.add_field(name="Gadget / Throwable", value=(gadget or {}).get("name", "None equipped"), inline=True)
        embed.add_field(name="Healing", value=(healing or {}).get("name", "None equipped"), inline=True)
        embed.add_field(name="Shield", value=(shield or {}).get("name", "None equipped"), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(description="Equip an item from inventory to a loadout slot.")
    async def equip(self, interaction: discord.Interaction, item_id: int, slot: str, weapon_slot: int | None = None) -> None:
        normalized_slot = slot.strip().lower()
        if normalized_slot not in {"weapon", "gadget", "healing", "shield"}:
            await interaction.response.send_message("Slot must be weapon, gadget, healing, or shield.", ephemeral=True)
            return

        async with SessionLocal() as session:
            try:
                _user, loadout = await equip_loadout_item(session, interaction.user.id, item_id=item_id, slot=normalized_slot, weapon_index=weapon_slot)
            except ValueError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return

        weapons = [w for w in (loadout.get("weapons") or []) if w]
        embed = self._styled_embed(title="Loadout Updated")
        embed.add_field(name="Weapons", value="\n".join(f"• {w['name']}" for w in weapons) or "None equipped", inline=False)
        embed.add_field(name="Gadget", value=(loadout.get("gadget") or {}).get("name", "None"), inline=True)
        embed.add_field(name="Healing", value=(loadout.get("healing") or {}).get("name", "None"), inline=True)
        embed.add_field(name="Shield", value=(loadout.get("shield") or {}).get("name", "None"), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(description="View your customizable profile card.")
    async def profile(self, interaction: discord.Interaction) -> None:
        async with SessionLocal() as session:
            user = await get_or_create_user(session, interaction.user.id)
            expected_level = level_from_xp(user.xp)
            if user.level != expected_level:
                user.level = expected_level
                await session.commit()
            profile = normalized_profile(user)
            title = (await session.get(Title, user.equipped_title_id)).name if user.equipped_title_id else "Unassigned"
            _user, loadout = await get_equipped_loadout(session, interaction.user.id)

        combat = user.stats.get("combat", 10)
        tech = user.stats.get("tech", 10)
        luck = user.stats.get("luck", 10)
        weapons = [w.get("name", "Unknown") for w in (loadout.get("weapons") or []) if w]
        gadget = (loadout.get("gadget") or {}).get("name", "None")
        healing = (loadout.get("healing") or {}).get("name", "None")
        background = get_background(str(profile["background_id"]))
        is_admin = self._is_super_admin(interaction)
        card = await render_profile_card(
            interaction_user=interaction.user,
            callsign=str(profile["callsign"]),
            title_name=title,
            bio=str(profile["bio"]),
            level=user.level,
            xp=user.xp,
            credits=user.credits,
            combat=combat,
            tech=tech,
            luck=luck,
            equipped_weapons=weapons,
            equipped_gadget=str(gadget),
            equipped_healing=str(healing),
            equipped_shield=str((loadout.get("shield") or {}).get("name", "None")),
            background=background,
            admin_background_path=str(ADMIN_PROFILE_BACKGROUND_PATH) if is_admin else None,
        )
        file = discord.File(card, filename="profile-card.png")
        await interaction.response.send_message(file=file)

    @app_commands.command(description="Update your profile fields.")
    async def profile_set(self, interaction: discord.Interaction, callsign: str | None = None, bio: str | None = None) -> None:
        if callsign is None and bio is None:
            await interaction.response.send_message("Provide at least one field to update.", ephemeral=True)
            return
        async with SessionLocal() as session:
            _, profile = await update_user_profile(session, interaction.user.id, callsign=callsign, bio=bio)
        embed = self._styled_embed(title="Raider Profile Updated")
        embed.add_field(name="Callsign", value=profile["callsign"], inline=False)
        embed.add_field(name="Bio", value=profile["bio"], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(description="List profile backgrounds you've collected.")
    async def backgrounds_list(self, interaction: discord.Interaction) -> None:
        async with SessionLocal() as session:
            user = await get_or_create_user(session, interaction.user.id)
            profile = normalized_profile(user)

        collected = set(profile["collected_background_ids"] if isinstance(profile.get("collected_background_ids"), list) else [])
        active_id = str(profile["background_id"])
        rows = []
        for bg_id, bg in PROFILE_BACKGROUNDS.items():
            if bg_id not in collected:
                continue
            marker = " ✅ Equipped" if bg_id == active_id else ""
            rows.append(f"• `{bg.id}` — {bg.name}{marker}")

        embed = self._styled_embed(title="Collected Backgrounds")
        embed.description = "\n".join(rows) if rows else "No backgrounds collected yet."
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(description="Equip a collected profile background.")
    async def background_equip(self, interaction: discord.Interaction, background_id: str) -> None:
        background_id = background_id.strip().lower()
        if background_id not in PROFILE_BACKGROUNDS:
            await interaction.response.send_message("Unknown background id.", ephemeral=True)
            return
        async with SessionLocal() as session:
            try:
                _, profile = await update_user_profile(session, interaction.user.id, background_id=background_id)
            except ValueError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return

        embed = self._styled_embed(title="Background Equipped")
        embed.add_field(name="Background", value=PROFILE_BACKGROUNDS[background_id].name, inline=False)
        embed.add_field(name="ID", value=str(profile["background_id"]), inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(description="Admin: grant a profile background to a user.")
    async def background_grant(self, interaction: discord.Interaction, member: discord.Member, background_id: str) -> None:
        if not self._is_super_admin(interaction):
            await interaction.response.send_message("This admin command is restricted.", ephemeral=True)
            return

        background_id = background_id.strip().lower()
        if background_id not in PROFILE_BACKGROUNDS:
            await interaction.response.send_message("Unknown background id.", ephemeral=True)
            return

        async with SessionLocal() as session:
            _, profile = await collect_profile_background(session, member.id, background_id)

        embed = self._styled_embed(title="Background Granted")
        embed.add_field(name="User", value=member.mention, inline=False)
        embed.add_field(name="Background", value=PROFILE_BACKGROUNDS[background_id].name, inline=False)
        embed.add_field(name="Total Collected", value=str(len(profile["collected_background_ids"])), inline=False)
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
        embed = self._styled_embed(title="Titles")
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
        embed = self._styled_embed(title=title.name, description=title.description)
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
        embed = self._styled_embed(title=f"Expedition Season {exp.season_number}")
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
        embed = self._styled_embed(title="Expedition Rewards")
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
        if not self._is_super_admin(interaction):
            await interaction.response.send_message("This admin command is restricted.", ephemeral=True)
            return
        async with SessionLocal() as session:
            exp = await ExpeditionService(session).create_default(season_number)
        await interaction.response.send_message(f"Expedition season {exp.season_number} started.", ephemeral=True)

    @app_commands.command(description="Admin: end expedition and open departure window.")
    async def expedition_end(self, interaction: discord.Interaction) -> None:
        if not self._is_super_admin(interaction):
            await interaction.response.send_message("This admin command is restricted.", ephemeral=True)
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
        if not self._is_super_admin(interaction):
            await interaction.response.send_message("This admin command is restricted.", ephemeral=True)
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
        embed = self._styled_embed(title="Active Quests")
        if not rows:
            embed.description = "No active quests."
        else:
            lines: list[str] = []
            for uq, q in rows:
                lines.append(f"• **Ch{q.chapter}.{q.order_index} {q.name}**")
                lines.append(f"  Description: {q.description}")
                lines.append(f"  Requirements: {self._format_requirement(q.requirements or {}, uq.progress or {})}")
            embed.description = "\n".join(lines)
        await interaction.response.send_message(embed=embed, ephemeral=True)


    @app_commands.command(description="Show action cooldowns.")
    async def cooldowns(self, interaction: discord.Interaction) -> None:
        async with SessionLocal() as session:
            user = await get_or_create_user(session, interaction.user.id)
            activity = ActivityService(session)
            status = await activity.cooldown_status(user.id)
            active_dep = (await session.execute(select(Deployment).where(and_(Deployment.user_id == user.id, Deployment.status.in_([DeploymentStatus.ACTIVE, DeploymentStatus.READY_TO_EXTRACT]))))).scalar_one_or_none()

        embed = self._styled_embed(title="Action Cooldowns")
        embed.add_field(name="Scavenge", value=status.get("scavenge", "Ready now"), inline=True)
        embed.add_field(name="Salvage", value=status.get("salvage", "Ready now"), inline=True)
        embed.add_field(name="Courier", value=status.get("courier", "Ready now"), inline=True)
        embed.add_field(name="Work", value=status.get("work", "Ready now"), inline=True)
        if active_dep:
            embed.add_field(name="Deployment", value=self._relative_time(active_dep.ends_at), inline=False)
        else:
            embed.add_field(name="Deployment", value="Ready now", inline=False)
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
                await interaction.response.send_message(str(exc))
                return
        await interaction.response.send_message(result.message)

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
                await interaction.response.send_message(str(exc))
                return
        await interaction.response.send_message(result.message)

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
                await interaction.response.send_message(str(exc))
                return
        await interaction.response.send_message(f"{result.message} Net `{result.credits}`")

    @app_commands.command(description="Work a random side job for credits.")
    async def work(self, interaction: discord.Interaction) -> None:
        async with SessionLocal() as session:
            user = await get_or_create_user(session, interaction.user.id)
            try:
                result = await ActivityService(session).work(user)
                await EventBus.emit(session, user, "WORK_COMPLETED", {"counter_updates": {"work_runs": 1, "activity_credits_earned": result.credits}})
                await session.commit()
            except ValueError as exc:
                await interaction.response.send_message(str(exc))
                return
        await interaction.response.send_message(result.message)

    @app_commands.command(description="Bet credits on a dice roll.")
    async def dice(self, interaction: discord.Interaction, stake: app_commands.Range[int, 10, 100000]) -> None:
        async with SessionLocal() as session:
            user = await get_or_create_user(session, interaction.user.id)
            try:
                result = await ActivityService(session).dice(user, stake)
                updates = {"gamble_runs": 1}
                if result.credits > 0:
                    updates["gamble_profit"] = result.credits
                await EventBus.emit(session, user, "GAMBLE_DICE", {"counter_updates": updates})
                await session.commit()
            except ValueError as exc:
                await interaction.response.send_message(str(exc))
                return
        await interaction.response.send_message(result.message)

    @app_commands.command(description="Show crafting requirements for an item.")
    async def craft_info(self, interaction: discord.Interaction, item_id: int) -> None:
        async with SessionLocal() as session:
            item = await session.get(Item, item_id)
            if item is None:
                await interaction.response.send_message("Unknown item id.", ephemeral=True)
                return
            if not is_craftable_item(item):
                await interaction.response.send_message("This item is not craftable.", ephemeral=True)
                return
            source_items = (await session.execute(select(Item))).scalars().all()
            source_map = {str((x.metadata_json or {}).get("source_id") or "").lower(): x for x in source_items}
            recipe = crafting_recipe_for_item(item)
        embed = self._styled_embed(title=f"Crafting: {item.name}")
        embed.description = "\n".join(
            f"• {source_map[source_id].name if source_id in source_map else source_id} x{qty}" for source_id, qty in recipe
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(description="Craft a weapon, gadget/throwable, or healing item.")
    async def craft(self, interaction: discord.Interaction, item_id: int, qty: int = 1) -> None:
        async with SessionLocal() as session:
            try:
                result = await craft_item(session, interaction.user.id, item_id=item_id, qty=qty)
            except ValueError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return
        embed = self._styled_embed(title="Crafting complete")
        embed.add_field(name="Crafted", value=f"{result['item'].name} x{result['qty']}", inline=False)
        embed.add_field(name="Materials Used", value="\n".join(f"• {m['name']} x{m['qty']}" for m in result["materials"]), inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

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
    async def trade(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        offered_credits: int = 0,
        requested_credits: int = 0,
        offered_item_id: int | None = None,
        offered_item_qty: int = 0,
        requested_item_id: int | None = None,
        requested_item_qty: int = 0,
    ) -> None:
        if target.bot or target.id == interaction.user.id:
            await interaction.response.send_message("Choose another player as trade target.", ephemeral=True)
            return
        if min(offered_credits, requested_credits, offered_item_qty, requested_item_qty) < 0:
            await interaction.response.send_message("Trade values cannot be negative.", ephemeral=True)
            return
        if offered_credits == requested_credits == 0 and offered_item_qty == requested_item_qty == 0:
            await interaction.response.send_message("Trade must include credits or items.", ephemeral=True)
            return
        if (offered_item_id is None) != (offered_item_qty == 0):
            await interaction.response.send_message("Set both offered item id and qty, or leave both empty.", ephemeral=True)
            return
        if (requested_item_id is None) != (requested_item_qty == 0):
            await interaction.response.send_message("Set both requested item id and qty, or leave both empty.", ephemeral=True)
            return

        offered = {"credits": offered_credits}
        requested = {"credits": requested_credits}
        if offered_item_id is not None and offered_item_qty > 0:
            offered["item_id"] = offered_item_id
            offered["item_qty"] = offered_item_qty
        if requested_item_id is not None and requested_item_qty > 0:
            requested["item_id"] = requested_item_id
            requested["item_qty"] = requested_item_qty

        async with SessionLocal() as session:
            src = await get_or_create_user(session, interaction.user.id)
            dst = await get_or_create_user(session, target.id)
            trade_row = Trade(from_user=src.id, to_user=dst.id, offered=offered, requested=requested, status=TradeStatus.PENDING)
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
