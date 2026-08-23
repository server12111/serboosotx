import logging
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..database.models import Service
from ..database.repositories.orders import OrderRepository
from ..database.repositories.transactions import LedgerRepository
from ..database.repositories.users import UserRepository
from .icheatbot import IcheatbotClient, IcheatbotError
from .pricing import compute_price, compute_upstream_cost

logger = logging.getLogger("boosty.order_flow")


@dataclass
class PlaceOrderResult:
    ok: bool
    order_id: int | None = None
    external_order_id: str | None = None
    reason: str | None = None  # "insufficient_funds" | "upstream_error"
    charge_rub: Decimal | None = None


async def place_order(
    session_factory: async_sessionmaker[AsyncSession],
    api_client: IcheatbotClient,
    user_id: int,
    service: Service,
    link: str,
    quantity: int,
    markup_percent: Decimal,
    runs: int | None = None,
    interval_minutes: int | None = None,
) -> PlaceOrderResult:
    """3-step saga: reserve funds + create a pending order in one DB transaction, call
    the slow upstream API outside any transaction, then finalize or refund in a second
    transaction. This keeps no row lock held across the network call."""
    charge_rub = compute_price(service.rate_rub, quantity, markup_percent)
    upstream_cost_rub = compute_upstream_cost(service.rate_rub, quantity)

    # Step 1: reserve
    async with session_factory() as session:
        new_balance = await UserRepository.try_debit(session, user_id, charge_rub)
        if new_balance is None:
            await session.rollback()
            return PlaceOrderResult(ok=False, reason="insufficient_funds", charge_rub=charge_rub)

        order = await OrderRepository.create_pending(
            session,
            user_id=user_id,
            service_id=service.id,
            link=link,
            quantity=quantity,
            charge_rub=charge_rub,
            upstream_cost_rub=upstream_cost_rub,
            runs=runs,
            interval_minutes=interval_minutes,
        )
        await LedgerRepository.record(
            session,
            user_id=user_id,
            type_="order_debit",
            amount=-charge_rub,
            balance_after=new_balance,
            related_order_id=order.id,
            comment=f"Заказ услуги {service.external_service_id}",
        )
        await session.commit()
        order_id = order.id

    # Step 2: call upstream outside any transaction
    try:
        external_order_id = await api_client.add(
            service_id=service.external_service_id,
            link=link,
            quantity=quantity,
            runs=runs,
            interval=interval_minutes,
        )
    except IcheatbotError as e:
        logger.error("upstream add() failed for order %s: %s", order_id, e)
        # Step 3b: compensate
        async with session_factory() as session:
            new_balance = await UserRepository.credit(session, user_id, charge_rub)
            await OrderRepository.mark_failed(session, order_id, str(e))
            await LedgerRepository.record(
                session,
                user_id=user_id,
                type_="order_refund",
                amount=charge_rub,
                balance_after=new_balance,
                related_order_id=order_id,
                comment="Возврат: ошибка при размещении заказа у поставщика",
            )
            await session.commit()
        return PlaceOrderResult(ok=False, order_id=order_id, reason="upstream_error", charge_rub=charge_rub)

    # Step 3a: finalize
    async with session_factory() as session:
        await OrderRepository.mark_placed(session, order_id, external_order_id)
        await session.commit()

    return PlaceOrderResult(
        ok=True, order_id=order_id, external_order_id=external_order_id, charge_rub=charge_rub
    )
