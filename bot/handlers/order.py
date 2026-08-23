import time
from decimal import Decimal

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..config import config
from ..database.models import User
from ..database.repositories.services import ServiceRepository
from ..database.repositories.settings import SettingsRepository
from ..database.repositories.users import UserRepository
from ..keyboards.inline import back_kb, insufficient_funds_kb, link_warning_kb, order_confirm_kb
from ..services import payment_cryptobot
from ..services.icheatbot import IcheatbotClient
from ..services.link_validators import looks_valid
from ..services.order_flow import place_order
from ..services.pricing import compute_price
from ..states import OrderStates
from ..utils.emoji import pe
from ..utils.formatting import fmt_qty, fmt_rub

router = Router(name="order")

# In-process replacement for the old Redis SET-NX lock: the bot is a single process
# (run.py's own file lock guarantees at most one instance runs), so a plain dict of
# user_id -> lock-expiry timestamp gives the same double-tap protection with no
# separate process to run.
_order_lock_until: dict[int, float] = {}
_ORDER_LOCK_SECONDS = 30  # comfortably exceeds IcheatbotClient's own HTTP timeout (20s,
# see icheatbot.py) — place_order() can legitimately take that long inside this lock.


@router.callback_query(F.data.startswith("service:order:"))
async def cb_start_order(
    callback: CallbackQuery, state: FSMContext, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    service_id = int(callback.data.split(":")[-1])
    async with session_factory() as session:
        service = await ServiceRepository.get_by_id(session, service_id)
    if service is None or not service.is_active:
        await callback.answer("Услуга больше недоступна.", show_alert=True)
        return

    await state.update_data(service_id=service_id)
    await state.set_state(OrderStates.waiting_link)
    await callback.message.edit_text(
        pe(f"🔗 Отправьте ссылку (или юзернейм) для «{service.name}»:"),
        reply_markup=back_kb("catalog:platforms:0", "❌ Отмена"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(OrderStates.waiting_link)
async def on_link_input(
    message: Message, state: FSMContext, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    link = (message.text or "").strip()
    if not link:
        await message.answer(pe("⚠️ Отправьте текстовую ссылку."))
        return

    data = await state.get_data()
    async with session_factory() as session:
        service = await ServiceRepository.get_by_id(session, data["service_id"])
    if service is None or not service.is_active:
        await state.clear()
        await message.answer(pe("Услуга больше недоступна."))
        return

    if not looks_valid(service.platform, link):
        await state.update_data(pending_link=link)
        await message.answer(
            pe(f"⚠️ Ссылка не похожа на типичную для этой платформы:\n{link}\n\nПродолжить всё равно?"),
            reply_markup=link_warning_kb(),
            parse_mode="HTML",
        )
        return

    await state.update_data(link=link)
    await _ask_quantity(message, state, service)


@router.callback_query(F.data == "order:link_continue", OrderStates.waiting_link)
async def cb_link_continue(callback: CallbackQuery, state: FSMContext, session_factory: async_sessionmaker[AsyncSession]) -> None:
    data = await state.get_data()
    link = data.get("pending_link")
    if not link:
        await callback.answer()
        return
    async with session_factory() as session:
        service = await ServiceRepository.get_by_id(session, data["service_id"])
    await state.update_data(link=link)
    await callback.answer()
    await _ask_quantity(callback.message, state, service, edit=True)


@router.callback_query(F.data == "order:link_retry", OrderStates.waiting_link)
async def cb_link_retry(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text(
        pe("🔗 Отправьте ссылку (или юзернейм) ещё раз:"),
        reply_markup=back_kb("catalog:platforms:0", "❌ Отмена"),
        parse_mode="HTML",
    )
    await callback.answer()


async def _ask_quantity(message: Message, state: FSMContext, service, edit: bool = False) -> None:
    await state.set_state(OrderStates.waiting_quantity)
    text = pe(
        f"🔢 Введите количество (от {fmt_qty(service.min_quantity)} до {fmt_qty(service.max_quantity)}):"
    )
    kb = back_kb("catalog:platforms:0", "❌ Отмена")
    if edit:
        await message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.message(OrderStates.waiting_quantity)
async def on_quantity_input(
    message: Message, state: FSMContext, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer(pe("⚠️ Введите целое число."))
        return
    quantity = int(raw)

    data = await state.get_data()
    async with session_factory() as session:
        service = await ServiceRepository.get_by_id(session, data["service_id"])
        if service is None or not service.is_active:
            await state.clear()
            await message.answer(pe("Услуга больше недоступна."))
            return
        if not (service.min_quantity <= quantity <= service.max_quantity):
            await message.answer(
                pe(f"⚠️ Количество должно быть от {fmt_qty(service.min_quantity)} до {fmt_qty(service.max_quantity)}.")
            )
            return
        markup = await SettingsRepository.get_decimal(session, "markup_percent", config.DEFAULT_MARKUP_PERCENT)

    charge = compute_price(service.rate_rub, quantity, markup)
    await state.update_data(quantity=quantity, charge_rub=str(charge))
    await state.set_state(OrderStates.confirming)

    link = data.get("link", "")
    text = (
        f"🧾 Проверьте заказ:\n\n"
        f"🗂 {service.name}\n"
        f"🔗 {link}\n"
        f"🔢 Количество: {fmt_qty(quantity)}\n"
        f"💵 Сумма: {fmt_rub(charge)}"
    )
    await message.answer(pe(text), reply_markup=order_confirm_kb(), parse_mode="HTML")


@router.callback_query(F.data == "order:cancel")
async def cb_order_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text(pe("❌ Заказ отменён."), reply_markup=back_kb("menu:main", "◀️ В меню"))
    await callback.answer()


@router.callback_query(F.data == "order:confirm", OrderStates.confirming)
async def cb_order_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    session_factory: async_sessionmaker[AsyncSession],
    api_client: IcheatbotClient,
) -> None:
    now = time.monotonic()
    locked_until = _order_lock_until.get(user.id)
    if locked_until is not None and locked_until > now:
        await callback.answer("⏳ Заказ уже обрабатывается…", show_alert=True)
        return
    _order_lock_until[user.id] = now + _ORDER_LOCK_SECONDS

    await callback.message.edit_text(pe("⏳ Обработка…"))
    await callback.answer()

    try:
        data = await state.get_data()
        async with session_factory() as session:
            service = await ServiceRepository.get_by_id(session, data["service_id"])
            markup = await SettingsRepository.get_decimal(
                session, "markup_percent", config.DEFAULT_MARKUP_PERCENT
            )

        if service is None or not service.is_active:
            await state.clear()
            await callback.message.edit_text(pe("Услуга больше недоступна."), reply_markup=back_kb("menu:main"))
            return

        quantity = data["quantity"]
        if not (service.min_quantity <= quantity <= service.max_quantity):
            await state.clear()
            await callback.message.edit_text(
                pe("⚠️ Количество вне допустимого диапазона (услуга обновилась). Начните заказ заново."),
                reply_markup=back_kb("catalog:platforms:0"),
            )
            return

        result = await place_order(
            session_factory=session_factory,
            api_client=api_client,
            user_id=user.id,
            service=service,
            link=data["link"],
            quantity=quantity,
            markup_percent=markup,
        )

        if result.ok:
            await state.clear()
            text = f"✅ Заказ #{result.order_id} принят!\n🆔 ID у поставщика: {result.external_order_id}"
            await callback.message.edit_text(pe(text), reply_markup=back_kb("orders:list:0", "🏷 Мои заказы"))
        elif result.reason == "insufficient_funds":
            # Deliberately NOT clearing state here — the order (service/link/quantity)
            # stays in FSM data so balance.py can offer to resume it straight after a
            # top-up instead of making the user re-browse and re-enter everything.
            async with session_factory() as session:
                fresh_user = await UserRepository.get_by_id(session, user.id)
            missing = (result.charge_rub - fresh_user.balance).quantize(Decimal("0.01"))
            min_topup = await payment_cryptobot.get_min_topup_rub(config.CRYPTOBOT_TOKEN)
            missing = max(missing, min_topup)
            text = (
                f"❌ Недостаточно средств.\n"
                f"Нужно: {fmt_rub(result.charge_rub)}, на балансе: {fmt_rub(fresh_user.balance)}."
            )
            await callback.message.edit_text(pe(text), reply_markup=insufficient_funds_kb(missing))
        else:
            await state.clear()
            text = "❌ Не удалось разместить заказ у поставщика. Средства возвращены на баланс."
            await callback.message.edit_text(pe(text), reply_markup=back_kb("menu:main"))
    finally:
        _order_lock_until.pop(user.id, None)
