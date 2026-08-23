import asyncio
import datetime
import logging
from decimal import Decimal, InvalidOperation

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..database.repositories.services import ServiceRepository, ServiceUpsert
from ..database.repositories.settings import SettingsRepository
from . import platform_map, service_type_map
from .icheatbot import IcheatbotClient, IcheatbotError

logger = logging.getLogger("boosty.catalog_sync")


def _to_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _row_to_upsert(raw: dict) -> ServiceUpsert | None:
    try:
        external_id = str(raw["service"])
        name = str(raw["name"])
        rate = Decimal(str(raw["rate"]))
        min_q = int(raw["min"])
        max_q = int(raw["max"])
    except (KeyError, InvalidOperation, ValueError, TypeError):
        logger.warning("skipping malformed service row: %r", raw)
        return None

    category_raw = raw.get("category")
    type_raw = raw.get("type")
    return ServiceUpsert(
        external_service_id=external_id,
        name=name,
        category_raw=category_raw,
        type_raw=type_raw,
        platform=platform_map.classify(category_raw, name),
        service_type=service_type_map.classify(category_raw, type_raw, name),
        rate_rub=rate,
        min_quantity=min_q,
        max_quantity=max_q,
        refill=_to_bool(raw.get("refill", False)),
        cancel=_to_bool(raw.get("cancel", False)),
        dripfeed=bool(raw.get("dripfeed") or raw.get("runs") or raw.get("interval")),
    )


async def run_once(
    session_factory: async_sessionmaker[AsyncSession], api_client: IcheatbotClient
) -> dict[str, int]:
    run_started_at = datetime.datetime.now(datetime.timezone.utc)
    raw_services = await api_client.services()

    rows: list[ServiceUpsert] = []
    for raw in raw_services:
        parsed = _row_to_upsert(raw)
        if parsed is not None:
            rows.append(parsed)

    async with session_factory() as session:
        await ServiceRepository.upsert_many(session, rows)
        deactivated = await ServiceRepository.deactivate_not_seen_since(session, run_started_at)

        stats = {"total_seen": len(rows), "deactivated": deactivated}
        await SettingsRepository.set(session, "catalog_last_sync_at", run_started_at.isoformat())
        await SettingsRepository.set(session, "catalog_last_sync_stats", str(stats))

    logger.info("catalog sync complete: %s", stats)
    return stats


async def loop(
    session_factory: async_sessionmaker[AsyncSession],
    api_client: IcheatbotClient,
    interval_sec: int,
) -> None:
    while True:
        try:
            await run_once(session_factory, api_client)
        except IcheatbotError as e:
            logger.error("catalog sync failed: %s", e)
        except Exception:
            logger.exception("catalog sync crashed unexpectedly")
        await asyncio.sleep(interval_sec)
