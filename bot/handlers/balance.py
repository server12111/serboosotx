import datetime
from decimal import Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..config import config
from ..database.models import User
from ..database.repositories.invoices import InvoiceRepository
from ..database.repositories.transactions import LedgerRepository
from ..keyboards.inline import back_kb, balance_quick_kb, history_kb, invoice_kb, order_confirm_kb
from ..services import payment_cryptobot
from ..services.invoice_reconciler import notify_referral_bonus, try_credit_paid_invoice
from ..states import OrderStates
from ..utils.emoji import pe
from ..utils.formatting import fmt_qty, fmt_rub
from ..utils.pagination import Page

router = Router(name="balance")

TX_TYPE_LABELS = {
    "topup": "➕ Пополнение",
    "order_debit": "🗂 Заказ",
    "order_refund": "↩️ Возврат",
    "admin_adjustment": "⚙️ Корректировка",
    "referral_bonus": "👥 Реферальный бонус",
}


class TopupStates(StatesGroup):
    waiting_amount = State()


@router.callback_query(F.data == "balance:quick")
async def cb_balance_quick(callback: CallbackQuery, user: User) -> None:
    text = f"💵 Ваш баланс: {fmt_rub(user.balance)}"
    await callback.message.edit_text(pe(text), reply_markup=balance_quick_kb(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "balance:topup:start")
async def cb_topup_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(TopupStates.waiting_amount)
    min_rub = await payment_cryptobot.get_min_topup_rub(config.CRYPTOBOT_TOKEN)
    await callback.message.edit_text(
        pe(f"➕ Введите сумму пополнения в рублях (минимум {fmt_rub(min_rub)}):"),
        reply_markup=back_kb("profile:menu", "❌ Отмена"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("balance:topup:quick:"))
async def cb_topup_quick(callback: CallbackQuery, state: FSMContext, user: User, session_factory) -> None:
    """Entered from the 'insufficient funds' order screen with the exact missing
    amount pre-filled — skips manual amount entry, creates the invoice right away."""
    amount_rub = Decimal(callback.data.split(":")[-1])
    await _create_and_show_invoice(callback, user, session_factory, amount_rub, edit=True)


@router.message(TopupStates.waiting_amount)
async def on_topup_amount(message: Message, state: FSMContext, user: User, session_factory) -> None:
    raw = (message.text or "").strip().replace(",", ".")
    try:
        amount = Decimal(raw)
    except InvalidOperation:
        await message.answer(pe("⚠️ Введите число, например 500"))
        return

    min_rub = await payment_cryptobot.get_min_topup_rub(config.CRYPTOBOT_TOKEN)
    if amount < min_rub:
        await message.answer(pe(f"⚠️ Минимальная сумма пополнения — {fmt_rub(min_rub)}"))
        return

    await state.clear()
    await _create_and_show_invoice(message, user, session_factory, amount, edit=False)


async def _create_and_show_invoice(
    target: CallbackQuery | Message, user: User, session_factory, amount_rub: Decimal, edit: bool
) -> None:
    invoice_data = await payment_cryptobot.create_invoice(
        config.CRYPTOBOT_TOKEN, amount_rub, payload=str(user.tg_id)
    )
    if invoice_data is None:
        text = pe("Не удалось создать счёт на оплату. Попробуйте позже.")
        if isinstance(target, CallbackQuery):
            await target.answer("Не удалось создать счёт на оплату. Попробуйте позже.", show_alert=True)
        else:
            await target.answer(text, parse_mode="HTML")
        return

    expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
        minutes=payment_cryptobot.INVOICE_EXPIRES_MINUTES
    )
    async with session_factory() as session:
        invoice = await InvoiceRepository.create(
            session,
            user_id=user.id,
            cryptobot_invoice_id=invoice_data["invoice_id"],
            asset=invoice_data["asset"],
            amount_crypto=invoice_data["amount_crypto"],
            amount_rub_locked=amount_rub,
            pay_url=invoice_data["pay_url"],
            expires_at=expires_at,
        )

    text = (
        f"💳 Счёт создан:\n"
        f"➕ К зачислению на баланс: {fmt_rub(amount_rub)}\n"
        f"💵 К оплате через CryptoBot (комиссия {payment_cryptobot.CRYPTOBOT_FEE_PERCENT}%): "
        f"{invoice_data['amount_crypto']} {invoice_data['asset']}\n\n"
        f"Оплатите по кнопке ниже и нажмите «Проверить оплату»."
    )
    kb = invoice_kb(invoice_data["pay_url"], invoice.id)
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(pe(text), reply_markup=kb, parse_mode="HTML")
        await target.answer()
    else:
        await target.answer(pe(text), reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("balance:invoice:check:"))
async def cb_invoice_check(callback: CallbackQuery, state: FSMContext, user: User, session_factory) -> None:
    invoice_id = int(callback.data.split(":")[-1])
    async with session_factory() as session:
        invoice = await InvoiceRepository.get_by_id(session, invoice_id)
    if invoice is None or invoice.user_id != user.id:
        await callback.answer("Счёт не найден.", show_alert=True)
        return

    if invoice.status == "paid":
        await callback.answer("✅ Счёт уже оплачен и зачислен.", show_alert=True)
        return

    remote = await payment_cryptobot.get_invoices(config.CRYPTOBOT_TOKEN, [invoice.cryptobot_invoice_id])
    remote_status = remote[0].get("status") if remote else None

    if remote_status != "paid":
        await callback.answer("⏳ Оплата ещё не поступила.", show_alert=True)
        return

    credited, new_balance, credited_user, referrer, referral_bonus = await try_credit_paid_invoice(
        session_factory, invoice
    )
    if credited and referrer and referral_bonus:
        await notify_referral_bonus(callback.bot, referrer.tg_id, referral_bonus)
    if credited and credited_user:
        await callback.message.edit_text(
            pe(f"✅ Баланс пополнен на {fmt_rub(invoice.amount_rub_locked)}\n💵 Текущий баланс: {fmt_rub(new_balance)}"),
            reply_markup=back_kb("profile:menu", "◀️ В меню"),
            parse_mode="HTML",
        )
        await _offer_resume_order(callback, state, new_balance)
    await callback.answer()


async def _offer_resume_order(callback: CallbackQuery, state: FSMContext, new_balance: Decimal) -> None:
    """If the top-up was triggered from an "insufficient funds" screen, the order the
    user was placing is still sitting in FSM state (order.py deliberately doesn't clear
    it in that case) — offer to pick it straight back up instead of making them
    re-browse the catalog and re-enter the link/quantity from scratch."""
    current_state = await state.get_state()
    if current_state != OrderStates.confirming.state:
        return

    data = await state.get_data()
    charge_raw = data.get("charge_rub")
    if not charge_raw or Decimal(charge_raw) > new_balance:
        return

    link = data.get("link", "")
    quantity = data.get("quantity")
    text = (
        f"✅ Средств теперь достаточно — можно оформить отложенный заказ:\n\n"
        f"🔗 {link}\n"
        f"🔢 Количество: {fmt_qty(quantity)}\n"
        f"💵 Сумма: {fmt_rub(Decimal(charge_raw))}"
    )
    await callback.message.answer(pe(text), reply_markup=order_confirm_kb(), parse_mode="HTML")


HISTORY_PAGE_SIZE = 10


@router.callback_query(F.data.startswith("balance:history:"))
async def cb_history(callback: CallbackQuery, user: User, session_factory) -> None:
    page_num = int(callback.data.split(":")[-1])
    async with session_factory() as session:
        # fetch one extra row to detect a next page without a separate count query
        fetched = await LedgerRepository.list_by_user(
            session, user.id, page_num * HISTORY_PAGE_SIZE, HISTORY_PAGE_SIZE + 1
        )

    if not fetched and page_num == 0:
        await callback.message.edit_text(
            pe("🗃 История операций пуста."), reply_markup=back_kb("profile:menu", "◀️ Назад")
        )
        await callback.answer()
        return

    has_next = len(fetched) > HISTORY_PAGE_SIZE
    transactions = fetched[:HISTORY_PAGE_SIZE]
    page = Page(offset=0, limit=HISTORY_PAGE_SIZE, page=page_num, has_prev=page_num > 0, has_next=has_next)

    lines = ["🗃 История операций:\n"]
    for tx in transactions:
        sign = "+" if tx.amount >= 0 else ""
        label = TX_TYPE_LABELS.get(tx.type, tx.type)
        lines.append(f"{label}: {sign}{fmt_rub(tx.amount)} (баланс: {fmt_rub(tx.balance_after)})")

    await callback.message.edit_text(pe("\n".join(lines)), reply_markup=history_kb(page), parse_mode="HTML")
    await callback.answer()
