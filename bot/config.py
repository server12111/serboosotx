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

    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", "postgresql+asyncpg://boosty:boosty@localhost:5432/boosty"
    )
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    DEFAULT_MARKUP_PERCENT: Decimal = _safe_decimal("DEFAULT_MARKUP_PERCENT", "30")
    DEFAULT_REFERRAL_PERCENT: Decimal = _safe_decimal("DEFAULT_REFERRAL_PERCENT", "5")
    CATALOG_SYNC_INTERVAL_SEC: int = _safe_int("CATALOG_SYNC_INTERVAL_SEC", 3600)
    ORDER_POLL_INTERVAL_SEC: int = _safe_int("ORDER_POLL_INTERVAL_SEC", 90)
    INVOICE_POLL_INTERVAL_SEC: int = _safe_int("INVOICE_POLL_INTERVAL_SEC", 15)

    SUPPORT_USERNAME: str = os.getenv("SUPPORT_USERNAME", "")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOGS_PATH: str = os.getenv("LOGS_PATH", "data/logs")


config = Config()

if not config.BOT_TOKEN:
    logger.warning("BOT_TOKEN is not set")
if not config.ADMIN_IDS:
    logger.warning("ADMIN_IDS is empty — no one will have admin access")
