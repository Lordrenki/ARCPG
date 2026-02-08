from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    database_url: str = Field(alias="DATABASE_URL")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    bot_log_level: str = Field(default="INFO", alias="BOT_LOG_LEVEL")
    sync_commands_guild_id: int | None = Field(default=None, alias="SYNC_COMMANDS_GUILD_ID")

    idle_claim_cap_hours: int = Field(default=24, alias="IDLE_CLAIM_CAP_HOURS")
    idle_xp_per_minute: int = Field(default=2, alias="IDLE_XP_PER_MINUTE")
    idle_credits_per_minute: int = Field(default=1, alias="IDLE_CREDITS_PER_MINUTE")
    deployment_auto_extract_minutes: int = Field(default=60, alias="DEPLOYMENT_AUTO_EXTRACT_MINUTES")
    supporter_features_enabled: bool = Field(default=True, alias="SUPPORTER_FEATURES_ENABLED")
    economy_multiplier: float = Field(default=1.0, alias="ECONOMY_MULTIPLIER")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[arg-type]
