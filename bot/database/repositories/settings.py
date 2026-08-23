from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Setting


class SettingsRepository:
    @staticmethod
    async def get(session: AsyncSession, key: str) -> str | None:
        result = await session.execute(select(Setting.value).where(Setting.key == key))
        row = result.first()
        return row[0] if row else None

    @staticmethod
    async def get_decimal(session: AsyncSession, key: str, default: Decimal) -> Decimal:
        raw = await SettingsRepository.get(session, key)
        if raw is None:
            return default
        try:
            return Decimal(raw)
        except InvalidOperation:
            return default

    @staticmethod
    async def get_int(session: AsyncSession, key: str, default: int) -> int:
        raw = await SettingsRepository.get(session, key)
        if raw is None:
            return default
        try:
            return int(raw)
        except ValueError:
            return default

    @staticmethod
    async def set(session: AsyncSession, key: str, value: str, updated_by: int | None = None) -> None:
        stmt = (
            pg_insert(Setting)
            .values(key=key, value=value, updated_by=updated_by)
            .on_conflict_do_update(
                index_elements=[Setting.key], set_={"value": value, "updated_by": updated_by}
            )
        )
        await session.execute(stmt)
        await session.commit()

    @staticmethod
    async def set_if_absent(session: AsyncSession, key: str, value: str) -> None:
        stmt = pg_insert(Setting).values(key=key, value=value).on_conflict_do_nothing(
            index_elements=[Setting.key]
        )
        await session.execute(stmt)
        await session.commit()

    @staticmethod
    async def get_all(session: AsyncSession) -> dict[str, str]:
        result = await session.execute(select(Setting.key, Setting.value))
        return dict(result.all())
