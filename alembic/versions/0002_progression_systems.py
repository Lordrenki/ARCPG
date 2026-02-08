"""titles quests expeditions and activities"""

from alembic import op
import sqlalchemy as sa

revision = "0002_progression_systems"
down_revision = "0001_init"
branch_labels = None
depends_on = None


quest_status = sa.Enum("LOCKED", "ACTIVE", "COMPLETED", name="queststatus")
expedition_status = sa.Enum("PREPARING", "ACTIVE", "DEPARTURE", "CLOSED", name="expeditionstatus")


def upgrade() -> None:
    op.add_column("users", sa.Column("equipped_title_id", sa.String(length=60), nullable=True))
    op.add_column("users", sa.Column("progression", sa.JSON(), nullable=False, server_default="{}"))

    op.create_table(
        "titles",
        sa.Column("id", sa.String(length=60), primary_key=True),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("description", sa.String(length=220), nullable=False),
        sa.Column("category", sa.String(length=30), nullable=False),
        sa.Column("rarity", sa.String(length=20), nullable=True),
        sa.Column("is_hidden", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("how_to_earn", sa.String(length=180), nullable=False, server_default="Earn via gameplay milestones."),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_foreign_key("fk_users_equipped_title", "users", "titles", ["equipped_title_id"], ["id"], ondelete="SET NULL")

    op.create_table(
        "user_titles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title_id", sa.String(length=60), sa.ForeignKey("titles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("earned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_event", sa.JSON(), nullable=False),
        sa.UniqueConstraint("user_id", "title_id", name="uq_user_title"),
    )
    op.create_index("ix_user_titles_user_id", "user_titles", ["user_id"])
    op.create_index("ix_user_titles_title_id", "user_titles", ["title_id"])

    op.create_table(
        "quests",
        sa.Column("id", sa.String(length=60), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=280), nullable=False),
        sa.Column("chapter", sa.Integer(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("requirements", sa.JSON(), nullable=False),
        sa.Column("rewards", sa.JSON(), nullable=False),
        sa.Column("is_sidequest", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "user_quests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("quest_id", sa.String(length=60), sa.ForeignKey("quests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", quest_status, nullable=False, server_default="LOCKED"),
        sa.Column("progress", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("user_id", "quest_id", name="uq_user_quest"),
    )
    op.create_index("ix_user_quests_user_status", "user_quests", ["user_id", "status"])

    op.create_table(
        "expeditions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("season_number", sa.Integer(), unique=True, nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("departure_starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("departure_ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", expedition_status, nullable=False, server_default="PREPARING"),
        sa.Column("config", sa.JSON(), nullable=False),
    )

    op.create_table(
        "expedition_stages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("expedition_id", sa.Integer(), sa.ForeignKey("expeditions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stage_number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("requirements", sa.JSON(), nullable=False),
        sa.Column("contributed", sa.JSON(), nullable=False),
        sa.Column("is_complete", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("expedition_id", "stage_number", name="uq_expedition_stage"),
    )
    op.create_index("ix_expedition_stages_expedition_id", "expedition_stages", ["expedition_id"])

    op.create_table(
        "expedition_contributions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("expedition_id", sa.Integer(), sa.ForeignKey("expeditions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("contributed_items", sa.JSON(), nullable=False),
        sa.Column("contributed_credits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("expedition_id", "user_id", name="uq_expedition_contribution"),
    )
    op.create_index("ix_expedition_contributions_expedition_id", "expedition_contributions", ["expedition_id"])
    op.create_index("ix_expedition_contributions_user_id", "expedition_contributions", ["user_id"])

    op.create_table(
        "expedition_rewards",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("expedition_id", sa.Integer(), sa.ForeignKey("expeditions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reward_type", sa.String(length=40), nullable=False),
        sa.Column("reward_value", sa.JSON(), nullable=False),
    )
    op.create_index("ix_expedition_rewards_expedition_id", "expedition_rewards", ["expedition_id"])

    op.create_table(
        "user_expedition_state",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("last_departed_expedition_id", sa.Integer(), nullable=True),
        sa.Column("permanent_rewards", sa.JSON(), nullable=False),
        sa.Column("temp_buffs", sa.JSON(), nullable=False),
        sa.Column("catchup_state", sa.JSON(), nullable=False),
    )

    op.create_table(
        "activity_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("activity_type", sa.String(length=30), nullable=False),
        sa.Column("seed", sa.String(length=120), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_activity_attempts_user_id", "activity_attempts", ["user_id"])
    op.create_index("ix_activity_attempts_activity_type", "activity_attempts", ["activity_type"])


def downgrade() -> None:
    op.drop_table("activity_attempts")
    op.drop_table("user_expedition_state")
    op.drop_table("expedition_rewards")
    op.drop_table("expedition_contributions")
    op.drop_table("expedition_stages")
    op.drop_table("expeditions")
    op.drop_table("user_quests")
    op.drop_table("quests")
    op.drop_table("user_titles")
    op.drop_constraint("fk_users_equipped_title", "users", type_="foreignkey")
    op.drop_table("titles")
    op.drop_column("users", "progression")
    op.drop_column("users", "equipped_title_id")

    quest_status.drop(op.get_bind(), checkfirst=True)
    expedition_status.drop(op.get_bind(), checkfirst=True)
