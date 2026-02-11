from datetime import datetime, timedelta, timezone
import asyncio
from pathlib import Path
import random
from typing import Literal
from uuid import uuid4

import discord
from discord import app_commands
from discord.ext import commands, tasks
from sqlalchemy import and_, select

from arkpg.bot.profile_card import render_profile_card
from arkpg.bot.views import PaginatedEmbedView, ProfileEditorView
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
    GameConfig,
    AuditLog,
    UserQuest,
    UserTitle,
    BossNotificationSubscription,
)
from arkpg.db.session import SessionLocal
from arkpg.game.constants import RARITY_COLORS, ZONE_CONFIG
from arkpg.game.profile_backgrounds import PROFILE_BACKGROUNDS, get_background, save_custom_background
from arkpg.game.progression import ActivityService, EventBus, ExpeditionService, QuestService, SeederService, TitleService
from arkpg.game.crafting import crafting_recipe_for_item, is_craftable_item
from arkpg.game.economy import level_from_xp
from arkpg.game.loadout import HEALING_ITEM_FLAT, SHIELD_DAMAGE_REDUCTION, gadget_utility_from_payload, is_gadget, is_healing, is_shield, is_weapon, source_type
from arkpg.game.bosses import FLAVOR_CRITS, FLAVOR_DAMAGE, FLAVOR_SUPPORT, random_boss, weighted_damage_roll
from arkpg.game.raids import RaidAction, RaidState, begin_raid, raid_rewards, resolve_action, strip_equipped_loadout
from arkpg.game.service import (
    atomic_trade_confirm,
    claim_idle,
    craft_item,
    equip_loadout_item,
    unequip_loadout_item,
    extract_deployment,
    get_equipped_loadout,
    collect_profile_background,
    get_or_create_user,
    normalized_profile,
    start_deployment,
    update_user_profile,
    ensure_starter_kit,
)


ADMIN_ROLE_ID = 927355923364720651
ADMIN_GUILD_ID = 927355923314380901
ADMIN_PROFILE_BACKGROUND_PATH = Path(__file__).resolve().parents[2] / "assets" / "admin_staff_team.png"
DUEL_COOLDOWN_SECONDS = 300
TRADE_REF_KEY = "trade_ref"
DEPLOYMENT_CHOICES = [
    app_commands.Choice(
        name=f"{zone} • Risk {int(cfg['risk'] * 100)}% • {int(cfg['duration_min'])} min",
        value=zone,
    )
    for zone, cfg in ZONE_CONFIG.items()
]


def _trade_ref(trade: Trade) -> str:
    requested = trade.requested or {}
    ref = str(requested.get(TRADE_REF_KEY) or "").strip()
    if ref:
        return ref
    return f"legacy-{trade.id}"


def _trade_summary(trade: Trade) -> str:
    offered = trade.offered or {}
    requested = trade.requested or {}
    offered_bits = [f"{int(offered.get('credits', 0) or 0)} Scrap"]
    requested_bits = [f"{int(requested.get('credits', 0) or 0)} Scrap"]
    if offered.get("item_id") and int(offered.get("item_qty", 0) or 0) > 0:
        offered_bits.append(f"item #{int(offered['item_id'])} x{int(offered['item_qty'])}")
    if requested.get("item_id") and int(requested.get("item_qty", 0) or 0) > 0:
        requested_bits.append(f"item #{int(requested['item_id'])} x{int(requested['item_qty'])}")
    return f"Offer: {', '.join(offered_bits)}\nRequest: {', '.join(requested_bits)}"


class _TradeAmountModal(discord.ui.Modal, title="Add Trade Scrap"):
    credits = discord.ui.TextInput(label="Scrap to add", placeholder="0", max_length=10)

    def __init__(self, trade_id: int, owner_id: int):
        super().__init__()
        self.trade_id = trade_id
        self.owner_id = owner_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Only the trade target can edit this trade.", ephemeral=True)
            return
        try:
            delta = int(str(self.credits.value).strip())
        except ValueError:
            await interaction.response.send_message("Scrap must be a whole number.", ephemeral=True)
            return
        if delta <= 0:
            await interaction.response.send_message("Scrap must be greater than zero.", ephemeral=True)
            return
        async with SessionLocal() as session:
            trade = await session.get(Trade, self.trade_id)
            if trade is None or trade.status != TradeStatus.PENDING:
                await interaction.response.send_message("Trade is no longer pending.", ephemeral=True)
                return
            requested = dict(trade.requested or {})
            requested["credits"] = int(requested.get("credits", 0) or 0) + delta
            trade.requested = requested
            actor = await get_or_create_user(session, interaction.user.id)
            session.add(AuditLog(event_type="trade_updated", payload={"trade_ref": _trade_ref(trade), "trade_db_id": trade.id, "actor_discord_id": actor.discord_id, "change": {"requested_credits_delta": delta}}))
            await session.commit()
        await interaction.response.edit_message(content=f"Trade {_trade_ref(trade)} updated.\n{_trade_summary(trade)}")


class _TradeItemModal(discord.ui.Modal, title="Add Trade Item Request"):
    item_id = discord.ui.TextInput(label="Item ID", placeholder="12345", max_length=12)
    qty = discord.ui.TextInput(label="Quantity", placeholder="1", max_length=8)

    def __init__(self, trade_id: int, owner_id: int):
        super().__init__()
        self.trade_id = trade_id
        self.owner_id = owner_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Only the trade target can edit this trade.", ephemeral=True)
            return
        try:
            item_id = int(str(self.item_id.value).strip())
            qty = int(str(self.qty.value).strip())
        except ValueError:
            await interaction.response.send_message("Item ID and quantity must be whole numbers.", ephemeral=True)
            return
        if item_id <= 0 or qty <= 0:
            await interaction.response.send_message("Item ID and quantity must be greater than zero.", ephemeral=True)
            return
        async with SessionLocal() as session:
            trade = await session.get(Trade, self.trade_id)
            if trade is None or trade.status != TradeStatus.PENDING:
                await interaction.response.send_message("Trade is no longer pending.", ephemeral=True)
                return
            requested = dict(trade.requested or {})
            requested["item_id"] = item_id
            requested["item_qty"] = qty
            trade.requested = requested
            actor = await get_or_create_user(session, interaction.user.id)
            session.add(AuditLog(event_type="trade_updated", payload={"trade_ref": _trade_ref(trade), "trade_db_id": trade.id, "actor_discord_id": actor.discord_id, "change": {"requested_item_id": item_id, "requested_item_qty": qty}}))
            await session.commit()
        await interaction.response.edit_message(content=f"Trade {_trade_ref(trade)} updated.\n{_trade_summary(trade)}")


