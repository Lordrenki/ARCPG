"""initial schema"""

from alembic import op
import sqlalchemy as sa

revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("discord_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_claim_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("xp", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("level", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("credits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stats", sa.JSON(), nullable=False),
    )
    op.create_index("ix_users_discord_id", "users", ["discord_id"], unique=True)

    op.create_table(
        "items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("type", sa.Enum("WEAPON", "ARMOR", "GADGET", "COMPONENT", "BLUEPRINT", "RECYCLABLE", name="itemtype"), nullable=False),
        sa.Column("rarity", sa.Enum("COMMON", "UNCOMMON", "RARE", "EPIC", "LEGENDARY", name="rarity"), nullable=False),
        sa.Column("base_value", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metadata", sa.JSON(), nullable=False),
    )

    op.create_table(
        "inventories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("durability", sa.Integer(), nullable=True),
        sa.Column("weapon_level", sa.Integer(), nullable=True),
        sa.UniqueConstraint("user_id", "item_id", "weapon_level", name="uq_inventory_slot"),
    )
    op.create_index("ix_inventories_user_id", "inventories", ["user_id"])
    op.create_index("ix_inventories_item_id", "inventories", ["item_id"])

    op.create_table(
        "squads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(80), nullable=False, unique=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "squad_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("squad_id", sa.Integer(), sa.ForeignKey("squads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.UniqueConstraint("squad_id", "user_id", name="uq_squad_member"),
    )
    op.create_index("ix_squad_members_squad_id", "squad_members", ["squad_id"])
    op.create_index("ix_squad_members_user_id", "squad_members", ["user_id"])

    op.create_table(
        "deployments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("zone", sa.String(60), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Enum("ACTIVE", "READY_TO_EXTRACT", "EXTRACTED", "FAILED", name="deploymentstatus"), nullable=False),
        sa.Column("seeded_rng", sa.String(120), nullable=False),
        sa.Column("carried_loot", sa.JSON(), nullable=False),
    )
    op.create_index("ix_deployments_user_id", "deployments", ["user_id"])
    op.create_index("ix_deployments_user_status", "deployments", ["user_id", "status"])

    op.create_table(
        "trades",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("from_user", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("to_user", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("offered", sa.JSON(), nullable=False),
        sa.Column("requested", sa.JSON(), nullable=False),
        sa.Column("status", sa.Enum("PENDING", "CONFIRMED", "CANCELLED", name="tradestatus"), nullable=False),
    )
    op.create_index("ix_trades_from_user", "trades", ["from_user"])
    op.create_index("ix_trades_to_user", "trades", ["to_user"])
    op.create_index("ix_trades_status", "trades", ["status"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_logs_event_type", "audit_logs", ["event_type"])

    op.create_table(
        "game_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("guild_id", sa.BigInteger(), nullable=False),
        sa.Column("announcement_channel_id", sa.BigInteger(), nullable=True),
        sa.Column("log_channel_id", sa.BigInteger(), nullable=True),
        sa.Column("allowed_zones", sa.JSON(), nullable=False),
        sa.Column("economy_multiplier", sa.Numeric(6, 2), nullable=False),
        sa.Column("monetization_enabled", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("guild_id", name="uq_game_config_guild"),
    )
    op.create_index("ix_game_config_guild_id", "game_config", ["guild_id"])


def downgrade() -> None:
    op.drop_table("game_config")
    op.drop_table("audit_logs")
    op.drop_table("trades")
    op.drop_table("deployments")
    op.drop_table("squad_members")
    op.drop_table("squads")
    op.drop_table("inventories")
    op.drop_table("items")
    op.drop_table("users")
