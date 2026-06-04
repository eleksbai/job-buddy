from functools import lru_cache
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.sources import PydanticBaseSettingsSource, YamlConfigSettingsSource

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class AppConfig(BaseModel):
    name: str = "Job Buddy"
    env: str = "local"
    host: str = "0.0.0.0"
    port: int = 8000


class LogConfig(BaseModel):
    level: str = "INFO"
    dir: str = "logs"
    file: str = "job-buddy.log"
    max_bytes: int = 10 * 1024 * 1024
    backup_count: int = 5


class MongoConfig(BaseModel):
    uri: str = "mongodb://localhost:27017"
    db: str = "job_buddy"


class BossConfig(BaseModel):
    default_greeting: str = "您好，我对该岗位很感兴趣，希望能和您聊一聊。"
    profile_dir: str = "data/chrome_profile"
    proxy: str = ""


class AIProviderConfig(BaseModel):
    name: str
    url: str
    model: str
    api_key: str = ""


class FeishuConfig(BaseModel):
    enabled: bool = True


class AIConfig(BaseModel):
    providers: list[AIProviderConfig] = Field(
        default_factory=lambda: [
            AIProviderConfig(name="openai", url="https://api.openai.com/v1", model="gpt-3.5-turbo")
        ]
    )
    default_provider: str | None = None
    resume_path: str = "data/resume.md"
    criteria_path: str = "data/matching_criteria.md"
    conversation_style_path: str = "data/conversation_style.md"
    request_delay_seconds: float = 1.0
    temperature: float = 0.1

    @property
    def provider(self) -> AIProviderConfig:
        """Return the provider matching default_provider, or the first one."""
        if self.default_provider:
            for p in self.providers:
                if p.name == self.default_provider:
                    return p
        if self.providers:
            return self.providers[0]
        return AIProviderConfig(name="openai", url="https://api.openai.com/v1", model="gpt-3.5-turbo")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        yaml_file=f"{_PROJECT_ROOT}/config.yaml",
        yaml_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        env_nested_delimiter="__",
        env_prefix="JOB_BUDDY_",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            YamlConfigSettingsSource(settings_cls),
        )

    app: AppConfig = Field(default_factory=AppConfig)
    log: LogConfig = Field(default_factory=LogConfig)
    mongo: MongoConfig = Field(default_factory=MongoConfig)
    boss: BossConfig = Field(default_factory=BossConfig)
    feishu: FeishuConfig = Field(default_factory=FeishuConfig)
    ai: AIConfig = Field(default_factory=AIConfig)

    @property
    def project_root(self) -> Path:
        return _PROJECT_ROOT


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def configure_logging(settings: Settings) -> None:
    level = getattr(logging, settings.log.level.upper(), logging.INFO)
    log_dir = Path(settings.log.dir).expanduser()
    if not log_dir.is_absolute():
        log_dir = settings.project_root / log_dir
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / settings.log.file

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
        maxBytes=settings.log.max_bytes,
        backupCount=settings.log.backup_count,
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
