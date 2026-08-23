from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from redis.asyncio import Redis

DEFAULT_WINDOW_MS = 600

STRICT_PREFIXES: dict[str, int] = {
    "order:confirm": 4000,
    "balance:topup:create": 4000,
    "admin:balance:adjust": 4000,
    "order:cancel_upstream": 4000,
}


class ThrottlingMiddleware(BaseMiddleware):
    """Redis SET-NX-based anti-flood. A default window applies to every event from a
    user; money-adjacent callback prefixes get a stricter window on top — this is a
    rate-limiting/UX concern, separate from the correctness-critical per-order lock
    taken inside the order confirmation handler itself."""

    def __init__(self, redis: Redis):
        self._redis = redis

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        if tg_user is None:
            return await handler(event, data)

        window_ms = DEFAULT_WINDOW_MS
        bucket = "default"
        if isinstance(event, CallbackQuery) and event.data:
            for prefix, ms in STRICT_PREFIXES.items():
                if event.data.startswith(prefix):
                    window_ms = ms
                    bucket = prefix
                    break

        key = f"throttle:{tg_user.id}:{bucket}"
        acquired = await self._redis.set(key, "1", nx=True, px=window_ms)
        if not acquired:
            if isinstance(event, CallbackQuery):
                await event.answer("⏳ Не так быстро…", show_alert=False)
            return None

        return await handler(event, data)
