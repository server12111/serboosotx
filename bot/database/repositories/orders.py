import datetime
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Order

OPEN_STATUSES_EXCLUDED = ("completed", "canceled", "failed", "refunded")


class OrderRepository:
    @staticmethod
    async def create_pending(
        session: AsyncSession,
        user_id: int,
        service_id: int,
        link: str,
        quantity: int,
        charge_rub: Decimal,
        upstream_cost_rub: Decimal,
        runs: int | None = None,
        interval_minutes: int | None = None,
    ) -> Order:
        order = Order(
            user_id=user_id,
            service_id=service_id,
            link=link,
            quantity=quantity,
            charge_rub=charge_rub,
            upstream_cost_rub=upstream_cost_rub,
            runs=runs,
            interval_minutes=interval_minutes,
            status="pending",
        )
        session.add(order)
        await session.flush()
        return order

    @staticmethod
    async def mark_placed(session: AsyncSession, order_id: int, external_order_id: str) -> None:
        """Does NOT commit — caller controls the transaction."""
        await session.execute(
            update(Order)
            .where(Order.id == order_id)
            .values(status="placed", external_order_id=external_order_id)
        )

    @staticmethod
    async def mark_failed(session: AsyncSession, order_id: int, error: str) -> None:
        """Does NOT commit — caller controls the transaction. This matters: callers
        pair this with a balance credit + ledger record that must land in the same
        commit, or a crash between two separate commits leaves the balance already
        corrected but with no ledger row explaining why."""
        await session.execute(
            update(Order).where(Order.id == order_id).values(status="failed", upstream_error=error)
        )

    @staticmethod
    async def update_status(
        session: AsyncSession,
        order_id: int,
        status: str,
        start_count: int | None,
        remains: int | None,
    ) -> None:
        await session.execute(
            update(Order)
            .where(Order.id == order_id)
            .values(
                status=status,
                start_count=start_count,
                remains=remains,
                last_checked_at=datetime.datetime.now(datetime.timezone.utc),
            )
        )

    @staticmethod
    async def list_open_for_polling(session: AsyncSession, limit: int) -> list[Order]:
        result = await session.execute(
            select(Order)
            .where(Order.status.notin_(OPEN_STATUSES_EXCLUDED))
            .order_by(Order.last_checked_at.asc().nulls_first())
            .limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def list_by_user(session: AsyncSession, user_id: int, offset: int, limit: int) -> list[Order]:
        result = await session.execute(
            select(Order)
            .where(Order.user_id == user_id)
            .order_by(Order.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def count_by_user(session: AsyncSession, user_id: int) -> int:
        result = await session.execute(
            select(func.count()).select_from(Order).where(Order.user_id == user_id)
        )
        return result.scalar_one()

    @staticmethod
    async def get_by_id(session: AsyncSession, order_id: int) -> Order | None:
        return await session.get(Order, order_id)

    @staticmethod
    async def list_stuck_pending(session: AsyncSession, older_than: datetime.datetime) -> list[Order]:
        result = await session.execute(
            select(Order).where(Order.status == "pending", Order.created_at < older_than)
        )
        return list(result.scalars().all())
