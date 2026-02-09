from __future__ import annotations

import hashlib
import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from arkpg.db.models import (
    ActivityAttempt,
    Expedition,
    ExpeditionContribution,
    ExpeditionStage,
    ExpeditionStatus,
    Inventory,
    Item,
    ItemType,
    Quest,
    QuestStatus,
    Title,
    Trade,
    TradeStatus,
    User,
    UserExpeditionState,
    UserQuest,
    UserTitle,
)
from arkpg.game.items import infer_rarity, load_items
from arkpg.game.quest_catalog import QUESTS
from arkpg.game.title_catalog import TITLE_RULE_MAP, TITLE_RULES

RARITY_MULTIPLIER = {"common": 1.0, "uncommon": 1.3, "rare": 1.7, "epic": 2.4, "legendary": 3.2}


def as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class EventBus:
    @staticmethod
    async def emit(session: AsyncSession, user: User, event_type: str, payload: dict) -> list[str]:
        counters = dict(user.progression_json or {})
        counters[event_type] = int(counters.get(event_type, 0)) + 1
        if "counter_updates" in payload:
            for key, delta in payload["counter_updates"].items():
                counters[key] = int(counters.get(key, 0)) + int(delta)
        if payload.get("set_level"):
            counters["level"] = payload["set_level"]
        user.progression_json = counters

        title_service = TitleService(session)
        quest_service = QuestService(session)
        earned = await title_service.evaluate_user(user, event_type, payload)
        await quest_service.apply_event(user, event_type, payload)
        return earned


class SeederService:
    @staticmethod
    def _normalize_rarity(value: str | None, item_value: int = 0) -> str:
        return infer_rarity(value, item_value)

    @staticmethod
    def _normalize_type(value: str | None) -> ItemType:
        lowered = str(value or "component").lower().strip()
        if lowered == "blueprint":
            return ItemType.BLUEPRINT
        if lowered == "recyclable":
            return ItemType.RECYCLABLE

        weapon_types = {
            "rifle", "burst rifle", "smg", "shotgun", "sniper", "lmg", "pistol", "hand cannon", "bow",
            "weapon", "melee", "launcher", "arc weapon",
        }
        armor_types = {"armor", "helmet", "chest", "boots", "gauntlets", "shield"}
        gadget_types = {"quick use", "modification", "deployable", "gadget", "consumable"}

        if lowered in weapon_types:
            return ItemType.WEAPON
        if lowered in armor_types:
            return ItemType.ARMOR
        if lowered in gadget_types:
            return ItemType.GADGET
        return ItemType.COMPONENT

    @staticmethod
    async def ensure_seed_data(session: AsyncSession) -> None:
        if (await session.execute(select(Title.id).limit(1))).scalar_one_or_none() is None:
            for rule in TITLE_RULES:
                session.add(Title(id=rule.id, name=rule.name, description=rule.description, category=rule.category, rarity=rule.rarity, is_hidden=rule.is_hidden, how_to_earn=rule.how_to_earn))

        if (await session.execute(select(Quest.id).limit(1))).scalar_one_or_none() is None:
            for q in QUESTS:
                session.add(Quest(**q, is_sidequest=False))

        if (await session.execute(select(Item.id).limit(1))).scalar_one_or_none() is None:
            for item in load_items():
                session.add(
                    Item(
                        name=item.name,
                        type=SeederService._normalize_type(item.type),
                        rarity=SeederService._normalize_rarity(item.rarity, item.value),
                        base_value=item.value,
                        metadata_json={"foundIn": list(item.found_in), "icon": item.icon, "description": item.description, "source_id": item.id},
                    )
                )

        await session.commit()


