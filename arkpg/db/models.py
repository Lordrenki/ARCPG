import enum
from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, Enum, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint
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
    stats: Mapped[dict] = mapped_column(JSON, default=lambda: {
        "health": 100,
        "stamina": 100,
        "luck": 10,
        "tech": 10,
        "combat": 10,
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
