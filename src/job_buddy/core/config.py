from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = Field(default="Job Buddy", alias="APP_NAME")
    app_env: str = Field(default="local", alias="APP_ENV")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")
    app_log_level: str = Field(default="INFO", alias="APP_LOG_LEVEL")

    mongodb_uri: str = Field(default="mongodb://localhost:27017", alias="MONGODB_URI")
    mongodb_db: str = Field(default="job_buddy", alias="MONGODB_DB")

    boss_client_class: str | None = Field(default=None, alias="BOSS_CLIENT_CLASS")
    boss_cli_bin: str = Field(default="boss", alias="BOSS_CLI_BIN")
    boss_data_dir: str | None = Field(default=None, alias="BOSS_DATA_DIR")
    boss_cdp_url: str | None = Field(default=None, alias="BOSS_CDP_URL")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
