from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    # Some hosts start the bot from a parent directory (e.g. `/home/container`)
    # while the project lives in a subfolder (e.g. `/home/container/ARCPG-main`).
    # Read `.env` from both locations so local and hosted starts work reliably.
    _project_root = Path(__file__).resolve().parents[2]
    model_config = SettingsConfigDict(
        env_file=(str(_project_root / ".env"), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    discord_token: str = Field(validation_alias=AliasChoices("DISCORD_TOKEN", "BOT_TOKEN", "TOKEN"))
    database_url: str | None = Field(default=None, alias="DATABASE_URL")
    database_host: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DB_HOST", "MYSQL_HOST", "MYSQLHOST", "PGHOST", "POSTGRES_HOST"),
    )
    database_port: int | None = Field(
        default=None,
        validation_alias=AliasChoices("DB_PORT", "MYSQL_PORT", "MYSQLPORT", "PGPORT", "POSTGRES_PORT"),
    )
    database_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "DB_NAME",
            "MYSQL_DATABASE",
            "MYSQLDATABASE",
            "PGDATABASE",
            "POSTGRES_DB",
            "POSTGRES_DATABASE",
        ),
    )
    database_user: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DB_USER", "MYSQL_USER", "MYSQLUSER", "PGUSER", "POSTGRES_USER"),
    )
    database_password: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "DB_PASSWORD",
            "MYSQL_PASSWORD",
            "MYSQLPASSWORD",
            "PGPASSWORD",
            "POSTGRES_PASSWORD",
        ),
    )
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    bot_log_level: str = Field(default="INFO", alias="BOT_LOG_LEVEL")
    sync_commands_guild_id: int | None = Field(default=None, alias="SYNC_COMMANDS_GUILD_ID")

    idle_claim_cap_hours: int = Field(default=24, alias="IDLE_CLAIM_CAP_HOURS")
    idle_xp_per_minute: int = Field(default=2, alias="IDLE_XP_PER_MINUTE")
    idle_credits_per_minute: int = Field(default=1, alias="IDLE_CREDITS_PER_MINUTE")
    deployment_auto_extract_minutes: int = Field(default=60, alias="DEPLOYMENT_AUTO_EXTRACT_MINUTES")
    supporter_features_enabled: bool = Field(default=True, alias="SUPPORTER_FEATURES_ENABLED")
    economy_multiplier: float = Field(default=1.0, alias="ECONOMY_MULTIPLIER")

    @field_validator("database_url", "database_host", "database_name", "database_user", "database_password", mode="before")
    @classmethod
    def normalize_db_text_values(cls, value: str | None) -> str | None:
        if not isinstance(value, str):
            return value
        cleaned = value.strip()
        while cleaned and cleaned[0] in {"'", '"'}:
            cleaned = cleaned[1:].strip()
        while cleaned and cleaned[-1] in {"'", '"'}:
            cleaned = cleaned[:-1].strip()
        return cleaned

    @model_validator(mode="after")
    def validate_database_settings(self) -> "Settings":
        has_url = bool(self.database_url)
        has_parts = all([self.database_host, self.database_name, self.database_user, self.database_password])
        if not has_url and not has_parts:
            raise ValueError(
                "DATABASE_URL is required unless DB_HOST, DB_NAME, DB_USER, and DB_PASSWORD are all set."
            )
        return self

    @property
    def resolved_database_url(self) -> str:
        if self.database_host and self.database_name and self.database_user and self.database_password:
            drivername = "mysql+aiomysql"
            if self.database_url and self.database_url.startswith("postgresql"):
                drivername = "postgresql+asyncpg"
            return URL.create(
                drivername=drivername,
                username=self.database_user,
                password=self.database_password,
                host=self.database_host,
                port=self.database_port,
                database=self.database_name,
            ).render_as_string(hide_password=False)
        return self.database_url or ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[arg-type]
