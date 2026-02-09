import enum
from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Enum, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from arkpg.db.base import Base


class Rarity(str, enum.Enum):
    COMMON = "common"
    UNCOMMON = "uncommon"
    RARE = "rare"
    EPIC = "epic"
    LEGENDARY = "legendary"


class ItemType(str, enum.Enum):
    WEAPON = "weapon"
    ARMOR = "armor"
    GADGET = "gadget"
    COMPONENT = "component"
    BLUEPRINT = "blueprint"
    RECYCLABLE = "recyclable"


class DeploymentStatus(str, enum.Enum):
    ACTIVE = "active"
    READY_TO_EXTRACT = "ready_to_extract"
    EXTRACTED = "extracted"
    FAILED = "failed"


class TradeStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class QuestStatus(str, enum.Enum):
    LOCKED = "locked"
    ACTIVE = "active"
    COMPLETED = "completed"


class ExpeditionStatus(str, enum.Enum):
    PREPARING = "preparing"
    ACTIVE = "active"
    DEPARTURE = "departure"
    CLOSED = "closed"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (Index("ix_users_discord_id", "discord_id", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    discord_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    last_claim_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    xp: Mapped[int] = mapped_column(Integer, default=0)
    level: Mapped[int] = mapped_column(Integer, default=1)
    credits: Mapped[int] = mapped_column(Integer, default=0)
    equipped_title_id: Mapped[str | None] = mapped_column(ForeignKey("titles.id", ondelete="SET NULL"), nullable=True)
    progression_json: Mapped[dict] = mapped_column("progression", JSON, default=dict)
    stats: Mapped[dict] = mapped_column(JSON, default=lambda: {
        "health": 100,
        "max_health": 100,
        "stamina": 100,
        "luck": 10,
        "tech": 10,
        "combat": 10,
        "loadout": {
            "weapons": [],
            "gadget": None,
            "healing": None,
            "shield": None,
        },
        "raid_clears": 0,
        "legendary_finds": 0,
        "supporter": False,
    })


class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    type: Mapped[ItemType] = mapped_column(Enum(ItemType), nullable=False)
    rarity: Mapped[Rarity] = mapped_column(Enum(Rarity), nullable=False)
    base_value: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)


class Inventory(Base):
    __tablename__ = "inventories"
    __table_args__ = (UniqueConstraint("user_id", "item_id", "weapon_level", name="uq_inventory_slot"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    qty: Mapped[int] = mapped_column(Integer, default=1)
    durability: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weapon_level: Mapped[int | None] = mapped_column(Integer, nullable=True)

    item: Mapped[Item] = relationship()


class Squad(Base):
    __tablename__ = "squads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class SquadMember(Base):
    __tablename__ = "squad_members"
    __table_args__ = (UniqueConstraint("squad_id", "user_id", name="uq_squad_member"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    squad_id: Mapped[int] = mapped_column(ForeignKey("squads.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="member")


class Deployment(Base):
    __tablename__ = "deployments"
    __table_args__ = (Index("ix_deployments_user_status", "user_id", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    zone: Mapped[str] = mapped_column(String(60))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[DeploymentStatus] = mapped_column(Enum(DeploymentStatus), default=DeploymentStatus.ACTIVE)
    seeded_rng: Mapped[str] = mapped_column(String(120), nullable=False)
    carried_loot: Mapped[dict] = mapped_column(JSON, default=dict)


class Trade(Base):
    __tablename__ = "trades"
    __table_args__ = (Index("ix_trades_status", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_user: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    to_user: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    offered: Mapped[dict] = mapped_column(JSON, default=dict)
    requested: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[TradeStatus] = mapped_column(Enum(TradeStatus), default=TradeStatus.PENDING)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(80), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class GameConfig(Base):
    __tablename__ = "game_config"
    __table_args__ = (UniqueConstraint("guild_id", name="uq_game_config_guild"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True)
    announcement_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    log_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    allowed_zones: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["Residential", "Industrial", "ARC Site"])
    economy_multiplier: Mapped[float] = mapped_column(Numeric(6, 2), default=1.0)
    monetization_enabled: Mapped[bool] = mapped_column(default=True)
    boss_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class Title(Base):
    __tablename__ = "titles"

    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(String(220), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    rarity: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    how_to_earn: Mapped[str] = mapped_column(String(180), default="Earn via gameplay milestones.")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class UserTitle(Base):
    __tablename__ = "user_titles"
    __table_args__ = (
        UniqueConstraint("user_id", "title_id", name="uq_user_title"),
        Index("ix_user_titles_user_id", "user_id"),
        Index("ix_user_titles_title_id", "title_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title_id: Mapped[str] = mapped_column(ForeignKey("titles.id", ondelete="CASCADE"), nullable=False)
    earned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    source_event: Mapped[dict] = mapped_column(JSON, default=dict)


class Quest(Base):
    __tablename__ = "quests"

    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(280), nullable=False)
    chapter: Mapped[int] = mapped_column(Integer, nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    requirements: Mapped[dict] = mapped_column(JSON, default=dict)
    rewards: Mapped[dict] = mapped_column(JSON, default=dict)
    is_sidequest: Mapped[bool] = mapped_column(Boolean, default=False)


class UserQuest(Base):
    __tablename__ = "user_quests"
    __table_args__ = (UniqueConstraint("user_id", "quest_id", name="uq_user_quest"), Index("ix_user_quests_user_status", "user_id", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    quest_id: Mapped[str] = mapped_column(ForeignKey("quests.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[QuestStatus] = mapped_column(Enum(QuestStatus), default=QuestStatus.LOCKED)
    progress: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Expedition(Base):
    __tablename__ = "expeditions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season_number: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    departure_starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    departure_ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[ExpeditionStatus] = mapped_column(Enum(ExpeditionStatus), default=ExpeditionStatus.PREPARING)
    config: Mapped[dict] = mapped_column(JSON, default=dict)


class ExpeditionStage(Base):
    __tablename__ = "expedition_stages"
    __table_args__ = (UniqueConstraint("expedition_id", "stage_number", name="uq_expedition_stage"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    expedition_id: Mapped[int] = mapped_column(ForeignKey("expeditions.id", ondelete="CASCADE"), index=True)
    stage_number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    requirements: Mapped[dict] = mapped_column(JSON, default=dict)
    contributed: Mapped[dict] = mapped_column(JSON, default=dict)
    is_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExpeditionContribution(Base):
    __tablename__ = "expedition_contributions"
    __table_args__ = (UniqueConstraint("expedition_id", "user_id", name="uq_expedition_contribution"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    expedition_id: Mapped[int] = mapped_column(ForeignKey("expeditions.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    contributed_items: Mapped[dict] = mapped_column(JSON, default=dict)
    contributed_credits: Mapped[int] = mapped_column(Integer, default=0)
    score: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class ExpeditionReward(Base):
    __tablename__ = "expedition_rewards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    expedition_id: Mapped[int] = mapped_column(ForeignKey("expeditions.id", ondelete="CASCADE"), index=True)
    reward_type: Mapped[str] = mapped_column(String(40), nullable=False)
    reward_value: Mapped[dict] = mapped_column(JSON, default=dict)


class UserExpeditionState(Base):
    __tablename__ = "user_expedition_state"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    last_departed_expedition_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    permanent_rewards: Mapped[dict] = mapped_column(JSON, default=dict)
    temp_buffs: Mapped[dict] = mapped_column(JSON, default=dict)
    catchup_state: Mapped[dict] = mapped_column(JSON, default=dict)


class ActivityAttempt(Base):
    __tablename__ = "activity_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    activity_type: Mapped[str] = mapped_column(String(30), index=True)
    seed: Mapped[str] = mapped_column(String(120), nullable=False)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