class InventoryService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add_item(self, user_id: int, item_id: int, qty: int) -> None:
        row = (await self.session.execute(select(Inventory).where(and_(Inventory.user_id == user_id, Inventory.item_id == item_id, Inventory.weapon_level.is_(None))).with_for_update())).scalar_one_or_none()
        if row:
            row.qty += qty
        else:
            self.session.add(Inventory(user_id=user_id, item_id=item_id, qty=qty))

    async def remove_item(self, user_id: int, item_id: int, qty: int) -> None:
        row = (await self.session.execute(select(Inventory).where(and_(Inventory.user_id == user_id, Inventory.item_id == item_id, Inventory.weapon_level.is_(None))).with_for_update())).scalar_one_or_none()
        if row is None or row.qty < qty:
            raise ValueError("Not enough items in inventory.")
        row.qty -= qty
        if row.qty == 0:
            await self.session.delete(row)


class TitleService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def evaluate_user(self, user: User, event_type: str, payload: dict) -> list[str]:
        counters = user.progression_json or {}
        earned: list[str] = []
        for rule in TITLE_RULES:
            existing = (await self.session.execute(select(UserTitle.id).where(and_(UserTitle.user_id == user.id, UserTitle.title_id == rule.id)))).scalar_one_or_none()
            if existing:
                continue
            if rule.complete_fn(counters):
                self.session.add(UserTitle(user_id=user.id, title_id=rule.id, source_event={"event_type": event_type, "payload": payload}))
                if not user.equipped_title_id:
                    user.equipped_title_id = rule.id
                earned.append(rule.name)
        await self.session.commit()
        return earned

    async def progress_for(self, user: User, title_id: str) -> float:
        rule = TITLE_RULE_MAP.get(title_id)
        if not rule:
            return 0.0
        return rule.progress_fn(user.progression_json or {})


class QuestService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def ensure_track(self, user: User) -> None:
        current = (await self.session.execute(select(UserQuest).where(UserQuest.user_id == user.id))).scalars().all()
        if current:
            return
        for q in sorted(QUESTS, key=lambda x: (x["chapter"], x["order_index"])):
            status = QuestStatus.ACTIVE if q["chapter"] == 1 and q["order_index"] == 1 else QuestStatus.LOCKED
            self.session.add(UserQuest(user_id=user.id, quest_id=q["id"], status=status, progress={}, started_at=datetime.now(timezone.utc) if status == QuestStatus.ACTIVE else None))
        await self.session.commit()

    def _requirement_value(self, req: dict, counters: dict) -> tuple[int, int]:
        if req["type"] == "counter":
            return int(counters.get(req["key"], 0)), int(req["count"])
        if req["type"] == "activity_count":
            return int(counters.get(f"{req['activity']}_runs", 0)), int(req["count"])
        if req["type"] == "collect_rarity":
            return int(counters.get(f"collect_{req['rarity']}_owned", 0)), int(req["count"])
        if req["type"] == "collect_found_in":
            return int(counters.get(f"collect_foundin_{req['found_in']}", 0)), int(req["count"])
        if req["type"] == "multi":
            vals = [self._requirement_value(x, counters) for x in req["all"]]
            return sum(a for a, _ in vals), sum(b for _, b in vals)
        return 0, 1

    async def apply_event(self, user: User, event_type: str, payload: dict) -> None:
        await self.ensure_track(user)
        active = (await self.session.execute(select(UserQuest, Quest).join(Quest, UserQuest.quest_id == Quest.id).where(and_(UserQuest.user_id == user.id, UserQuest.status == QuestStatus.ACTIVE)))).all()
        counters = user.progression_json or {}
        for uq, q in active:
            cur, target = self._requirement_value(q.requirements, counters)
            uq.progress = {"current": cur, "target": target}
            if cur >= target:
                uq.status = QuestStatus.COMPLETED
                uq.completed_at = datetime.now(timezone.utc)
                rewards = q.rewards or {}
                user.credits += int(rewards.get("credits", 0))
                user.xp += int(rewards.get("xp", 0))
                if rewards.get("perk"):
                    pr = dict(user.progression_json or {})
                    for k, v in rewards["perk"].items():
                        pr[f"perk_{k}"] = int(pr.get(f"perk_{k}", 0)) + int(v)
                    user.progression_json = pr
                if rewards.get("title_unlock"):
                    if (await self.session.execute(select(UserTitle).where(and_(UserTitle.user_id == user.id, UserTitle.title_id == rewards["title_unlock"])))).scalar_one_or_none() is None:
                        self.session.add(UserTitle(user_id=user.id, title_id=rewards["title_unlock"], source_event={"event_type": "quest_reward", "quest_id": q.id}))
                nxt = (await self.session.execute(select(UserQuest, Quest).join(Quest, UserQuest.quest_id == Quest.id).where(and_(UserQuest.user_id == user.id, UserQuest.status == QuestStatus.LOCKED)).order_by(Quest.chapter.asc(), Quest.order_index.asc()).limit(1))).first()
                if nxt:
                    n_uq, _ = nxt
                    n_uq.status = QuestStatus.ACTIVE
                    n_uq.started_at = datetime.now(timezone.utc)
        await self.session.commit()