class TradeOfferView(discord.ui.View):
    def __init__(self, trade_id: int, sender_discord_id: int, target_discord_id: int, timeout: float = 900):
        super().__init__(timeout=timeout)
        self.trade_id = trade_id
        self.sender_discord_id = sender_discord_id
        self.target_discord_id = target_discord_id

    @discord.ui.button(label="Add Money", style=discord.ButtonStyle.secondary)
    async def add_money(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(_TradeAmountModal(trade_id=self.trade_id, owner_id=self.target_discord_id))

    @discord.ui.button(label="Add Item", style=discord.ButtonStyle.secondary)
    async def add_item(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await interaction.response.send_modal(_TradeItemModal(trade_id=self.trade_id, owner_id=self.target_discord_id))

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.user.id != self.target_discord_id:
            await interaction.response.send_message("Only the trade target can accept this trade.", ephemeral=True)
            return
        async with SessionLocal() as session:
            trade = await session.get(Trade, self.trade_id)
            if trade is None:
                await interaction.response.send_message("Trade is unavailable.", ephemeral=True)
                return
            trade_ref = _trade_ref(trade)
            try:
                await atomic_trade_confirm(session, self.trade_id)
            except ValueError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return
        await interaction.response.edit_message(content=f"Trade {trade_ref} confirmed.", view=None)

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger)
    async def deny(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.user.id != self.target_discord_id:
            await interaction.response.send_message("Only the trade target can deny this trade.", ephemeral=True)
            return
        async with SessionLocal() as session:
            trade = await session.get(Trade, self.trade_id)
            if trade is None or trade.status != TradeStatus.PENDING:
                await interaction.response.send_message("Trade is no longer pending.", ephemeral=True)
                return
            trade.status = TradeStatus.CANCELLED
            session.add(AuditLog(event_type="trade_denied", payload={"trade_ref": _trade_ref(trade), "trade_db_id": trade.id, "denied_by_discord_id": interaction.user.id}))
            await session.commit()
        await interaction.response.edit_message(content=f"Trade {_trade_ref(trade)} denied.", view=None)



class DuelRequestView(discord.ui.View):
    def __init__(self, cog: "GameplayCog", challenger: discord.abc.User, opponent: discord.abc.User, timeout: float = 90):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.challenger = challenger
        self.opponent = opponent

    @discord.ui.button(label="Accept Duel", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.user.id != self.opponent.id:
            await interaction.response.send_message("Only the challenged player can accept this duel.", ephemeral=True)
            return
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content=f"Duel accepted by {self.opponent.mention}. Resolving...", view=self)
        await self.cog._resolve_duel(interaction, self.challenger, self.opponent)

    @discord.ui.button(label="Deny Duel", style=discord.ButtonStyle.danger)
    async def deny(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.user.id != self.opponent.id:
            await interaction.response.send_message("Only the challenged player can deny this duel.", ephemeral=True)
            return
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(content=f"Duel request denied by {self.opponent.mention}.", view=self)


class RaidEncounterView(discord.ui.View):
    def __init__(self, cog: "GameplayCog", owner_id: int, state: RaidState, rng_seed: int, timeout: float = 240):
        super().__init__(timeout=timeout)
        self.cog = cog
        self.owner_id = owner_id
        self.state = state
        self.rng = random.Random(rng_seed)

    async def _consume_raid_bandage(self, discord_id: int) -> bool:
        async with SessionLocal() as session:
            user = await get_or_create_user(session, discord_id)
            rows = (
                await session.execute(
                    select(Inventory, Item)
                    .join(Item, Inventory.item_id == Item.id)
                    .where(
                        and_(
                            Inventory.user_id == user.id,
                            Inventory.weapon_level.is_(None),
                            Inventory.qty > 0,
                        )
                    )
                    .order_by(Item.base_value.asc())
                )
            ).all()

            bandage_row = next(
                (row for row in rows if "bandage" in str((row[1].metadata_json or {}).get("source_id") or "").lower()),
                None,
            )
            if bandage_row is None:
                return False

            inv, _item = bandage_row
            inv.qty -= 1
            if inv.qty <= 0:
                await session.delete(inv)
            await session.commit()
            return True

    async def _run_action(self, interaction: discord.Interaction, action: RaidAction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This raid belongs to another player.", ephemeral=True)
            return

        can_heal = True
        if action == "heal" and self.state.heals_left > 0:
            can_heal = await self._consume_raid_bandage(interaction.user.id)
        result = resolve_action(self.state, action, self.rng, can_heal=can_heal)
        embed = self.cog._raid_embed(self.state, "\n".join(result.lines))

        if result.raid_over:
            for child in self.children:
                child.disabled = True
            reward_line = await self.cog._finalize_raid(interaction.user.id, self.state, result.player_won, self.rng)
            embed.add_field(name="Outcome", value=reward_line, inline=False)
            await interaction.response.edit_message(embed=embed, view=self)
            self.stop()
            return

        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Attack", style=discord.ButtonStyle.danger)
    async def attack(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._run_action(interaction, "attack")

    @discord.ui.button(label="Dodge", style=discord.ButtonStyle.secondary)
    async def dodge(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._run_action(interaction, "dodge")

    @discord.ui.button(label="Heal", style=discord.ButtonStyle.success)
    async def heal(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._run_action(interaction, "heal")

    @discord.ui.button(label="Retreat", style=discord.ButtonStyle.primary)
    async def retreat(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._run_action(interaction, "retreat")


class BossSignupView(discord.ui.View):
    def __init__(self, cog: "GameplayCog", guild_id: int, spawn_id: str):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild_id = guild_id
        self.spawn_id = spawn_id

    @discord.ui.button(label="Participate", style=discord.ButtonStyle.success)
    async def participate(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        msg = await self.cog.add_boss_participant(self.guild_id, self.spawn_id, interaction.user.id)
        await interaction.response.send_message(msg, ephemeral=True)

    @discord.ui.button(label="Withdraw", style=discord.ButtonStyle.secondary)
    async def withdraw(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        msg = await self.cog.remove_boss_participant(self.guild_id, self.spawn_id, interaction.user.id)
        await interaction.response.send_message(msg, ephemeral=True)

    @discord.ui.button(label="Notify", style=discord.ButtonStyle.primary)
    async def notify(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        msg = await self.cog.toggle_boss_notification_opt_in(self.guild_id, interaction.user.id)
        await interaction.response.send_message(msg, ephemeral=True)


class GameplayCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.settings = get_settings()
        self._boss_state: dict[int, dict] = {}
        self._boss_rng = random.Random()
        self.boss_scheduler.start()

    def cog_unload(self) -> None:
        self.boss_scheduler.cancel()


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

    def _combat_rating(self, user: User, loadout: dict) -> float:
        stats = user.stats or {}
        weapons = [w for w in (loadout.get("weapons") or []) if w]
        weapon_power = sum((float(w.get("value", 0)) / 500) + 2.5 for w in weapons)
        gadget_power = (float((loadout.get("gadget") or {}).get("value", 0)) / 800) if loadout.get("gadget") else 0.0
        shield_bonus = (float((loadout.get("shield") or {}).get("value", 0)) / 900) if loadout.get("shield") else 0.0
        return (
            user.level * 1.35
            + float(stats.get("combat", 10)) * 1.45
            + float(stats.get("tech", 10)) * 0.55
            + float(stats.get("luck", 10)) * 0.9
            + weapon_power
            + gadget_power
            + shield_bonus
        )

    @staticmethod
    def _is_down(user: User) -> bool:
        stats = user.stats or {}
        return int(stats.get("health", stats.get("max_health", 100)) or 0) <= 0

    async def _block_if_down(self, interaction: discord.Interaction, session, *, action_label: str) -> bool:
        user = await get_or_create_user(session, interaction.user.id)
        if self._is_down(user):
            await interaction.response.send_message(
                f"You are at 0 HP and cannot {action_label}. Use /heal to recover.",
                ephemeral=True,
            )
            return True
        return False

    def _raid_embed(self, state: RaidState, narration: str) -> discord.Embed:
        embed = self._styled_embed(title=f"Raid: {state.enemy.name}")
        embed.description = narration
        embed.add_field(name="Your HP", value=f"{state.player_hp}/{state.player_max_hp}", inline=True)
        embed.add_field(name="Enemy HP", value=f"{state.enemy.hp}/{state.enemy.max_hp}", inline=True)
        embed.add_field(name="Med Charges", value=str(state.heals_left), inline=True)
        return embed

    async def _finalize_raid(self, discord_id: int, state: RaidState, player_won: bool, rng: random.Random) -> str:
        async with SessionLocal() as session:
            user = await get_or_create_user(session, discord_id)
            stats = dict(user.stats or {})
            max_hp = int(stats.get("max_health", 100) or 100)
            stats["max_health"] = max_hp
            stats["health"] = max(0, min(max_hp, state.player_hp))
            user.stats = stats

            if player_won:
                xp_reward, scrap_reward = raid_rewards(state.enemy.level, rng)
                user.xp += xp_reward
                user.credits += scrap_reward
                user.level = level_from_xp(user.xp)
                await EventBus.emit(session, user, "RAID_COMPLETED", {"counter_updates": {"raids_won": 1, "activity_credits_earned": scrap_reward}})
                line = f"Victory. +{xp_reward} XP and +{scrap_reward} Scrap secured."
            else:
                hp_loss = max(0, state.player_max_hp - state.player_hp)
                stripped_loadout, lost_items = strip_equipped_loadout(stats.get("loadout"))
                stats["loadout"] = stripped_loadout
                if lost_items:
                    line = (
                        f"Raid failed. You withdraw with {state.player_hp} HP remaining (damage taken: {hp_loss}). "
                        f"Lost equipped items: {', '.join(lost_items)}."
                    )
                else:
                    line = f"Raid failed. You withdraw with {state.player_hp} HP remaining (damage taken: {hp_loss})."

            await session.commit()
            return line

    def _guild_boss_rng(self, guild_id: int) -> random.Random:
        return random.Random((guild_id * 1_000_003) ^ int(self._boss_rng.random() * 1_000_000))

    async def _ensure_boss_schedule(self, guild_id: int) -> dict:
        state = self._boss_state.setdefault(guild_id, {})
        if not state.get("next_spawn"):
            guild_rng = self._guild_boss_rng(guild_id)
            state["next_spawn"] = datetime.now(timezone.utc) + timedelta(minutes=guild_rng.randint(30, 60))
            state["warned"] = False
            state["participants"] = set()
            state["spawn_id"] = f"{guild_id}-{int(state['next_spawn'].timestamp())}"
        return state

    async def toggle_boss_notification_opt_in(self, guild_id: int, discord_id: int) -> str:
        async with SessionLocal() as session:
            existing = (
                await session.execute(
                    select(BossNotificationSubscription).where(
                        and_(
                            BossNotificationSubscription.guild_id == guild_id,
                            BossNotificationSubscription.discord_id == discord_id,
                        )
                    )
                )
            ).scalar_one_or_none()
            if existing:
                await session.delete(existing)
                await session.commit()
                return "Boss DM notifications disabled for this server."

            session.add(BossNotificationSubscription(guild_id=guild_id, discord_id=discord_id))
            await session.commit()
            return "Boss DM notifications enabled for this server."

    async def _notify_boss_subscribers(self, guild: discord.Guild, signup_message: discord.Message) -> None:
        async with SessionLocal() as session:
            rows = (
                await session.execute(
                    select(BossNotificationSubscription).where(BossNotificationSubscription.guild_id == guild.id)
                )
            ).scalars().all()

        jump_link = signup_message.jump_url
        for row in rows:
            member = guild.get_member(row.discord_id)
            if member is None:
                continue
            try:
                await member.send(
                    f"Boss signup is live in **{guild.name}**. Join here: {jump_link}"
                )
            except discord.Forbidden:
                continue

    async def add_boss_participant(self, guild_id: int, spawn_id: str, discord_id: int) -> str:
        state = self._boss_state.get(guild_id)
        if not state or state.get("spawn_id") != spawn_id:
            return "That boss signup is no longer active."
        async with SessionLocal() as session:
            user = await get_or_create_user(session, discord_id)
            loadout = (user.stats or {}).get("loadout", {})
            if not [w for w in (loadout.get("weapons") or []) if w]:
                return "You need a weapon equipped in /loadout to join this boss fight."
        state.setdefault("participants", set()).add(discord_id)
        return "You are locked in for the boss fight."

    async def remove_boss_participant(self, guild_id: int, spawn_id: str, discord_id: int) -> str:
        state = self._boss_state.get(guild_id)
        if not state or state.get("spawn_id") != spawn_id:
            return "That boss signup is no longer active."
        state.setdefault("participants", set()).discard(discord_id)
        return "You withdrew from this boss fight."

    async def _run_boss_fight(self, guild: discord.Guild, channel: discord.TextChannel, state: dict) -> None:
        participants = list(state.get("participants") or set())
        if not participants:
            await channel.send("No raiders committed. The boss signal fades for now.")
            return
        spawn = random_boss(self._boss_rng)
        hp = spawn.max_hp
        damages: dict[int, int] = {uid: 0 for uid in participants}
        alive: set[int] = set()
        ratings: dict[int, float] = {}
        async with SessionLocal() as session:
            for uid in participants:
                user = await get_or_create_user(session, uid)
                loadout = (user.stats or {}).get("loadout", {})
                if not [w for w in (loadout.get("weapons") or []) if w]:
                    continue
                if self._is_down(user):
                    continue
                alive.add(uid)
                ratings[uid] = max(1.0, self._combat_rating(user, loadout))
            await session.commit()
        if not alive:
            await channel.send("All queued raiders are down or unarmed. The boss leaves uncontested.")
            return
        await channel.send(f"⚠️ **{spawn.name}** engaged ({spawn.archetype})! HP: **{hp}**")
        while hp > 0 and alive:
            await asyncio.sleep(30)
            burst = 0
            hitter = self._boss_rng.choice(list(alive))
            dealt = weighted_damage_roll(self._boss_rng, ratings[hitter])
            damages[hitter] += dealt
            burst += dealt
            if len(alive) > 1:
                for uid in self._boss_rng.sample(list(alive), k=min(2, len(alive))):
                    chip = max(8, weighted_damage_roll(self._boss_rng, ratings[uid]) // 4)
                    damages[uid] += chip
                    burst += chip
            hp = max(0, hp - burst)
            crit_line = self._boss_rng.choice(FLAVOR_CRITS).format(user=f"<@{hitter}>", boss=spawn.name)
            await channel.send(f"{crit_line}\nBoss HP: **{hp}/{spawn.max_hp}**")
            struck = self._boss_rng.choice(list(alive))
            harm = self._boss_rng.randint(8, 28)
            async with SessionLocal() as session:
                player = await get_or_create_user(session, struck)
                stats = dict(player.stats or {})
                cur = int(stats.get("health", stats.get("max_health", 100)) or 0)
                stats["health"] = max(0, cur - harm)
                player.stats = stats
                if stats["health"] <= 0:
                    alive.discard(struck)
                    inv_rows = (await session.execute(select(Inventory).where(Inventory.user_id == player.id).limit(1))).scalars().all()
                    if inv_rows and self._boss_rng.random() < 0.35:
                        inv_rows[0].qty = max(0, inv_rows[0].qty - 1)
                        if inv_rows[0].qty == 0:
                            await session.delete(inv_rows[0])
                await session.commit()
            await channel.send(self._boss_rng.choice(FLAVOR_DAMAGE).format(user=f"<@{struck}>", damage=harm))
            if alive:
                support_user = self._boss_rng.choice(list(alive))
                await channel.send(self._boss_rng.choice(FLAVOR_SUPPORT).format(user=f"<@{support_user}>"))

        if hp > 0 and not alive:
            await channel.send("All raiders went down. The boss withdraws into the storm.")
            return

        winner_discord_id = max(damages, key=damages.get)
        async with SessionLocal() as session:
            winner = await get_or_create_user(session, winner_discord_id)
            pool = (await session.execute(select(Item).where(Item.base_value >= 1200).order_by(Item.base_value.desc()).limit(20))).scalars().all()
            if not pool:
                pool = (await session.execute(select(Item).order_by(Item.base_value.desc()).limit(20))).scalars().all()
            reward = self._boss_rng.choice(pool) if pool else None
            if reward:
                inv = (await session.execute(select(Inventory).where(and_(Inventory.user_id == winner.id, Inventory.item_id == reward.id, Inventory.weapon_level.is_(None))))).scalar_one_or_none()
                if inv:
                    inv.qty += 1
                else:
                    session.add(Inventory(user_id=winner.id, item_id=reward.id, qty=1))
            await session.commit()
        await channel.send(f"✅ **{spawn.name}** has been defeated. MVP: <@{winner_discord_id}> ({damages[winner_discord_id]} damage)." + (f" Reward: **{reward.name}**" if reward else ""))

    @tasks.loop(seconds=60)
    async def boss_scheduler(self) -> None:
        if not self.bot.guilds:
            return
        now = datetime.now(timezone.utc)
        for guild in self.bot.guilds:
            async with SessionLocal() as session:
                cfg = (await session.execute(select(GameConfig).where(GameConfig.guild_id == guild.id))).scalar_one_or_none()
            if cfg is None or cfg.boss_channel_id is None:
                continue
            channel = guild.get_channel(cfg.boss_channel_id)
            if not isinstance(channel, discord.TextChannel):
                continue
            state = await self._ensure_boss_schedule(guild.id)
            spawn_at = state["next_spawn"]
            if not state.get("warned") and now >= spawn_at - timedelta(minutes=5):
                state["warned"] = True
                state["participants"] = set()
                view = BossSignupView(self, guild.id, state["spawn_id"])
                signup_message = await channel.send("Boss contact in ~5 minutes. Click below to participate.", view=view)
                await self._notify_boss_subscribers(guild, signup_message)
            if now >= spawn_at:
                await self._run_boss_fight(guild, channel, state)
                guild_rng = self._guild_boss_rng(guild.id)
                self._boss_state[guild.id] = {
                    "next_spawn": now + timedelta(minutes=guild_rng.randint(30, 60)),
                    "warned": False,
                    "participants": set(),
                    "spawn_id": f"{guild.id}-{int(now.timestamp())}",
                }

    @boss_scheduler.before_loop
    async def _before_boss_scheduler(self) -> None:
        await self.bot.wait_until_ready()

    @app_commands.command(description="Browse all player commands.")
    async def help(self, interaction: discord.Interaction) -> None:
        tree_commands = interaction.client.tree.get_commands()
        commands_list = []
        for cmd in self._flatten_commands(tree_commands):
            root_name = cmd.qualified_name.split(" ")[0].lower()
            if root_name in {"config", "wipe", "anti_exploit_log", "give", "items"}:
                continue
            if cmd.name.startswith("admin"):
                continue
            if (cmd.description or "").lower().startswith("admin:"):
                continue
            commands_list.append(cmd)

        entries = sorted(
            [(f"/{cmd.qualified_name}", cmd.description or "No description available.") for cmd in commands_list],
            key=lambda x: x[0],
        )

        pages: list[discord.Embed] = []
        intro = self._styled_embed(title="✨ ARCPG Command Center ✨", color=0xB23A48)
        intro.description = (
            "```ansi\n\u001b[1;31mWELCOME, RAIDER\u001b[0m\n\u001b[0;37mYour tactical command index is online.\u001b[0m\n```\n"
            "Use the buttons below to browse every command."
        )
        intro.add_field(
            name="🔥 What's New",
            value=(
                "• `/salvage item:<name>` now lets you choose from your inventory with type-ahead autocomplete.\n"
                "• `/profile` now displays publicly whether you inspect yourself or another raider.\n"
                "• Weapon crafting for I–IV tiers now scales material requirements by mark tier."
            ),
            inline=False,
        )
        intro.add_field(
            name="🎯 Quick Start",
            value="`/start` • `/deploy` • `/extract` • `/claim` • `/loadout`",
            inline=False,
        )
        intro.set_footer(text="ARCPG Alpha V.0.5 • Page 1")
        pages.append(intro)

        per_page = 8
        total_pages = 1 + max(1, (len(entries) + per_page - 1) // per_page)
        for idx in range(0, len(entries), per_page):
            chunk = entries[idx : idx + per_page]
            embed = self._styled_embed(title="📘 Command Index", color=0x7A1F2B)
            embed.description = "\n".join(f"`{name}`\n↳ {description}" for name, description in chunk)
            page_no = 2 + (idx // per_page)
            embed.set_footer(text=f"ARCPG Alpha V.0.5 • Page {page_no}/{total_pages}")
            pages.append(embed)

        if len(pages) == 1 and not entries:
            pages.append(self._styled_embed(title="📘 Command Index", description="No commands available."))

        view = PaginatedEmbedView(owner_id=interaction.user.id, pages=pages)
        await interaction.response.send_message(embed=view.current_embed(), view=view, ephemeral=True)

    @app_commands.command(description="Set the boss spawn channel for this server.")
    @app_commands.default_permissions(manage_guild=True)
    async def set_boss_channel(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("Guild-only command.", ephemeral=True)
            return
        member = interaction.user if isinstance(interaction.user, discord.Member) else interaction.guild.get_member(interaction.user.id)
        if not isinstance(member, discord.Member) or not member.guild_permissions.manage_guild:
            await interaction.response.send_message("You need Manage Server permission to configure boss channels.", ephemeral=True)
            return
        async with SessionLocal() as session:
            cfg = (await session.execute(select(GameConfig).where(GameConfig.guild_id == interaction.guild.id))).scalar_one_or_none()
            if cfg is None:
                cfg = GameConfig(guild_id=interaction.guild.id)
                session.add(cfg)
            cfg.boss_channel_id = channel.id
            await session.commit()
        self._boss_state.pop(interaction.guild.id, None)
        await interaction.response.send_message(f"Boss encounters will now announce in {channel.mention}.", ephemeral=True)

    @app_commands.command(description="Initialize your raider profile and open the quick-start guide.")
    async def start(self, interaction: discord.Interaction) -> None:
        async with SessionLocal() as session:
            existing = (await session.execute(select(User).where(User.discord_id == interaction.user.id))).scalar_one_or_none()
            user = await get_or_create_user(session, interaction.user.id)
            await SeederService.ensure_seed_data(session)
            if existing is None:
                await ensure_starter_kit(session, user)
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
        page2.add_field(name="3) /claim", value="Collect idle XP and Scrap between active runs.", inline=False)
        page2.set_footer(text="ARCPG Alpha V.0.5 • Page 2/3")
        pages.append(page2)

        page3 = self._styled_embed(title="Profile & Social", color=0x7A1F2B)
        page3.description = "Customize identity and progress with other players."
        page3.add_field(name="Profile", value="Use **/profile** and **/editprofile** to edit callsign, bio, title, and background.", inline=False)
        page3.add_field(name="Progression", value="Use **/titles_list** and **/titles_inspect** to track earned title goals.", inline=False)
        page3.add_field(name="Multiplayer", value="Try **/squad_create**, **/squad_join**, and **/trade**.", inline=False)
        page3.set_footer(text="ARCPG Alpha V.0.5 • Page 3/3")
        pages.append(page3)

        view = PaginatedEmbedView(owner_id=interaction.user.id, pages=pages)
        await interaction.response.send_message(embed=view.current_embed(), view=view, ephemeral=True)

    @app_commands.command(description="Claim your idle XP and Scrap.")
    async def claim(self, interaction: discord.Interaction) -> None:
        async with SessionLocal() as session:
            await SeederService.ensure_seed_data(session)
            user, minutes, xp, credits = await claim_idle(session, self.settings, interaction.user.id)
        embed = self._styled_embed(title="Idle claim complete")
        embed.add_field(name="Recovered Time", value=f"{minutes} min")
        embed.add_field(name="XP", value=f"+{xp}")
        embed.add_field(name="Scrap", value=f"+{credits}")
        materials = (user.stats or {}).get("last_claim_materials", [])
        if isinstance(materials, list) and materials:
            material_text = "\n".join(
                f"• {entry.get('name', 'Unknown')} x{entry.get('qty', 0)}"
                for entry in materials
                if isinstance(entry, dict)
            )
            if material_text:
                embed.add_field(name="Basic Materials", value=material_text, inline=False)
        embed.set_footer(text=f"ARCPG Alpha V.0.5 • Level {user.level}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(description="Start a deployment.")
    @app_commands.choices(zone=DEPLOYMENT_CHOICES)
    async def deploy(self, interaction: discord.Interaction, zone: str) -> None:
        if zone not in ZONE_CONFIG:
            await interaction.response.send_message("Unknown zone. Choose Residential, Industrial, or ARC Site.", ephemeral=True)
            return
        async with SessionLocal() as session:
            await SeederService.ensure_seed_data(session)
            if await self._block_if_down(interaction, session, action_label="start deployments"):
                return
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
        embed.add_field(name="Scrap", value=f"+{outcome['credits']}")
        loot_text = "\n".join(f"• {x['name']} x{x['qty']}" for x in outcome["loot"]) if outcome["loot"] else "No recovered loot"
        embed.add_field(name="Recovered", value=loot_text, inline=False)
        survivability = outcome.get("survivability") or {}
        if survivability:
            embed.add_field(name="Damage", value=f"Taken {survivability.get('effective_damage', 0)} • HP {survivability.get('health_after', '?')}" + (" • Auto-heal used" if survivability.get("healing_used") else ""), inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(description="Start an interactive raid against a random high-level enemy.")
    async def raid(self, interaction: discord.Interaction) -> None:
        async with SessionLocal() as session:
            await SeederService.ensure_seed_data(session)
            if await self._block_if_down(interaction, session, action_label="start raids"):
                return
            user = await get_or_create_user(session, interaction.user.id)
            stats = dict(user.stats or {})
            max_hp = int(stats.get("max_health", 100) or 100)
            hp = int(stats.get("health", max_hp) if stats.get("health") is not None else max_hp)

        rng_seed = int(uuid4().int % (2**32))
        raid_rng = random.Random(rng_seed)
        state, opening = begin_raid(player_level=user.level, player_hp=hp, player_max_hp=max_hp, rng=raid_rng)
        embed = self._raid_embed(state, opening)
        embed.add_field(name="Actions", value="Use the buttons below each turn: Attack, Dodge, Heal, or Retreat.", inline=False)
        view = RaidEncounterView(self, owner_id=interaction.user.id, state=state, rng_seed=rng_seed)
        await interaction.response.send_message(embed=embed, view=view)


    @app_commands.command(description="View your inventory.")
    async def inventory(self, interaction: discord.Interaction) -> None:
        async with SessionLocal() as session:
            user = await get_or_create_user(session, interaction.user.id)
            loadout = (user.stats or {}).get("loadout", {}) if isinstance(user.stats, dict) else {}
            equipped_item_ids = [
                int(payload.get("item_id"))
                for payload in [*(loadout.get("weapons") or []), loadout.get("gadget"), loadout.get("healing"), loadout.get("shield")]
                if isinstance(payload, dict) and payload.get("item_id")
            ]
            rows = (
                await session.execute(
                    select(Inventory, Item)
                    .join(Item, Inventory.item_id == Item.id)
                    .where(and_(Inventory.user_id == user.id, Inventory.weapon_level.is_(None), Inventory.qty > 0))
                    .order_by(Item.name.asc())
                )
            ).all()

        equipped_count: dict[int, int] = {}
        for equipped_item_id in equipped_item_ids:
            equipped_count[equipped_item_id] = equipped_count.get(equipped_item_id, 0) + 1

        visible_rows: list[tuple[Inventory, Item, int]] = []
        for inv, item in rows:
            remaining_qty = int(inv.qty) - int(equipped_count.get(item.id, 0))
            if remaining_qty > 0:
                visible_rows.append((inv, item, remaining_qty))

        if not visible_rows:
            embed = self._styled_embed(title="Field Inventory", description="Your stash is empty.")
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        page_size = 20
        pages: list[discord.Embed] = []
        total_pages = max(1, (len(visible_rows) + page_size - 1) // page_size)
        for index in range(total_pages):
            chunk = visible_rows[index * page_size : (index + 1) * page_size]
            page = self._styled_embed(title="Field Inventory")
            page.description = "\n".join(f"• {item.name} x{remaining_qty}" for _inv, item, remaining_qty in chunk)
            page.set_footer(text=f"Page {index + 1}/{total_pages}")
            pages.append(page)

        view = PaginatedEmbedView(owner_id=interaction.user.id, pages=pages)
        await interaction.response.send_message(embed=view.current_embed(), view=view, ephemeral=True)

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

    async def equip_item_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[int]]:
        slot = str(getattr(interaction.namespace, "slot", "weapon")).lower().strip()
        normalized_slot = "weapon" if slot not in {"weapon", "gadget", "healing", "shield"} else slot
        async with SessionLocal() as session:
            user = await get_or_create_user(session, interaction.user.id)
            rows = (await session.execute(
                select(Inventory, Item)
                .join(Item, Inventory.item_id == Item.id)
                .where(Inventory.user_id == user.id)
                .order_by(Item.name.asc())
            )).all()

        picks: list[app_commands.Choice[int]] = []
        needle = current.strip().lower()
        for inv, item in rows:
            valid_for_slot = (
                (normalized_slot == "weapon" and is_weapon(item))
                or (normalized_slot == "gadget" and is_gadget(item))
                or (normalized_slot == "healing" and is_healing(item))
                or (normalized_slot == "shield" and is_shield(item))
            )
            if not valid_for_slot:
                continue
            if needle and needle not in item.name.lower() and needle not in str(item.id):
                continue
            picks.append(app_commands.Choice(name=f"{item.name} (ID {item.id}) x{inv.qty}", value=item.id))
            if len(picks) >= 25:
                break
        return picks

    async def inventory_item_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[int]]:
        async with SessionLocal() as session:
            user = await get_or_create_user(session, interaction.user.id)
            rows = (await session.execute(
                select(Inventory, Item)
                .join(Item, Inventory.item_id == Item.id)
                .where(and_(Inventory.user_id == user.id, Inventory.weapon_level.is_(None), Inventory.qty > 0))
                .order_by(Item.name.asc())
            )).all()

        needle = current.strip().lower()
        picks: list[app_commands.Choice[int]] = []
        for inv, item in rows:
            if needle and needle not in item.name.lower() and needle not in str(item.id):
                continue
            picks.append(app_commands.Choice(name=f"{item.name} (ID {item.id}) x{inv.qty}", value=item.id))
            if len(picks) >= 25:
                break
        return picks

    async def all_item_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[int]]:
        async with SessionLocal() as session:
            await SeederService.ensure_seed_data(session)
            rows = (await session.execute(select(Item).order_by(Item.name.asc()))).scalars().all()

        needle = current.strip().lower()
        picks: list[app_commands.Choice[int]] = []
        for item in rows:
            if needle and needle not in item.name.lower() and needle not in str(item.id):
                continue
            picks.append(app_commands.Choice(name=f"{item.name} (ID {item.id})", value=item.id))
            if len(picks) >= 25:
                break
        return picks

    async def inventory_healing_item_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[int]]:
        async with SessionLocal() as session:
            user = await get_or_create_user(session, interaction.user.id)
            rows = (
                await session.execute(
                    select(Inventory, Item)
                    .join(Item, Inventory.item_id == Item.id)
                    .where(and_(Inventory.user_id == user.id, Inventory.weapon_level.is_(None), Inventory.qty > 0))
                    .order_by(Item.name.asc())
                )
            ).all()

        needle = current.strip().lower()
        picks: list[app_commands.Choice[int]] = []
        for inv, item in rows:
            if not is_healing(item):
                continue
            if needle and needle not in item.name.lower() and needle not in str(item.id):
                continue
            picks.append(app_commands.Choice(name=f"{item.name} (ID {item.id}) x{inv.qty}", value=item.id))
            if len(picks) >= 25:
                break
        return picks

    async def salvage_item_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        async with SessionLocal() as session:
            user = await get_or_create_user(session, interaction.user.id)
            rows = (
                await session.execute(
                    select(Inventory, Item)
                    .join(Item, Inventory.item_id == Item.id)
                    .where(and_(Inventory.user_id == user.id, Inventory.weapon_level.is_(None), Inventory.qty > 0))
                    .order_by(Item.name.asc())
                )
            ).all()

        needle = current.strip().lower()
        picks: list[app_commands.Choice[str]] = []
        for inv, item in rows:
            source_id = str((item.metadata_json or {}).get("source_id") or "").strip().lower()
            if not source_id:
                continue
            haystack = f"{item.name} {source_id}".lower()
            if needle and needle not in haystack:
                continue
            picks.append(app_commands.Choice(name=f"{item.name} x{inv.qty}", value=source_id))
            if len(picks) >= 25:
                break
        return picks

    async def craftable_item_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[int]]:
        async with SessionLocal() as session:
            rows = (await session.execute(select(Item).order_by(Item.name.asc()))).scalars().all()

        source_ids = {str((row.metadata_json or {}).get("source_id") or "").strip().lower() for row in rows}
        needle = current.strip().lower()
        picks: list[app_commands.Choice[int]] = []
        for item in rows:
            source_id = str((item.metadata_json or {}).get("source_id") or "").strip().lower()
            has_blueprint = bool(source_id) and f"{source_id}_blueprint" in source_ids
            if not is_craftable_item(item) and not has_blueprint:
                continue
            if needle and needle not in item.name.lower() and needle not in str(item.id):
                continue
            picks.append(app_commands.Choice(name=f"{item.name} (ID {item.id})", value=item.id))
            if len(picks) >= 25:
                break
        return picks

    @app_commands.command(description="Equip an item from inventory to a loadout slot.")
    @app_commands.describe(slot="Slot to equip", item_id="Choose an item from your inventory", weapon_slot="Optional; only slot 1 is available for weapons")
    @app_commands.autocomplete(item_id=equip_item_autocomplete)
    async def equip(
        self,
        interaction: discord.Interaction,
        slot: Literal["weapon", "gadget", "healing", "shield"],
        item_id: int,
        weapon_slot: app_commands.Range[int, 1, 1] | None = None,
    ) -> None:
        normalized_slot = slot.strip().lower()

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

    @app_commands.command(description="Unequip an item from a loadout slot back into inventory.")
    @app_commands.describe(slot="Slot to clear", weapon_slot="Optional; only slot 1 is available for weapons")
    async def unequip(
        self,
        interaction: discord.Interaction,
        slot: Literal["weapon", "gadget", "healing", "shield"],
        weapon_slot: app_commands.Range[int, 1, 1] | None = None,
    ) -> None:
        normalized_slot = slot.strip().lower()
        async with SessionLocal() as session:
            try:
                _user, loadout = await unequip_loadout_item(session, interaction.user.id, slot=normalized_slot, weapon_index=weapon_slot)
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

    @app_commands.command(description="View your profile card or inspect another player's profile card.")
    async def profile(self, interaction: discord.Interaction, member: discord.Member | None = None) -> None:
        target_member: discord.abc.User = member or interaction.user
        async with SessionLocal() as session:
            user = await get_or_create_user(session, target_member.id)
            expected_level = level_from_xp(user.xp)
            if user.level != expected_level:
                user.level = expected_level
                await session.commit()
            profile = normalized_profile(user)
            title_row = await session.get(Title, user.equipped_title_id) if user.equipped_title_id else None
            title = title_row.name if title_row else "Unassigned"
            _user, loadout = await get_equipped_loadout(session, target_member.id)

        combat = user.stats.get("combat", 10)
        tech = user.stats.get("tech", 10)
        luck = user.stats.get("luck", 10)
        health_raw = user.stats.get("health")
        max_health_raw = user.stats.get("max_health")
        health = int(health_raw if health_raw is not None else 100)
        max_health = int(max_health_raw if max_health_raw is not None else 100)
        weapons = [w.get("name", "Unknown") for w in (loadout.get("weapons") or []) if w]
        gadget = (loadout.get("gadget") or {}).get("name", "None")
        healing = (loadout.get("healing") or {}).get("name", "None")
        background = get_background(str(profile["background_id"]))
        is_admin = self._is_super_admin(interaction)
        card = await render_profile_card(
            interaction_user=target_member,
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
            health=health,
            max_health=max_health,
            background=background,
            admin_background_path=str(ADMIN_PROFILE_BACKGROUND_PATH) if is_admin else None,
        )
        file = discord.File(card, filename="profile-card.png")
        await interaction.response.send_message(file=file, ephemeral=False)

    @app_commands.command(description="Open a private profile editor with buttons and menus.")
    async def editprofile(self, interaction: discord.Interaction) -> None:
        async with SessionLocal() as session:
            user = await get_or_create_user(session, interaction.user.id)
            profile = normalized_profile(user)
            titles = (
                await session.execute(
                    select(Title)
                    .join(UserTitle, UserTitle.title_id == Title.id)
                    .where(UserTitle.user_id == user.id)
                    .order_by(Title.name.asc())
                )
            ).scalars().all()

        title_options = [discord.SelectOption(label=t.name[:100], value=t.id, description=t.category[:100]) for t in titles]

        collected = set(profile["collected_background_ids"] if isinstance(profile.get("collected_background_ids"), list) else [])
        background_options = [
            discord.SelectOption(label=bg.name[:100], value=bg.id, description=bg.id[:100])
            for bg in PROFILE_BACKGROUNDS.values()
            if bg.id in collected
        ]

        embed = self._styled_embed(title="Profile Editor", description="Use the buttons and menus below to update your profile.")
        embed.add_field(name="Current Callsign", value=str(profile["callsign"]), inline=False)
        embed.add_field(name="Current Bio", value=str(profile["bio"]), inline=False)
        embed.add_field(name="Earned Titles", value="\n".join(f"• {t.name} ({t.id})" for t in titles[:15]) or "No earned titles yet.", inline=False)
        embed.add_field(
            name="Collected Backgrounds",
            value="\n".join(f"• {PROFILE_BACKGROUNDS[bg_id].name} ({bg_id})" for bg_id in sorted(collected)[:15] if bg_id in PROFILE_BACKGROUNDS) or "No backgrounds collected yet.",
            inline=False,
        )
        view = ProfileEditorView(owner_id=interaction.user.id, title_options=title_options, background_options=background_options)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

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


    @app_commands.command(description="Admin: add a custom profile background image.")
    async def background_add_custom(
        self,
        interaction: discord.Interaction,
        background_id: str,
        name: str,
        image: discord.Attachment,
    ) -> None:
        if not self._is_super_admin(interaction):
            await interaction.response.send_message("This admin command is restricted.", ephemeral=True)
            return

        normalized_id = background_id.strip().lower()
        if not normalized_id:
            await interaction.response.send_message("Provide a valid background id.", ephemeral=True)
            return
        ext = Path(image.filename or "").suffix.lower()
        if ext not in {".png", ".jpg", ".jpeg", ".webp"}:
            await interaction.response.send_message("Upload a PNG, JPG, JPEG, or WEBP image.", ephemeral=True)
            return

        target_dir = Path(__file__).resolve().parents[2] / "assets" / "profile_backgrounds" / "custom"
        target_dir.mkdir(parents=True, exist_ok=True)
        local_path = target_dir / f"{normalized_id}{ext}"

        await image.save(local_path)
        save_custom_background(normalized_id, name.strip(), str(local_path))
        async with SessionLocal() as session:
            await collect_profile_background(session, interaction.user.id, normalized_id)

        embed = self._styled_embed(title="Custom Background Added")
        embed.add_field(name="ID", value=normalized_id, inline=False)
        embed.add_field(name="Name", value=name.strip(), inline=False)
        embed.set_image(url=image.url)
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

    @app_commands.command(description="Donate crafting materials to expedition.")
    @app_commands.autocomplete(item_id=inventory_item_autocomplete)
    async def expedition_donate_item(self, interaction: discord.Interaction, item_id: int, qty: int) -> None:
        async with SessionLocal() as session:
            user = await get_or_create_user(session, interaction.user.id)
            try:
                score = await ExpeditionService(session).donate_item(user, item_id, qty)
            except ValueError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return
        await interaction.response.send_message(f"Material donation accepted. Expedition score +{score}.", ephemeral=True)


    @app_commands.command(description="Depart during active departure window.")
    async def expedition_depart(self, interaction: discord.Interaction) -> None:
        async with SessionLocal() as session:
            user = await get_or_create_user(session, interaction.user.id)
            try:
                rewards = await ExpeditionService(session).depart(user)
                await ensure_starter_kit(session, user)
                await session.commit()
            except ValueError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return
        await interaction.response.send_message(f"Departure complete. Permanent: {rewards['permanent']} | Temporary: {rewards['temp']}\nSeason reset applied: inventory cleared, XP reset, level reset, and base stats increased by 25%.", ephemeral=True)

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
            if await self._block_if_down(interaction, session, action_label="scavenge"):
                return
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
    @app_commands.describe(item="Pick an inventory item to salvage (autocomplete enabled)")
    @app_commands.autocomplete(item=salvage_item_autocomplete)
    async def salvage(self, interaction: discord.Interaction, item: str | None = None) -> None:
        async with SessionLocal() as session:
            user = await get_or_create_user(session, interaction.user.id)
            try:
                result = await ActivityService(session).salvage(user, source_id=item)
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
            if await self._block_if_down(interaction, session, action_label="run courier jobs"):
                return
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

    @app_commands.command(description="Work a random side job for Scrap.")
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

    @app_commands.command(description="Bet Scrap on a dice roll.")
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
    @app_commands.autocomplete(item_id=craftable_item_autocomplete)
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

    @app_commands.command(description="Show public item stats and combat-relevant effects.")
    @app_commands.autocomplete(item_id=all_item_autocomplete)
    async def iteminfo(self, interaction: discord.Interaction, item_id: int) -> None:
        async with SessionLocal() as session:
            await SeederService.ensure_seed_data(session)
            item = await session.get(Item, item_id)
            if item is None:
                await interaction.response.send_message("Unknown item id.", ephemeral=True)
                return
        metadata = item.metadata_json or {}
        sid = str(metadata.get("source_id") or "").lower()
        item_kind = source_type(item)
        embed = self._styled_embed(title=f"Item Info: {item.name}", description=str(metadata.get("description") or "No description."))
        embed.add_field(name="ID", value=str(item.id), inline=True)
        embed.add_field(name="Type", value=item_kind.title(), inline=True)
        embed.add_field(name="Rarity", value=item.rarity.value.title(), inline=True)
        embed.add_field(name="Value", value=str(item.base_value), inline=True)

        if is_weapon(item):
            base_damage = max(8, int(item.base_value / 180) + int({"common": 8, "uncommon": 10, "rare": 13, "epic": 17, "legendary": 22}.get(item.rarity.value, 10)))
            embed.add_field(name="Estimated Damage", value=f"{base_damage} per hit", inline=True)
        if is_shield(item):
            reduction = SHIELD_DAMAGE_REDUCTION.get(sid, 0.2)
            embed.add_field(name="Damage Reduction", value=f"{int(reduction * 100)}%", inline=True)
        if is_healing(item):
            heal = HEALING_ITEM_FLAT.get(sid, 35)
            embed.add_field(name="Healing", value=f"Restores {heal} HP", inline=True)
        if is_gadget(item) and not is_healing(item):
            utility_power = gadget_utility_from_payload({
                "source_id": sid,
                "source_type": item_kind,
                "rarity": item.rarity.value,
                "value": item.base_value,
                "description": str(metadata.get("description") or ""),
            })
            embed.add_field(name="Utility Power", value=str(utility_power), inline=True)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(description="Sell an item from your inventory for Scrap.")
    @app_commands.autocomplete(item_id=inventory_item_autocomplete)
    async def sell(self, interaction: discord.Interaction, item_id: int, qty: app_commands.Range[int, 1, 999] = 1) -> None:
        async with SessionLocal() as session:
            user = await get_or_create_user(session, interaction.user.id)
            row = (
                await session.execute(
                    select(Inventory, Item)
                    .join(Item, Inventory.item_id == Item.id)
                    .where(
                        and_(
                            Inventory.user_id == user.id,
                            Inventory.item_id == item_id,
                            Inventory.weapon_level.is_(None),
                            Inventory.qty > 0,
                        )
                    )
                )
            ).first()
            if row is None:
                await interaction.response.send_message("You do not own that item.", ephemeral=True)
                return

            inv, item = row
            if inv.qty < qty:
                await interaction.response.send_message("Not enough quantity in inventory.", ephemeral=True)
                return

            scrap = int(item.base_value) * int(qty)
            inv.qty -= qty
            if inv.qty <= 0:
                await session.delete(inv)
            user.credits += scrap
            await session.commit()

        embed = self._styled_embed(title="Item Sold")
        embed.add_field(name="Item", value=f"{item.name} x{qty}", inline=True)
        embed.add_field(name="Scrap Gained", value=f"+{scrap}", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(description="Craft a weapon, gadget/throwable, or healing item.")
    @app_commands.autocomplete(item_id=craftable_item_autocomplete)
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

    @app_commands.command(description="Use a healing item from your inventory to restore HP.")
    @app_commands.autocomplete(item_id=inventory_healing_item_autocomplete)
    async def heal(self, interaction: discord.Interaction, item_id: int, qty: app_commands.Range[int, 1, 10] = 1) -> None:
        await interaction.response.defer(ephemeral=True)

        async with SessionLocal() as session:
            user = await get_or_create_user(session, interaction.user.id)
            stats = dict(user.stats or {})
            max_hp = int(stats.get("max_health", 100) or 100)
            hp = int(stats.get("health", max_hp) if stats.get("health") is not None else max_hp)
            if hp >= max_hp:
                await interaction.followup.send("Your HP is already full.", ephemeral=True)
                return

            row = (
                await session.execute(
                    select(Inventory, Item).join(Item, Inventory.item_id == Item.id).where(
                        and_(Inventory.user_id == user.id, Inventory.item_id == item_id, Inventory.weapon_level.is_(None))
                    )
                )
            ).first()
            if row is None:
                await interaction.followup.send("You do not own that item.", ephemeral=True)
                return

            inv, item = row
            if not is_healing(item):
                await interaction.followup.send("That item is not a healing item.", ephemeral=True)
                return
            if inv.qty < qty:
                await interaction.followup.send("Not enough quantity in inventory.", ephemeral=True)
                return

            sid = str((item.metadata_json or {}).get("source_id") or "").lower()
            per_item = HEALING_ITEM_FLAT.get(sid, 35)
            healed = per_item * qty
            new_hp = min(max_hp, hp + healed)
            applied = new_hp - hp

            inv.qty -= qty
            if inv.qty <= 0:
                await session.delete(inv)

            stats["max_health"] = max_hp
            stats["health"] = new_hp
            user.stats = stats
            await session.commit()

        embed = self._styled_embed(title="Healing Applied")
        embed.add_field(name="Item", value=f"{item.name} x{qty}", inline=True)
        embed.add_field(name="HP Restored", value=str(applied), inline=True)
        embed.add_field(name="Current HP", value=f"{new_hp}", inline=True)
        try:
            await interaction.followup.send(embed=embed, ephemeral=True)
        except discord.NotFound:
            return

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

    async def _resolve_duel(self, interaction: discord.Interaction, challenger: discord.abc.User, opponent: discord.abc.User) -> None:
        async with SessionLocal() as session:
            me = await get_or_create_user(session, challenger.id)
            them = await get_or_create_user(session, opponent.id)
            _me_user, my_loadout = await get_equipped_loadout(session, challenger.id)
            _them_user, their_loadout = await get_equipped_loadout(session, opponent.id)
            my_power = self._combat_rating(me, my_loadout)
            their_power = self._combat_rating(them, their_loadout)
            roll_me = random.uniform(0.82, 1.18)
            roll_them = random.uniform(0.82, 1.18)
            i_win = (my_power * roll_me) >= (their_power * roll_them)

            winner_user = me if i_win else them
            loser_user = them if i_win else me
            winner_member = challenger if i_win else opponent
            loser_member = opponent if i_win else challenger

            if i_win:
                await EventBus.emit(session, me, "PVP_WIN", {"counter_updates": {"pvp_wins": 1, "pvp_fair_wins": 1}})
            xp_reward = random.randint(14, 26)
            scrap_reward = random.randint(90, 170)
            winner_user.xp += xp_reward
            winner_user.credits += scrap_reward
            winner_user.level = level_from_xp(winner_user.xp)

            loser_stats = dict(loser_user.stats or {})
            max_hp = int(loser_stats.get("max_health", 100) or 100)
            loser_hp = int(loser_stats.get("health", max_hp) or max_hp)
            hp_penalty = random.randint(12, 22)
            loser_stats["health"] = max(0, loser_hp - hp_penalty)
            loser_user.stats = loser_stats
            now = datetime.now(timezone.utc)
            me_prog = dict(me.progression_json or {})
            me_prog["duel_cd_until"] = (now + timedelta(seconds=DUEL_COOLDOWN_SECONDS)).isoformat()
            me.progression_json = me_prog

            await session.commit()

        flavor_pool = [
            f"{winner_member.mention} baited a reload and landed the finishing burst on {loser_member.mention}.",
            f"{loser_member.mention} had the early advantage, but {winner_member.mention} turned it around with better positioning.",
            f"A chaos grenade broke the tempo and {winner_member.mention} capitalized first against {loser_member.mention}.",
            f"After a long standoff, {winner_member.mention} committed to the push and won the duel over {loser_member.mention}.",
            f"Both raiders traded heavy hits, but {winner_member.mention} survived the final exchange.",
            f"The arena lights flickered and {winner_member.mention} used the opening to outplay {loser_member.mention}.",
        ]
        upset = abs(my_power - their_power) > 6 and ((i_win and my_power < their_power) or ((not i_win) and their_power < my_power))
        flavor = random.choice(flavor_pool) + (" **Upset win!**" if upset else "")
        await interaction.followup.send(
            f"{flavor}\n"
            f"Duel: {challenger.mention} vs {opponent.mention}.\n"
            f"Power check: **{my_power:.1f}** vs **{their_power:.1f}**.\n"
            f"Winner reward: **+{xp_reward} XP**, **+{scrap_reward} Scrap**. "
            f"Loser penalty: **-{hp_penalty} HP**."
        )

    @app_commands.command(description="Challenge another player to a duel.")
    async def duel(self, interaction: discord.Interaction, opponent: discord.Member) -> None:
        if opponent.bot:
            await interaction.response.send_message("Bots cannot duel.", ephemeral=True)
            return
        if opponent.id == interaction.user.id:
            await interaction.response.send_message("You cannot duel yourself.", ephemeral=True)
            return
        async with SessionLocal() as session:
            me = await get_or_create_user(session, interaction.user.id)
            if self._is_down(me):
                await interaction.response.send_message("You are at 0 HP and cannot duel. Use /heal to recover.", ephemeral=True)
                return
            duel_cd = (me.progression_json or {}).get("duel_cd_until")
            if duel_cd:
                duel_ready = datetime.fromisoformat(str(duel_cd))
                if duel_ready.tzinfo is None:
                    duel_ready = duel_ready.replace(tzinfo=timezone.utc)
                if duel_ready > datetime.now(timezone.utc):
                    await interaction.response.send_message(f"Duel cooldown active. Try again {self._relative_time(duel_ready)}.", ephemeral=True)
                    return

            them = await get_or_create_user(session, opponent.id)
            if self._is_down(them):
                await interaction.response.send_message("That opponent is at 0 HP and cannot duel right now.", ephemeral=True)
                return
            if abs(me.level - them.level) > 8:
                await interaction.response.send_message("Level difference too large. Find a closer rival.", ephemeral=True)
                return

        view = DuelRequestView(self, challenger=interaction.user, opponent=opponent)
        await interaction.response.send_message(
            f"{opponent.mention}, {interaction.user.mention} challenged you to a duel. Accept or deny below.",
            view=view,
            allowed_mentions=discord.AllowedMentions(users=True),
        )

    @app_commands.command(description="Create a pending trade offer.")
    @app_commands.autocomplete(offered_item_id=inventory_item_autocomplete, requested_item_id=inventory_item_autocomplete)
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
            await interaction.response.send_message("Trade must include Scrap or items.", ephemeral=True)
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
            existing_pending = (
                await session.execute(
                    select(Trade).where(
                        and_(
                            Trade.status == TradeStatus.PENDING,
                            (Trade.from_user.in_([src.id, dst.id]) | Trade.to_user.in_([src.id, dst.id])),
                        )
                    ).limit(1)
                )
            ).scalar_one_or_none()
            if existing_pending is not None:
                await interaction.response.send_message(
                    f"A pending trade already exists for one of the players in this trade ({_trade_ref(existing_pending)}).",
                    ephemeral=True,
                )
                return
            requested[TRADE_REF_KEY] = str(uuid4())
            trade_row = Trade(from_user=src.id, to_user=dst.id, offered=offered, requested=requested, status=TradeStatus.PENDING)
            session.add(trade_row)
            await session.flush()
            session.add(
                AuditLog(
                    event_type="trade_created",
                    payload={
                        "trade_ref": requested[TRADE_REF_KEY],
                        "trade_db_id": trade_row.id,
                        "from_discord_id": interaction.user.id,
                        "to_discord_id": target.id,
                        "offered": offered,
                        "requested": requested,
                    },
                )
            )
            await session.commit()
        view = TradeOfferView(trade_id=trade_row.id, sender_discord_id=interaction.user.id, target_discord_id=target.id)
        await interaction.response.send_message(f"Trade {_trade_ref(trade_row)} sent to {target.mention}.", ephemeral=True)
        await interaction.channel.send(
            f"Trade {_trade_ref(trade_row)} started by {interaction.user.mention} for {target.mention}.\n{_trade_summary(trade_row)}",
            view=view,
            allowed_mentions=discord.AllowedMentions(users=True),
        )

    @app_commands.command(description="Confirm a trade by trade reference ID.")
    async def trade_confirm(self, interaction: discord.Interaction, trade_ref: str) -> None:
        trade_ref = trade_ref.strip()
        if not trade_ref:
            await interaction.response.send_message("Provide a trade reference ID.", ephemeral=True)
            return
        async with SessionLocal() as session:
            trade = (
                await session.execute(
                    select(Trade).where(Trade.requested[TRADE_REF_KEY].as_string() == trade_ref)
                )
            ).scalar_one_or_none()
            if trade is None:
                await interaction.response.send_message("Trade not found.", ephemeral=True)
                return
            actor = await get_or_create_user(session, interaction.user.id)
            if actor.id != trade.to_user:
                await interaction.response.send_message("Only the trade target can confirm this trade.", ephemeral=True)
                return
            try:
                await atomic_trade_confirm(session, trade.id)
                await EventBus.emit(session, actor, "TRADE_COMPLETED", {"counter_updates": {"trade_completed": 1}})
                await session.commit()
            except ValueError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return
        await interaction.response.send_message(f"Trade {trade_ref} confirmed.", ephemeral=True)

    @app_commands.command(description="Cancel your currently pending outgoing trade.")
    async def canceltrade(self, interaction: discord.Interaction) -> None:
        async with SessionLocal() as session:
            actor = await get_or_create_user(session, interaction.user.id)
            trade = (
                await session.execute(
                    select(Trade).where(
                        and_(Trade.from_user == actor.id, Trade.status == TradeStatus.PENDING)
                    )
                )
            ).scalar_one_or_none()
            if trade is None:
                await interaction.response.send_message("You have no pending outgoing trade to cancel.", ephemeral=True)
                return
            trade.status = TradeStatus.CANCELLED
            session.add(
                AuditLog(
                    event_type="trade_cancelled",
                    payload={
                        "trade_ref": _trade_ref(trade),
                        "trade_db_id": trade.id,
                        "cancelled_by_discord_id": interaction.user.id,
                    },
                )
            )
            await session.commit()
        await interaction.response.send_message(f"Trade {_trade_ref(trade)} cancelled.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GameplayCog(bot))
