from decimal import Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ...database.models import User
from ...database.repositories.admin_actions import AdminActionRepository
from ...database.repositories.transactions import LedgerRepository
from ...database.repositories.users import UserRepository
from ...keyboards.inline import admin_user_actions_kb, back_kb
from ...utils.emoji import pe
from ...utils.formatting import fmt_rub

router = Router(name="admin_users")


class AdminStates(StatesGroup):
    user_search_waiting = State()
    balance_adjust_waiting = State()


def _user_card_text(user: User) -> str:
    status = "🚫 забанен" if user.is_banned else "✅ активен"
    return (
        f"👤 Пользователь #{user.id}\n"
        f"🆔 tg_id: {user.tg_id}\n"
        f"📛 @{user.username or '—'} ({user.full_name or '—'})\n"
        f"💵 Баланс: {fmt_rub(user.balance)}\n"
        f"📊 Статус: {status}"
    )


@router.callback_query(F.data == "admin:user:search")
async def cb_user_search_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminStates.user_search_waiting)
    await callback.message.edit_text(
        pe("👤 Отправьте tg_id или username пользователя:"), reply_markup=back_kb("admin:panel", "❌ Отмена")
    )
    await callback.answer()


@router.message(AdminStates.user_search_waiting)
async def on_user_search(message: Message, state: FSMContext, session_factory) -> None:
    query = (message.text or "").strip().lstrip("@")
    async with session_factory() as session:
        results = await UserRepository.search(session, query)

    await state.clear()
    if not results:
        await message.answer(pe("Пользователь не найден."), reply_markup=back_kb("admin:panel", "◀️ Назад"))
        return

    user = results[0]
    await message.answer(pe(_user_card_text(user)), reply_markup=admin_user_actions_kb(user), parse_mode="HTML")


@router.callback_query(F.data.startswith("admin:ban:"))
async def cb_ban(callback: CallbackQuery, session_factory) -> None:
    user_id = int(callback.data.split(":")[-1])
    async with session_factory() as session:
        await UserRepository.set_ban(session, user_id, True)
        await AdminActionRepository.log(session, callback.from_user.id, "ban", target_user_id=user_id)
        user = await UserRepository.get_by_id(session, user_id)

    await callback.message.edit_text(pe(_user_card_text(user)), reply_markup=admin_user_actions_kb(user), parse_mode="HTML")
    await callback.answer("🚫 Пользователь забанен.")


@router.callback_query(F.data.startswith("admin:unban:"))
async def cb_unban(callback: CallbackQuery, session_factory) -> None:
    user_id = int(callback.data.split(":")[-1])
    async with session_factory() as session:
        await UserRepository.set_ban(session, user_id, False)
        await AdminActionRepository.log(session, callback.from_user.id, "unban", target_user_id=user_id)
        user = await UserRepository.get_by_id(session, user_id)

    await callback.message.edit_text(pe(_user_card_text(user)), reply_markup=admin_user_actions_kb(user), parse_mode="HTML")
    await callback.answer("✅ Пользователь разбанен.")


@router.callback_query(F.data.startswith("admin:balance:adjust:"))
async def cb_balance_adjust_start(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = int(callback.data.split(":")[-1])
    await state.update_data(target_user_id=user_id)
    await state.set_state(AdminStates.balance_adjust_waiting)
    await callback.message.edit_text(
        pe("💵 Введите сумму изменения баланса (например 500 или -200):"),
        reply_markup=back_kb("admin:panel", "❌ Отмена"),
    )
    await callback.answer()


@router.message(AdminStates.balance_adjust_waiting)
async def on_balance_adjust(message: Message, state: FSMContext, session_factory) -> None:
    raw = (message.text or "").strip().replace(",", ".").replace("+", "")
    try:
        delta = Decimal(raw)
    except InvalidOperation:
        await message.answer(pe("⚠️ Введите число, например 500 или -200"))
        return

    data = await state.get_data()
    user_id = data["target_user_id"]
    await state.clear()

    async with session_factory() as session:
        if delta >= 0:
            new_balance = await UserRepository.credit(session, user_id, delta)
        else:
            new_balance = await UserRepository.try_debit(session, user_id, -delta)
            if new_balance is None:
                await session.rollback()
                await message.answer(pe("⚠️ Недостаточно средств для списания такой суммы."))
                return

        await LedgerRepository.record(
            session,
            user_id=user_id,
            type_="admin_adjustment",
            amount=delta,
            balance_after=new_balance,
            comment=f"Ручная корректировка администратором {message.from_user.id}",
        )
        await AdminActionRepository.log(
            session, message.from_user.id, "balance_adjust", target_user_id=user_id, payload={"delta": str(delta)}
        )
        await session.commit()
        user = await UserRepository.get_by_id(session, user_id)

    await message.answer(pe(_user_card_text(user)), reply_markup=admin_user_actions_kb(user), parse_mode="HTML")
