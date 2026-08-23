import datetime
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import CryptoBotInvoice


class InvoiceRepository:
    @staticmethod
    async def create(
        session: AsyncSession,
        user_id: int,
        cryptobot_invoice_id: int,
        asset: str,
        amount_crypto: Decimal,
        amount_rub_locked: Decimal,
        pay_url: str,
        expires_at: datetime.datetime,
    ) -> CryptoBotInvoice:
        invoice = CryptoBotInvoice(
            user_id=user_id,
            cryptobot_invoice_id=cryptobot_invoice_id,
            asset=asset,
            amount_crypto=amount_crypto,
            amount_rub_locked=amount_rub_locked,
            pay_url=pay_url,
            expires_at=expires_at,
            status="active",
        )
        session.add(invoice)
        await session.commit()
        return invoice

    @staticmethod
    async def get_by_id(session: AsyncSession, invoice_id: int) -> CryptoBotInvoice | None:
        return await session.get(CryptoBotInvoice, invoice_id)

    @staticmethod
    async def get_by_cryptobot_id(
        session: AsyncSession, cryptobot_invoice_id: int
    ) -> CryptoBotInvoice | None:
        result = await session.execute(
            select(CryptoBotInvoice).where(
                CryptoBotInvoice.cryptobot_invoice_id == cryptobot_invoice_id
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def mark_paid_if_active(session: AsyncSession, invoice_id: int) -> bool:
        """Atomic conditional transition active->paid. Returns True iff this call was the
        one that made the transition — guards against a race between the periodic
        reconciler and a user-triggered manual check crediting the same invoice twice.
        Does NOT commit — caller wraps this with the balance credit in one transaction."""
        result = await session.execute(
            update(CryptoBotInvoice)
            .where(CryptoBotInvoice.id == invoice_id, CryptoBotInvoice.status == "active")
            .values(status="paid", paid_at=datetime.datetime.now(datetime.timezone.utc))
            .returning(CryptoBotInvoice.id)
        )
        return result.first() is not None

    @staticmethod
    async def mark_expired(session: AsyncSession, invoice_id: int) -> None:
        await session.execute(
            update(CryptoBotInvoice).where(CryptoBotInvoice.id == invoice_id).values(status="expired")
        )

    @staticmethod
    async def list_active(session: AsyncSession) -> list[CryptoBotInvoice]:
        result = await session.execute(
            select(CryptoBotInvoice).where(CryptoBotInvoice.status == "active")
        )
        return list(result.scalars().all())
