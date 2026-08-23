from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..config import config
from ..database.models import User
from ..keyboards.inline import main_menu_kb, with_admin_row
from ..utils.emoji import pe

router = Router(name="start")

WELCOME_TEXT = (
    "🤖 <b>SeroX Company</b>\n\n"
    "Накрутка подписчиков, лайков, просмотров и других показателей для Telegram, "
    "Instagram, TikTok, YouTube и ещё десятка платформ.\n\n"
    "⚡ Быстрое выполнение\n"
    "💵 Честные цены\n"
    "🔒 Безопасная оплата"
)


def menu_kb(user: User):
    kb = main_menu_kb()
    if user.tg_id in config.ADMIN_IDS:
        kb = with_admin_row(kb)
    return kb


@router.message(CommandStart())
async def cmd_start(message: Message, user: User, state: FSMContext) -> None:
    # /start is the universal escape hatch — always clear any stuck FSM state.
    await state.clear()
    await message.answer(pe(WELCOME_TEXT), reply_markup=menu_kb(user), parse_mode="HTML")


@router.callback_query(F.data == "menu:main")
async def cb_main_menu(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text(pe(WELCOME_TEXT), reply_markup=menu_kb(user), parse_mode="HTML")
    await callback.answer()
