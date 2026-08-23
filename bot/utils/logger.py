import logging
import os
from logging.handlers import RotatingFileHandler


def setup_logging(logs_path: str, level: str = "INFO") -> None:
    os.makedirs(logs_path, exist_ok=True)
    log_file = os.path.join(logs_path, "bot.log")

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    file_handler = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level.upper())
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    logging.getLogger("aiogram").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)
