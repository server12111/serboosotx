import asyncio
import logging
import os
import sys
import time

from bot.config import config
from bot.utils.logger import setup_logging

LOCK_FILE = os.path.join(config.DATA_DIR, "boosty.lock")
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

logger = logging.getLogger("boosty.run")


def _run_migrations() -> None:
    """Applies pending Alembic migrations before the bot starts — makes run.py
    self-sufficient regardless of how it's launched (previously this only happened
    via docker-compose's `alembic upgrade head && python run.py` command wrapper, so
    a bare `python run.py` on a fresh DB crashed with "no such table")."""
    from alembic import command
    from alembic.config import Config

    alembic_cfg = Config(os.path.join(_PROJECT_ROOT, "alembic.ini"))
    command.upgrade(alembic_cfg, "head")


def _acquire_single_instance_lock():
    os.makedirs(os.path.dirname(os.path.abspath(LOCK_FILE)), exist_ok=True)
    if sys.platform == "win32":
        import msvcrt

        fh = open(LOCK_FILE, "w")
        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            print("Бот уже запущен (lock-файл занят).")
            sys.exit(1)
        return fh
    else:
        import fcntl

        fh = open(LOCK_FILE, "w")
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("Бот уже запущен (lock-файл занят).")
            sys.exit(1)
        return fh


def main() -> None:
    setup_logging(config.LOGS_PATH, config.LOG_LEVEL)
    _lock_handle = _acquire_single_instance_lock()  # noqa: F841 — keep the handle alive
    _run_migrations()

    from bot.main import main as bot_main

    backoff = 5
    while True:
        try:
            asyncio.run(bot_main())
            break  # a clean exit (e.g. Ctrl+C) should not be restarted
        except KeyboardInterrupt:
            break
        except Exception:
            logger.exception("Bot crashed, restarting in %s seconds", backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 300)


if __name__ == "__main__":
    main()