@dataclass
class ActivityResult:
    seed: str
    success: bool
    credits: int
    items: list[tuple[int, int]]
    message: str


class ActivityService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _seed(self, user_id: int, activity: str) -> str:
        now = datetime.now(timezone.utc).isoformat()
        return hashlib.sha256(f"{user_id}:{activity}:{now}".encode()).hexdigest()[:32]

    async def _check_cd(self, user_id: int, activity: str, seconds: int) -> None:
        last = (await self.session.execute(select(ActivityAttempt).where(and_(ActivityAttempt.user_id == user_id, ActivityAttempt.activity_type == activity)).order_by(ActivityAttempt.created_at.desc()).limit(1))).scalar_one_or_none()
        if last and (datetime.now(timezone.utc) - as_utc(last.created_at)).total_seconds() < seconds:
            raise ValueError(f"{activity} cooldown active.")

    async def scavenge(self, user: User) -> ActivityResult:
        await self._check_cd(user.id, "scavenge", 45)
        seed = await self._seed(user.id, "scavenge")
        rng = random.Random(seed)
        items = (await self.session.execute(select(Item).limit(25))).scalars().all()
        picked = rng.choice(items)
        qty = rng.randint(1, 2)
        credits = rng.randint(20, 80)
        event = "mini-event triggered" if rng.random() < 0.2 else "quiet pickup"
        await InventoryService(self.session).add_item(user.id, picked.id, qty)
        user.credits += credits
        self.session.add(ActivityAttempt(user_id=user.id, activity_type="scavenge", seed=seed, result={"item_id": picked.id, "qty": qty, "credits": credits, "event": event}))
        return ActivityResult(seed, True, credits, [(picked.id, qty)], f"Recovered {picked.name} x{qty} ({event}).")

    async def salvage(self, user: User) -> ActivityResult:
        await self._check_cd(user.id, "salvage", 60)
        seed = await self._seed(user.id, "salvage")
        rng = random.Random(seed)
        inv = (await self.session.execute(select(Inventory, Item).join(Item, Inventory.item_id == Item.id).where(Inventory.user_id == user.id).limit(1))).first()
        if not inv:
            raise ValueError("Need at least one item to salvage.")
        inv_row, item = inv
        await InventoryService(self.session).remove_item(user.id, item.id, 1)
        credits = int(item.base_value * (1.1 + rng.random() * 0.8))
        user.credits += credits
        jackpot = rng.random() < 0.15
        reward_items: list[tuple[int, int]] = []
        if jackpot:
            refined = (await self.session.execute(select(Item).where(Item.base_value >= 120).limit(1))).scalar_one_or_none()
            if refined:
                await InventoryService(self.session).add_item(user.id, refined.id, 1)
                reward_items.append((refined.id, 1))
        self.session.add(ActivityAttempt(user_id=user.id, activity_type="salvage", seed=seed, result={"credits": credits, "jackpot": jackpot}))
        return ActivityResult(seed, True, credits, reward_items, "Salvage complete.")

    async def courier(self, user: User, stake: int) -> ActivityResult:
        await self._check_cd(user.id, "courier", 75)
        if stake < 10:
            raise ValueError("Stake must be >= 10 credits.")
        if user.credits < stake:
            raise ValueError("Not enough credits for stake.")
        seed = await self._seed(user.id, "courier")
        rng = random.Random(seed)
        user.credits -= stake
        success = rng.random() >= 0.25
        payout = int(stake * (1.5 + rng.random() * 1.2)) if success else 0
        if success:
            user.credits += payout
        self.session.add(ActivityAttempt(user_id=user.id, activity_type="courier", seed=seed, result={"stake": stake, "success": success, "payout": payout}))
        return ActivityResult(seed, success, payout - stake if success else -stake, [], "Courier success." if success else "Courier run failed.")


