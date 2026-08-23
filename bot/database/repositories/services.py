import datetime
from decimal import Decimal
from typing import TypedDict

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Service


class ServiceUpsert(TypedDict):
    external_service_id: str
    name: str
    category_raw: str | None
    type_raw: str | None
    platform: str
    service_type: str
    rate_rub: Decimal
    min_quantity: int
    max_quantity: int
    refill: bool
    cancel: bool
    dripfeed: bool


# Postgres/asyncpg cap bind parameters at 32767 per statement. ServiceUpsert has 12
# fields, so a single INSERT ... VALUES (...), (...) covering the whole catalog
# (thousands of rows) blows past that — chunk into batches well under the limit.
_UPSERT_BATCH_SIZE = 1000


class ServiceRepository:
    @staticmethod
    async def upsert_many(session: AsyncSession, rows: list[ServiceUpsert]) -> None:
        for i in range(0, len(rows), _UPSERT_BATCH_SIZE):
            batch = rows[i : i + _UPSERT_BATCH_SIZE]
            stmt = pg_insert(Service).values(batch)
            stmt = stmt.on_conflict_do_update(
                index_elements=[Service.external_service_id],
                set_={
                    "name": stmt.excluded.name,
                    "category_raw": stmt.excluded.category_raw,
                    "type_raw": stmt.excluded.type_raw,
                    "platform": stmt.excluded.platform,
                    "service_type": stmt.excluded.service_type,
                    "rate_rub": stmt.excluded.rate_rub,
                    "min_quantity": stmt.excluded.min_quantity,
                    "max_quantity": stmt.excluded.max_quantity,
                    "refill": stmt.excluded.refill,
                    "cancel": stmt.excluded.cancel,
                    "dripfeed": stmt.excluded.dripfeed,
                    "is_active": True,
                    "last_seen_at": func.now(),
                    "updated_at": func.now(),
                },
            )
            await session.execute(stmt)
        await session.commit()

    @staticmethod
    async def deactivate_not_seen_since(session: AsyncSession, cutoff: datetime.datetime) -> int:
        result = await session.execute(
            update(Service)
            .where(Service.last_seen_at < cutoff, Service.is_active.is_(True))
            .values(is_active=False)
            .returning(Service.id)
        )
        deactivated = result.scalars().all()
        await session.commit()
        return len(deactivated)

    @staticmethod
    async def get_by_id(session: AsyncSession, service_id: int) -> Service | None:
        return await session.get(Service, service_id)

    @staticmethod
    async def get_by_external_id(session: AsyncSession, external_id: str) -> Service | None:
        result = await session.execute(
            select(Service).where(Service.external_service_id == external_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def list_platforms(session: AsyncSession) -> list[tuple[str, int]]:
        result = await session.execute(
            select(Service.platform, func.count())
            .where(Service.is_active.is_(True))
            .group_by(Service.platform)
        )
        return list(result.all())

    @staticmethod
    async def list_types_for_platform(session: AsyncSession, platform: str) -> list[tuple[str, int]]:
        result = await session.execute(
            select(Service.service_type, func.count())
            .where(Service.platform == platform, Service.is_active.is_(True))
            .group_by(Service.service_type)
            .order_by(func.count().desc())
        )
        return list(result.all())

    @staticmethod
    async def list_by_platform_and_type(
        session: AsyncSession, platform: str, service_type: str, offset: int, limit: int
    ) -> list[Service]:
        result = await session.execute(
            select(Service)
            .where(
                Service.platform == platform,
                Service.service_type == service_type,
                Service.is_active.is_(True),
            )
            .order_by(Service.name)
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def count_by_platform_and_type(session: AsyncSession, platform: str, service_type: str) -> int:
        result = await session.execute(
            select(func.count())
            .select_from(Service)
            .where(
                Service.platform == platform,
                Service.service_type == service_type,
                Service.is_active.is_(True),
            )
        )
        return result.scalar_one()

    @staticmethod
    async def list_categories_for_platform_type(
        session: AsyncSession, platform: str, service_type: str
    ) -> list[tuple[str, int]]:
        """Distinct upstream category_raw values within a platform+type — this is real
        provider taxonomy (e.g. "по странам" / "премиум" / "боты" within followers),
        not another guessed classifier, so it's used as-is rather than re-bucketed."""
        result = await session.execute(
            select(Service.category_raw, func.count())
            .where(
                Service.platform == platform,
                Service.service_type == service_type,
                Service.is_active.is_(True),
                Service.category_raw.is_not(None),
            )
            .group_by(Service.category_raw)
            .order_by(func.count().desc())
        )
        return list(result.all())

    @staticmethod
    async def list_by_platform_type_category(
        session: AsyncSession, platform: str, service_type: str, category_raw: str, offset: int, limit: int
    ) -> list[Service]:
        result = await session.execute(
            select(Service)
            .where(
                Service.platform == platform,
                Service.service_type == service_type,
                Service.category_raw == category_raw,
                Service.is_active.is_(True),
            )
            .order_by(Service.name)
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def count_by_platform_type_category(
        session: AsyncSession, platform: str, service_type: str, category_raw: str
    ) -> int:
        result = await session.execute(
            select(func.count())
            .select_from(Service)
            .where(
                Service.platform == platform,
                Service.service_type == service_type,
                Service.category_raw == category_raw,
                Service.is_active.is_(True),
            )
        )
        return result.scalar_one()

    @staticmethod
    async def search_by_name(session: AsyncSession, query: str, offset: int, limit: int) -> list[Service]:
        like = f"%{query}%"
        result = await session.execute(
            select(Service)
            .where(
                Service.is_active.is_(True),
                or_(Service.name.ilike(like), Service.category_raw.ilike(like)),
            )
            .order_by(Service.name)
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def count_search(session: AsyncSession, query: str) -> int:
        like = f"%{query}%"
        result = await session.execute(
            select(func.count())
            .select_from(Service)
            .where(
                Service.is_active.is_(True),
                or_(Service.name.ilike(like), Service.category_raw.ilike(like)),
            )
        )
        return result.scalar_one()
