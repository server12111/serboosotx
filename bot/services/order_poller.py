import asyncio
import datetime
import logging
from decimal import Decimal, InvalidOperation

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..database.repositories.orders import OrderRepository
from ..database.repositories.transactions import LedgerRepository
from ..database.repositories.users import UserRepository
from ..utils.emoji import pe
from .icheatbot import IcheatbotClient, IcheatbotError

logger = logging.getLogger("boosty.order_poller")

REFUNDABLE_STATUSES = ("canceled", "partial")
TERMINAL_STATUSES = ("completed", "canceled", "partial", "failed", "refunded")
STUCK_PENDING_AFTER = datetime.timedelta(minutes=10)

_STATUS_MAP = {
    "pending": "in_progress",
    "in progress": "in_progress",
    "inprogress": "in_progress",
    "processing": "in_progress",
    "completed": "completed",
    "complete": "completed",
    "partial": "partial",
    "canceled": "canceled",
    "cancelled": "canceled",
}


def normalize_status(raw_status: str) -> str:
    return _STATUS_MAP.get(str(raw_status).strip().lower(), "in_progress")


async def _process_batch(
    session_factory: async_sessionmaker[AsyncSession],
    api_client: IcheatbotClient,
    bot: Bot,
    limit: int,
) -> None:
    async with session_factory() as session:
        orders = await OrderRepository.list_open_for_polling(session, limit)
        pollable = [o for o in orders if o.external_order_id]

    if not pollable:
        return

    external_ids = [o.external_order_id for o in pollable]
    try:
        statuses = await api_client.status_bulk(external_ids)
    except IcheatbotError:
        statuses = await api_client.status_sequential(external_ids)

    for order in pollable:
        raw = statuses.get(order.external_order_id)
        if not raw:
            continue

        new_status = normalize_status(raw.get("status", ""))
        try:
            start_count = int(raw["start_count"]) if raw.get("start_count") not in (None, "") else None
        except (ValueError, TypeError):
            start_count = None
        try:
            remains = int(raw["remains"]) if raw.get("remains") not in (None, "") else None
        except (ValueError, TypeError):
            remains = None

        status_changed = new_status != order.status

        async with session_factory() as session:
            await OrderRepository.update_status(session, order.id, new_status, start_count, remains)

            refund_amount: Decimal | None = None
            if (
                status_changed
                and new_status in REFUNDABLE_STATUSES
                and remains
                and remains > 0
                and order.quantity > 0
            ):
                try:
                    refund_amount = (order.charge_rub * remains / order.quantity).quantize(Decimal("0.01"))
                except InvalidOperation:
                    refund_amount = None
                if refund_amount and refund_amount > 0:
                    new_balance = await UserRepository.credit(session, order.user_id, refund_amount)
                    await LedgerRepository.record(
                        session,
                        user_id=order.user_id,
                        type_="order_refund",
                        amount=refund_amount,
                        balance_after=new_balance,
                        related_order_id=order.id,
                        comment=f"Частичный возврат: заказ #{order.id} завершён не полностью",
                    )

            await session.commit()

            if status_changed and new_status in TERMINAL_STATUSES:
                user = await UserRepository.get_by_id(session, order.user_id)

        if status_changed and new_status in TERMINAL_STATUSES and user:
            await _notify(bot, user.tg_id, order.id, new_status, refund_amount)


async def _notify(bot: Bot, tg_id: int, order_id: int, status: str, refund_amount: Decimal | None) -> None:
    labels = {
        "completed": "✅ выполнен",
        "partial": "🟡 выполнен частично",
        "canceled": "❌ отменён",
        "failed": "❌ ошибка",
    }
    text = pe(f"📦 Заказ #{order_id} {labels.get(status, status)}.")
    if refund_amount:
        text += pe(f"\n💸 Возвращено на баланс: {refund_amount} ₽")
    try:
        await bot.send_message(tg_id, text, parse_mode="HTML")
    except Exception:
        logger.debug("could not notify user %s about order %s", tg_id, order_id)


async def _sweep_stuck_pending(session_factory: async_sessionmaker[AsyncSession], bot: Bot) -> None:
    """Recovers orders left in 'pending' by a process crash between the reserve step
    (funds debited, order row inserted) and the upstream add() call resolving — see
    order_flow.py's saga. Best-effort: if the crash happened to land in the narrow
    window right after add() actually succeeded upstream but before we recorded the
    external_order_id, this refunds the user for an order the provider may still have
    queued. That inherent gap can't be closed without idempotency keys on the upstream
    API, so it's logged for manual admin review rather than silently reconciled."""
    cutoff = datetime.datetime.now(datetime.timezone.utc) - STUCK_PENDING_AFTER
    async with session_factory() as session:
        stuck = await OrderRepository.list_stuck_pending(session, cutoff)

    for order in stuck:
        async with session_factory() as session:
            new_balance = await UserRepository.credit(session, order.user_id, order.charge_rub)
            await OrderRepository.mark_failed(
                session, order.id, "stuck in pending past timeout — auto-refunded, verify upstream manually"
            )
            await LedgerRepository.record(
                session,
                user_id=order.user_id,
                type_="order_refund",
                amount=order.charge_rub,
                balance_after=new_balance,
                related_order_id=order.id,
                comment=f"Возврат: заказ #{order.id} завис в обработке дольше {STUCK_PENDING_AFTER}",
            )
            await session.commit()
            user = await UserRepository.get_by_id(session, order.user_id)

        logger.warning(
            "order %s auto-refunded after being stuck pending — verify manually whether it was placed upstream",
            order.id,
        )
        if user:
            await _notify(bot, user.tg_id, order.id, "failed", order.charge_rub)


async def loop(
    session_factory: async_sessionmaker[AsyncSession],
    api_client: IcheatbotClient,
    bot: Bot,
    interval_sec: int,
    batch_limit: int = 200,
) -> None:
    while True:
        try:
            await _process_batch(session_factory, api_client, bot, batch_limit)
            await _sweep_stuck_pending(session_factory, bot)
        except Exception:
            logger.exception("order poller tick crashed unexpectedly")
        await asyncio.sleep(interval_sec)
