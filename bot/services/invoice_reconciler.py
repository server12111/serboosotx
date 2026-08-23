import asyncio
import logging
from decimal import ROUND_HALF_UP, Decimal

from aiogram import Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import BaseStorage, StorageKey
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..config import config
from ..database.models import CryptoBotInvoice, User
from ..database.repositories.invoices import InvoiceRepository
from ..database.repositories.settings import SettingsRepository
from ..database.repositories.transactions import LedgerRepository
from ..database.repositories.users import UserRepository
from ..keyboards.inline import order_confirm_kb
from ..states import OrderStates
from ..utils.emoji import pe
from ..utils.formatting import fmt_qty, fmt_rub
from . import payment_cryptobot

logger = logging.getLogger("boosty.invoice_reconciler")


async def try_credit_paid_invoice(
    session_factory: async_sessionmaker[AsyncSession], invoice: CryptoBotInvoice
) -> tuple[bool, Decimal | None, User | None, User | None, Decimal | None]:
    """Atomically transitions an invoice active->paid, credits the user, and — if they
    were referred — credits their referrer a percentage of this same top-up. Safe to
    call from both the periodic reconciler loop and a user-triggered manual check:
    mark_paid_if_active() guards the whole block so it runs at most once ever per
    invoice, which makes the referral bonus exactly-once by construction too (it can
    never fire twice for the same top-up, whichever path gets there first).

    Returns (credited, new_balance, user, referrer, referral_bonus)."""
    async with session_factory() as session:
        transitioned = await InvoiceRepository.mark_paid_if_active(session, invoice.id)
        if not transitioned:
            await session.commit()
            return False, None, None, None, None

        new_balance = await UserRepository.credit(session, invoice.user_id, invoice.amount_rub_locked)
        await LedgerRepository.record(
            session,
            user_id=invoice.user_id,
            type_="topup",
            amount=invoice.amount_rub_locked,
            balance_after=new_balance,
            related_invoice_id=invoice.id,
            comment=f"Пополнение через CryptoBot (#{invoice.cryptobot_invoice_id})",
        )
        user = await UserRepository.get_by_id(session, invoice.user_id)

        referrer = None
        referral_bonus = None
        if user and user.referrer_id:
            referral_percent = await SettingsRepository.get_decimal(
                session, "referral_percent", config.DEFAULT_REFERRAL_PERCENT
            )
            referral_bonus = (invoice.amount_rub_locked * referral_percent / Decimal(100)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            if referral_bonus > 0:
                referrer_balance = await UserRepository.credit(session, user.referrer_id, referral_bonus)
                await LedgerRepository.record(
                    session,
                    user_id=user.referrer_id,
                    type_="referral_bonus",
                    amount=referral_bonus,
                    balance_after=referrer_balance,
                    related_invoice_id=invoice.id,
                    comment=f"Реферальный бонус с пополнения пользователя #{user.id}",
                )
                referrer = await UserRepository.get_by_id(session, user.referrer_id)

        await session.commit()
        return True, new_balance, user, referrer, referral_bonus


async def _process_once(
    session_factory: async_sessionmaker[AsyncSession], cryptobot_token: str, bot: Bot, storage: BaseStorage
) -> None:
    async with session_factory() as session:
        active = await InvoiceRepository.list_active(session)

    if not active:
        return

    remote = await payment_cryptobot.get_invoices(
        cryptobot_token, [inv.cryptobot_invoice_id for inv in active]
    )
    remote_by_id = {int(item["invoice_id"]): item for item in remote}

    for invoice in active:
        remote_item = remote_by_id.get(invoice.cryptobot_invoice_id)
        if not remote_item:
            continue
        status = remote_item.get("status")

        if status == "paid":
            credited, new_balance, user, referrer, referral_bonus = await try_credit_paid_invoice(
                session_factory, invoice
            )
            if credited and user:
                await _notify_paid(bot, user.tg_id, invoice.amount_rub_locked, new_balance)
                await offer_resume_order(bot, storage, user.tg_id, new_balance)
            if credited and referrer and referral_bonus:
                await notify_referral_bonus(bot, referrer.tg_id, referral_bonus)
        elif status == "expired":
            async with session_factory() as session:
                await InvoiceRepository.mark_expired(session, invoice.id)
                await session.commit()


async def _notify_paid(bot: Bot, tg_id: int, credited_amount: Decimal, new_balance: Decimal) -> None:
    text = pe(f"✅ Баланс пополнен на {credited_amount} ₽\n💵 Текущий баланс: {new_balance} ₽")
    try:
        await bot.send_message(tg_id, text, parse_mode="HTML")
    except Exception:
        logger.debug("could not notify user %s about invoice payment", tg_id)


async def notify_referral_bonus(bot: Bot, tg_id: int, bonus: Decimal) -> None:
    text = pe(f"👥 Реферальный бонус: +{bonus} ₽ (ваш реферал пополнил баланс)")
    try:
        await bot.send_message(tg_id, text, parse_mode="HTML")
    except Exception:
        logger.debug("could not notify referrer %s about bonus", tg_id)


async def offer_resume_order(bot: Bot, storage: BaseStorage, tg_id: int, new_balance: Decimal) -> None:
    """Most top-ups triggered from an "insufficient funds" screen are actually picked
    up here (this background sweep), not via the manual "Проверить оплату" button — so
    the same resume-the-pending-order offer implemented for the manual-check path in
    balance.py needs to happen here too, using a manually-constructed FSMContext since
    there's no live Update to inject one for us. Private-chat DMs use chat_id == the
    user's own tg_id, so this key reconstruction is safe."""
    try:
        key = StorageKey(bot_id=bot.id, chat_id=tg_id, user_id=tg_id)
        state = FSMContext(storage=storage, key=key)
        current_state = await state.get_state()
        if current_state != OrderStates.confirming.state:
            return

        data = await state.get_data()
        charge_raw = data.get("charge_rub")
        if not charge_raw or Decimal(charge_raw) > new_balance:
            return

        text = (
            f"✅ Средств теперь достаточно — можно оформить отложенный заказ:\n\n"
            f"🔗 {data.get('link', '')}\n"
            f"🔢 Количество: {fmt_qty(data.get('quantity'))}\n"
            f"💵 Сумма: {fmt_rub(Decimal(charge_raw))}"
        )
        await bot.send_message(tg_id, pe(text), reply_markup=order_confirm_kb(), parse_mode="HTML")
    except Exception:
        logger.debug("could not offer resumed order to user %s", tg_id)


async def loop(
    session_factory: async_sessionmaker[AsyncSession],
    cryptobot_token: str,
    bot: Bot,
    storage: BaseStorage,
    interval_sec: int,
) -> None:
    while True:
        try:
            await _process_once(session_factory, cryptobot_token, bot, storage)
        except Exception:
            logger.exception("invoice reconciler tick crashed unexpectedly")
        await asyncio.sleep(interval_sec)