class ExpeditionService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def active(self) -> Expedition | None:
        return (await self.session.execute(select(Expedition).where(Expedition.status.in_([ExpeditionStatus.ACTIVE, ExpeditionStatus.DEPARTURE])).order_by(Expedition.season_number.desc()).limit(1))).scalar_one_or_none()

    async def create_default(self, season_number: int) -> Expedition:
        now = datetime.now(timezone.utc)
        exp = Expedition(season_number=season_number, starts_at=now, ends_at=now + timedelta(days=21), departure_starts_at=now + timedelta(days=21), departure_ends_at=now + timedelta(days=28), status=ExpeditionStatus.ACTIVE, config={"min_depart_score": 500, "catchup_discount": 0.35})
        self.session.add(exp)
        await self.session.flush()
        stages = [
            (1, "Outpost Foundation", {"credits": 15000, "rarity": {"common": 150}}),
            (2, "Power Routing", {"credits": 22000, "rarity": {"uncommon": 120}}),
            (3, "Hull Assembly", {"credits": 30000, "rarity": {"rare": 80}}),
            (4, "Navigation Stack", {"credits": 36000, "rarity": {"epic": 35}}),
            (5, "Departure Prep", {"credits": 45000, "rarity": {"legendary": 12}}),
        ]
        for num, name, req in stages:
            self.session.add(ExpeditionStage(expedition_id=exp.id, stage_number=num, name=name, requirements=req, contributed={"credits": 0, "rarity": defaultdict(int)}))
        await self.session.commit()
        return exp

    async def donate_item(self, user: User, item_id: int, qty: int) -> int:
        exp = await self.active()
        if not exp or exp.status != ExpeditionStatus.ACTIVE:
            raise ValueError("No active expedition accepts donations.")
        item = await self.session.get(Item, item_id)
        if not item:
            raise ValueError("Item not found.")
        await InventoryService(self.session).remove_item(user.id, item_id, qty)
        score = int(item.base_value * RARITY_MULTIPLIER.get(str(item.rarity), 1.0) * qty)
        await self._apply_contribution(exp, user, score, {str(item_id): qty}, 0, item_rarity=str(item.rarity), qty=qty)
        return score

    async def donate_credits(self, user: User, credits: int) -> int:
        exp = await self.active()
        if not exp or exp.status != ExpeditionStatus.ACTIVE:
            raise ValueError("No active expedition accepts donations.")
        if credits <= 0 or user.credits < credits:
            raise ValueError("Insufficient credits.")
        user.credits -= credits
        score = credits
        await self._apply_contribution(exp, user, score, {}, credits)
        return score

    async def _apply_contribution(self, exp: Expedition, user: User, score: int, item_map: dict[str, int], credits: int, item_rarity: str | None = None, qty: int = 0) -> None:
        contrib = (await self.session.execute(select(ExpeditionContribution).where(and_(ExpeditionContribution.expedition_id == exp.id, ExpeditionContribution.user_id == user.id)).with_for_update())).scalar_one_or_none()
        if contrib is None:
            contrib = ExpeditionContribution(expedition_id=exp.id, user_id=user.id, contributed_items={}, contributed_credits=0, score=0)
            self.session.add(contrib)
        citems = dict(contrib.contributed_items or {})
        for k, v in item_map.items():
            citems[k] = int(citems.get(k, 0)) + v
        contrib.contributed_items = citems
        contrib.contributed_credits += credits
        contrib.score += score
        contrib.updated_at = datetime.now(timezone.utc)

        stage = (await self.session.execute(select(ExpeditionStage).where(and_(ExpeditionStage.expedition_id == exp.id, ExpeditionStage.is_complete.is_(False))).order_by(ExpeditionStage.stage_number.asc()).limit(1).with_for_update())).scalar_one_or_none()
        if stage:
            data = dict(stage.contributed or {"credits": 0, "rarity": {}})
            data["credits"] = int(data.get("credits", 0)) + credits
            rarity_map = dict(data.get("rarity", {}))
            if item_rarity:
                rarity_map[item_rarity] = int(rarity_map.get(item_rarity, 0)) + qty
            data["rarity"] = rarity_map
            stage.contributed = data
            req = stage.requirements or {}
            req_rarity = req.get("rarity", {})
            complete = data.get("credits", 0) >= req.get("credits", 0) and all(rarity_map.get(r, 0) >= n for r, n in req_rarity.items())
            if complete:
                stage.is_complete = True
                stage.completed_at = datetime.now(timezone.utc)

        await EventBus.emit(self.session, user, "EXPEDITION_DONATED", {"counter_updates": {"expedition_score": score, "expedition_items_donated": sum(item_map.values())}})
        await self.session.commit()

    async def depart(self, user: User) -> dict:
        exp = await self.active()
        if not exp or exp.status != ExpeditionStatus.DEPARTURE:
            raise ValueError("Departure window is not open.")
        contrib = (await self.session.execute(select(ExpeditionContribution).where(and_(ExpeditionContribution.expedition_id == exp.id, ExpeditionContribution.user_id == user.id)).with_for_update())).scalar_one_or_none()
        min_score = int(exp.config.get("min_depart_score", 500))
        if not contrib or contrib.score < min_score:
            raise ValueError("Contribution threshold not met.")

        state = await self.session.get(UserExpeditionState, user.id, with_for_update=True)
        if state is None:
            state = UserExpeditionState(user_id=user.id, permanent_rewards={}, temp_buffs={}, catchup_state={})
            self.session.add(state)

        permanent = dict(state.permanent_rewards or {})
        permanent["stash_slots"] = int(permanent.get("stash_slots", 0)) + (1 if contrib.score >= min_score else 0)
        permanent["stat_points"] = int(permanent.get("stat_points", 0)) + (1 if contrib.score >= min_score * 2 else 0)
        state.permanent_rewards = permanent

        tb = dict(state.temp_buffs or {})
        stacks = int(tb.get("stacks", 0)) + 1
        stacks = min(stacks, 3)
        tb.update({"stacks": stacks, "xp_bonus": 0.05 * stacks, "scrap_bonus": 0.04 * stacks, "repair_bonus": 0.03 * stacks, "expires_at": exp.departure_ends_at.isoformat()})
        state.temp_buffs = tb
        state.last_departed_expedition_id = exp.id

        catchup = dict(state.catchup_state or {})
        catchup["missed_points"] = max(0, int(catchup.get("missed_points", 0)) - 1)
        state.catchup_state = catchup

        await EventBus.emit(self.session, user, "EXPEDITION_DEPARTED", {"counter_updates": {"expeditions_departed": 1}})
        await self.session.commit()
        return {"permanent": permanent, "temp": tb, "score": contrib.score}
