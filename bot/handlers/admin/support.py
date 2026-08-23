from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ...config import config
from ...database.repositories.admin_actions import AdminActionRepository
from ...database.repositories.settings import SettingsRepository
from ...keyboards.inline import admin_support_kb, back_kb
from ...utils.emoji import pe

router = Router(name="admin_support")


class AdminStates(StatesGroup):
    support_waiting_value = State()


@router.callback_query(F.data == "admin:support:show")
async def cb_support_show(callback: CallbackQuery, session_factory, state: FSMContext) -> None:
    await state.clear()
    async with session_factory() as session:
        username = await SettingsRepository.get(session, "support_username") or config.SUPPORT_USERNAME
    text = f"🆘 Текущий аккаунт поддержки: {username or 'не задан'}"
    await callback.message.edit_text(pe(text), reply_markup=admin_support_kb(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin:support:set")
async def cb_support_set_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminStates.support_waiting_value)
    await callback.message.edit_text(
        pe("🆘 Отправьте username бота/аккаунта поддержки (например support_bot, без @):"),
        reply_markup=back_kb("admin:support:show", "❌ Отмена"),
    )
    await callback.answer()


@router.message(AdminStates.support_waiting_value)
async def on_support_value(message: Message, state: FSMContext, session_factory) -> None:
    username = (message.text or "").strip().lstrip("@")
    if not username:
        await message.answer(pe("⚠️ Отправьте непустой username."))
        return

    async with session_factory() as session:
        await SettingsRepository.set(session, "support_username", username, updated_by=message.from_user.id)
        await AdminActionRepository.log(
            session, message.from_user.id, "support_username_change", payload={"new_value": username}
        )
    await state.clear()
    await message.answer(pe(f"✅ Аккаунт поддержки обновлён: @{username}"), reply_markup=back_kb("admin:panel", "◀️ Назад"))
