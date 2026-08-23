import asyncio
import logging
import os
import sys
import time

from bot.config import config
from bot.utils.logger import setup_logging

LOCK_FILE = os.path.join(config.DATA_DIR, "boosty.lock")

logger = logging.getLogger("boosty.run")


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
