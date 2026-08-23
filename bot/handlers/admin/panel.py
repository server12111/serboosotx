from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ...keyboards.inline import admin_panel_kb
from ...utils.emoji import pe

router = Router(name="admin_panel")


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(pe("⚙️ Админ-панель"), reply_markup=admin_panel_kb(), parse_mode="HTML")


@router.callback_query(F.data == "admin:panel")
async def cb_admin_panel(callback: CallbackQuery, state: FSMContext) -> None:
    # Every admin FSM flow's cancel/back button routes here — clearing state is what
    # actually makes "cancel" cancel, instead of leaving a stale FSM state that later
    # captures the admin's next unrelated message.
    await state.clear()
    await callback.message.edit_text(pe("⚙️ Админ-панель"), reply_markup=admin_panel_kb(), parse_mode="HTML")
    await callback.answer()
