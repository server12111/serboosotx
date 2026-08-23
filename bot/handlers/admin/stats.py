from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import func, select

from ...database.models import BalanceTransaction, Order, User
from ...keyboards.inline import back_kb
from ...utils.emoji import pe
from ...utils.formatting import fmt_rub

router = Router(name="admin_stats")


@router.callback_query(F.data == "admin:stats")
async def cb_admin_stats(callback: CallbackQuery, session_factory) -> None:
    async with session_factory() as session:
        users_total = (await session.execute(select(func.count()).select_from(User))).scalar_one()
        orders_total = (await session.execute(select(func.count()).select_from(Order))).scalar_one()
        revenue = (
            await session.execute(
                select(func.coalesce(func.sum(Order.charge_rub), 0)).where(
                    Order.status.notin_(("pending", "failed"))
                )
            )
        ).scalar_one()
        cost = (
            await session.execute(
                select(func.coalesce(func.sum(Order.upstream_cost_rub), 0)).where(
                    Order.status.notin_(("pending", "failed"))
                )
            )
        ).scalar_one()
        topups = (
            await session.execute(
                select(func.coalesce(func.sum(BalanceTransaction.amount), 0)).where(
                    BalanceTransaction.type == "topup"
                )
            )
        ).scalar_one()

    profit = revenue - cost
    text = (
        f"📊 Статистика\n\n"
        f"👥 Пользователей: {users_total}\n"
        f"📦 Заказов: {orders_total}\n"
        f"💵 Оборот по заказам: {fmt_rub(revenue)}\n"
        f"📈 Прибыль (оценка): {fmt_rub(profit)}\n"
        f"➕ Всего пополнений: {fmt_rub(topups)}"
    )
    await callback.message.edit_text(pe(text), reply_markup=back_kb("admin:panel", "◀️ Назад"), parse_mode="HTML")
    await callback.answer()
