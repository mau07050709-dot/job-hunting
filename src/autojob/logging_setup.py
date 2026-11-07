import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_logging(data_path: Path):
    directory = data_path / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("autojob")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = RotatingFileHandler(directory / "job-hunting.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
    return logger
