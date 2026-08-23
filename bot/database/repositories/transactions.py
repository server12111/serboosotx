from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import BalanceTransaction


class LedgerRepository:
    @staticmethod
    async def record(
        session: AsyncSession,
        user_id: int,
        type_: str,
        amount: Decimal,
        balance_after: Decimal,
        related_order_id: int | None = None,
        related_invoice_id: int | None = None,
        comment: str | None = None,
    ) -> BalanceTransaction:
        """Does NOT commit — caller wraps this with the balance mutation in one transaction."""
        tx = BalanceTransaction(
            user_id=user_id,
            type=type_,
            amount=amount,
            balance_after=balance_after,
            related_order_id=related_order_id,
            related_invoice_id=related_invoice_id,
            comment=comment,
        )
        session.add(tx)
        await session.flush()
        return tx

    @staticmethod
    async def list_by_user(
        session: AsyncSession, user_id: int, offset: int, limit: int
    ) -> list[BalanceTransaction]:
        result = await session.execute(
            select(BalanceTransaction)
            .where(BalanceTransaction.user_id == user_id)
            .order_by(BalanceTransaction.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def sum_by_type(session: AsyncSession, user_id: int, type_: str) -> Decimal:
        result = await session.execute(
            select(func.coalesce(func.sum(BalanceTransaction.amount), 0)).where(
                BalanceTransaction.user_id == user_id, BalanceTransaction.type == type_
            )
        )
        return result.scalar_one()
