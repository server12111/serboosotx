from decimal import Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ...config import config
from ...database.repositories.admin_actions import AdminActionRepository
from ...database.repositories.settings import SettingsRepository
from ...keyboards.inline import admin_markup_kb, back_kb
from ...utils.emoji import pe

router = Router(name="admin_markup")


class AdminStates(StatesGroup):
    markup_waiting_value = State()


@router.callback_query(F.data == "admin:markup:show")
async def cb_markup_show(callback: CallbackQuery, session_factory) -> None:
    async with session_factory() as session:
        markup = await SettingsRepository.get_decimal(session, "markup_percent", config.DEFAULT_MARKUP_PERCENT)
    text = f"📈 Текущая наценка: {markup}%"
    await callback.message.edit_text(pe(text), reply_markup=admin_markup_kb(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin:markup:set")
async def cb_markup_set_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminStates.markup_waiting_value)
    await callback.message.edit_text(
        pe("📈 Отправьте новое значение наценки в процентах:"), reply_markup=back_kb("admin:panel", "❌ Отмена")
    )
    await callback.answer()


@router.message(AdminStates.markup_waiting_value)
async def on_markup_value(message: Message, state: FSMContext, session_factory) -> None:
    raw = (message.text or "").strip().replace(",", ".")
    try:
        value = Decimal(raw)
    except InvalidOperation:
        await message.answer(pe("⚠️ Введите число, например 30"))
        return

    async with session_factory() as session:
        await SettingsRepository.set(session, "markup_percent", str(value), updated_by=message.from_user.id)
        await AdminActionRepository.log(
            session, message.from_user.id, "markup_change", payload={"new_value": str(value)}
        )
    await state.clear()
    await message.answer(pe(f"✅ Наценка обновлена: {value}%"), reply_markup=back_kb("admin:panel", "◀️ Назад"))
