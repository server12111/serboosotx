from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject


class AdminMiddleware(BaseMiddleware):
    def __init__(self, admin_ids: set[int]):
        self._admin_ids = admin_ids

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        if tg_user is None or tg_user.id not in self._admin_ids:
            if isinstance(event, CallbackQuery):
                await event.answer("⛔ Доступ только для администраторов.", show_alert=True)
            elif isinstance(event, Message):
                await event.answer("⛔ Доступ только для администраторов.")
            return None
        return await handler(event, data)
