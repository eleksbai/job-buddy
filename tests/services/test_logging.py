import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from job_buddy.config import Settings, configure_logging


def test_configure_logging_creates_stream_and_file_handlers(tmp_path: Path):
    settings = Settings(
        APP_LOG_LEVEL="DEBUG",
        APP_LOG_DIR=str(tmp_path / "logs"),
        APP_LOG_FILE="app.log",
        APP_LOG_MAX_BYTES="2048",
        APP_LOG_BACKUP_COUNT="3",
    )

    configure_logging(settings)

    root_logger = logging.getLogger()
    assert len(root_logger.handlers) == 2
    assert any(isinstance(handler, logging.StreamHandler) for handler in root_logger.handlers)

    file_handlers = [handler for handler in root_logger.handlers if isinstance(handler, RotatingFileHandler)]
    assert len(file_handlers) == 1
    file_handler = file_handlers[0]
    assert Path(file_handler.baseFilename) == (tmp_path / "logs" / "app.log")
    assert file_handler.maxBytes == 2048
    assert file_handler.backupCount == 3


def test_configure_logging_is_idempotent(tmp_path: Path):
    settings = Settings(APP_LOG_DIR=str(tmp_path / "logs"))

    configure_logging(settings)
    configure_logging(settings)

    root_logger = logging.getLogger()
    assert len(root_logger.handlers) == 2


def test_configure_logging_writes_timestamped_log_file(tmp_path: Path):
    settings = Settings(APP_LOG_DIR=str(tmp_path / "logs"), APP_LOG_FILE="runtime.log")

    configure_logging(settings)
    logger = logging.getLogger("job_buddy.tests.logging")
    logger.info("hello log file")

    log_file = tmp_path / "logs" / "runtime.log"
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "hello log file" in content
    assert "INFO" in content
    assert "test_logging.py" in content
