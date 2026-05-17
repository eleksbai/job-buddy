from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录：.env 文件所在目录，不受启动位置影响
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=f"{_PROJECT_ROOT}/.env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = Field(default="Job Buddy", alias="APP_NAME")
    app_env: str = Field(default="local", alias="APP_ENV")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")
    app_log_level: str = Field(default="INFO", alias="APP_LOG_LEVEL")
    app_log_dir: str = Field(default="logs", alias="APP_LOG_DIR")
    app_log_file: str = Field(default="job-buddy.log", alias="APP_LOG_FILE")
    app_log_max_bytes: int = Field(default=10 * 1024 * 1024, alias="APP_LOG_MAX_BYTES")
    app_log_backup_count: int = Field(default=5, alias="APP_LOG_BACKUP_COUNT")

    mongodb_uri: str = Field(default="mongodb://localhost:27017", alias="MONGODB_URI")
    mongodb_db: str = Field(default="job_buddy", alias="MONGODB_DB")

    collector_config_path: str = Field(default="config/collector_engines.json", alias="COLLECTOR_CONFIG_PATH")

    @property
    def project_root(self) -> Path:
        return _PROJECT_ROOT


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
