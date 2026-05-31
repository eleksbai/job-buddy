from functools import lru_cache
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


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

    boss_default_greeting: str = Field(
        default="您好，我对该岗位很感兴趣，希望能和您聊一聊。",
        alias="BOSS_DEFAULT_GREETING",
    )
    boss_profile_dir: str = Field(default="data/chrome_profile", alias="JOB_BUDDY_PROFILE_DIR")
    boss_proxy: str = Field(default="", alias="BOSS_PROXY")

    # AI Matching
    ai_api_base_url: str = Field(default="https://api.openai.com/v1", alias="AI_API_BASE_URL")
    ai_api_key: str = Field(default="", alias="AI_API_KEY")
    ai_model: str = Field(default="gpt-3.5-turbo", alias="AI_MODEL")
    ai_resume_path: str = Field(default="data/resume.md", alias="AI_RESUME_PATH")
    ai_criteria_path: str = Field(default="data/matching_criteria.md", alias="AI_CRITERIA_PATH")
    ai_conversation_style_path: str = Field(default="data/conversation_style.md", alias="AI_CONVERSATION_STYLE_PATH")
    ai_request_delay_seconds: float = Field(default=1.0, alias="AI_REQUEST_DELAY_SECONDS")
    ai_temperature: float = Field(default=0.1, alias="AI_TEMPERATURE")

    @property
    def project_root(self) -> Path:
        return _PROJECT_ROOT


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def configure_logging(settings: Settings) -> None:
    level = getattr(logging, settings.app_log_level.upper(), logging.INFO)
    log_dir = Path(settings.app_log_dir).expanduser()
    if not log_dir.is_absolute():
        log_dir = settings.project_root / log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / settings.app_log_file

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s [%(filename)s:%(lineno)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(level)
    stream_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=settings.app_log_max_bytes,
        backupCount=settings.app_log_backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    root_logger.addHandler(stream_handler)
    root_logger.addHandler(file_handler)


# historyMsg -> zpData.messages[].status
# getGeekFriendList.json -> zpData.result[].lastMessageInfo.status
MESSAGE_STATUS = {
    "送达": 1,
    "已读": 2,
}

MESSAGE_STATUS_REVERSE: dict[int, str] = {v: k for k, v in MESSAGE_STATUS.items()}
