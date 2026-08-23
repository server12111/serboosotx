from aiogram import F, Router
from aiogram.types import CallbackQuery

from ..database.models import User
from ..database.repositories.orders import OrderRepository
from ..database.repositories.services import ServiceRepository
from ..keyboards.inline import back_kb, order_detail_kb, orders_list_kb
from ..services.icheatbot import IcheatbotClient, IcheatbotError
from ..utils.emoji import pe
from ..utils.formatting import fmt_qty, fmt_rub
from ..utils.pagination import paginate

router = Router(name="orders_list")

STATUS_LABELS = {
    "pending": "⏳ в обработке",
    "placed": "🕓 отправлен поставщику",
    "in_progress": "🔷 выполняется",
    "completed": "✅ выполнен",
    "partial": "🟡 выполнен частично",
    "canceled": "❌ отменён",
    "failed": "❌ ошибка",
    "refunded": "↩️ возвращён",
}


@router.callback_query(F.data.startswith("orders:list:"))
async def cb_orders_list(callback: CallbackQuery, user: User, session_factory) -> None:
    page_num = int(callback.data.split(":")[-1])
    async with session_factory() as session:
        total = await OrderRepository.count_by_user(session, user.id)
        page = paginate(page_num, total)
        orders = await OrderRepository.list_by_user(session, user.id, page.offset, page.limit)

    if not orders:
        await callback.message.edit_text(
            pe("📋 У вас пока нет заказов."), reply_markup=back_kb("menu:main", "◀️ В меню")
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        pe("📋 Ваши заказы:"), reply_markup=orders_list_kb(orders, page), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("orders:view:"))
async def cb_order_view(callback: CallbackQuery, user: User, session_factory) -> None:
    order_id = int(callback.data.split(":")[-1])
    async with session_factory() as session:
        order = await OrderRepository.get_by_id(session, order_id)
        if order is None or order.user_id != user.id:
            await callback.answer("Заказ не найден.", show_alert=True)
            return
        service = await ServiceRepository.get_by_id(session, order.service_id)

    text = (
        f"📦 Заказ #{order.id}\n\n"
        f"🗂 {service.name if service else '—'}\n"
        f"🔗 {order.link}\n"
        f"🔢 Количество: {fmt_qty(order.quantity)}\n"
        f"💵 Сумма: {fmt_rub(order.charge_rub)}\n"
        f"📊 Статус: {STATUS_LABELS.get(order.status, order.status)}"
    )
    if order.start_count is not None:
        text += f"\n🏁 Стартовое значение: {fmt_qty(order.start_count)}"
    if order.remains is not None:
        text += f"\n⏳ Осталось: {fmt_qty(order.remains)}"

    await callback.message.edit_text(
        pe(text), reply_markup=order_detail_kb(order, service) if service else back_kb("orders:list:0"), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("order:refill:"))
async def cb_order_refill(callback: CallbackQuery, user: User, session_factory, api_client: IcheatbotClient) -> None:
    order_id = int(callback.data.split(":")[-1])
    async with session_factory() as session:
        order = await OrderRepository.get_by_id(session, order_id)
        if order is None or order.user_id != user.id or not order.external_order_id:
            await callback.answer("Заказ не найден.", show_alert=True)
            return
    try:
        await api_client.refill(order.external_order_id)
        await callback.answer("🔄 Запрос на реролл отправлен.", show_alert=True)
    except IcheatbotError as e:
        await callback.answer(f"Не удалось запросить реролл: {e}", show_alert=True)


