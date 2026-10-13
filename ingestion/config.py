from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class IngestionSettings(BaseSettings):
    slack_bot_token: str = Field(min_length=1)
    slack_app_token: str = Field(min_length=1)
    slack_channel_ids: list[str] = Field(default_factory=list)

    slack_page_size: int = Field(default=200, ge=1, le=200)

    slack_max_retries: int = Field(default=5, ge=0, le=10)

    slack_initial_backoff_seconds: float = Field(
        default=1.0,
        gt=0,
    )

    checkpoint_file: str = "storage/checkpoints.json"

    output_file: str = "output/threads.json"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> IngestionSettings:
    return IngestionSettings()