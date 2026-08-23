import logging
import os
from decimal import Decimal, InvalidOperation

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("boosty.config")


def _safe_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid int for %s=%r, using default %s", name, raw, default)
        return default


def _safe_decimal(name: str, default: str) -> Decimal:
    raw = os.getenv(name, default)
    try:
        return Decimal(raw)
    except (InvalidOperation, TypeError):
        logger.warning("Invalid decimal for %s=%r, using default %s", name, raw, default)
        return Decimal(default)


def _safe_admin_ids(name: str) -> set[int]:
    raw = os.getenv(name, "")
    ids: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError:
            logger.warning("Invalid admin id skipped: %r", part)
    return ids


class Config:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    ADMIN_IDS: set[int] = _safe_admin_ids("ADMIN_IDS")

    ICHEATBOT_API_KEY: str = os.getenv("ICHEATBOT_API_KEY", "")
    ICHEATBOT_BASE_URL: str = os.getenv("ICHEATBOT_BASE_URL", "https://icheatbot.com/api/v2")

    CRYPTOBOT_TOKEN: str = os.getenv("CRYPTOBOT_TOKEN", "")

    # Where persistent local state lives — the main SQLite DB, the FSM-state SQLite
    # DB, logs, and the single-instance lock file all sit under here. Set DATA_DIR to
    # the host's persistent volume path in production (e.g. /app/data).
    DATA_DIR: str = os.getenv("DATA_DIR", "data")

    # Built with a literal "/" (not os.path.join) — URLs always use forward slashes
    # regardless of OS, unlike FSM_DB_PATH below which is a plain filesystem path.
    DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite+aiosqlite:///{DATA_DIR}/boosty.db")
    # Separate file from the main DB — FSM writes (one per user keystroke/tap) would
    # otherwise compete for the same single-writer lock as order/balance writes.
    FSM_DB_PATH: str = os.getenv("FSM_DB_PATH", os.path.join(DATA_DIR, "fsm.db"))

    DEFAULT_MARKUP_PERCENT: Decimal = _safe_decimal("DEFAULT_MARKUP_PERCENT", "30")
    DEFAULT_REFERRAL_PERCENT: Decimal = _safe_decimal("DEFAULT_REFERRAL_PERCENT", "5")
    CATALOG_SYNC_INTERVAL_SEC: int = _safe_int("CATALOG_SYNC_INTERVAL_SEC", 3600)
    ORDER_POLL_INTERVAL_SEC: int = _safe_int("ORDER_POLL_INTERVAL_SEC", 90)
    INVOICE_POLL_INTERVAL_SEC: int = _safe_int("INVOICE_POLL_INTERVAL_SEC", 15)

    SUPPORT_USERNAME: str = os.getenv("SUPPORT_USERNAME", "")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOGS_PATH: str = os.getenv("LOGS_PATH", os.path.join(DATA_DIR, "logs"))


config = Config()

if not config.BOT_TOKEN:
    logger.warning("BOT_TOKEN is not set")
if not config.ADMIN_IDS:
    logger.warning("ADMIN_IDS is empty — no one will have admin access")
