import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, TelegramObject

DEFAULT_WINDOW_MS = 600

STRICT_PREFIXES: dict[str, int] = {
    "order:confirm": 4000,
    "balance:topup:create": 4000,
    "admin:balance:adjust": 4000,
}


class ThrottlingMiddleware(BaseMiddleware):
    """In-process SET-NX-with-TTL-style anti-flood — the bot runs as a single process
    (run.py's own file lock already guarantees at most one instance), so a plain dict
    keyed by (user, bucket) -> expiry timestamp gives the same guarantee a Redis key
    would, with no extra process to run. A default window applies to every event from
    a user; money-adjacent callback prefixes get a stricter window on top — this is a
    rate-limiting/UX concern, separate from the correctness-critical per-order lock
    taken inside the order confirmation handler itself."""

    def __init__(self) -> None:
        self._expiry: dict[str, float] = {}

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

        key = f"{tg_user.id}:{bucket}"
        now = time.monotonic()
        expires_at = self._expiry.get(key)
        if expires_at is not None and expires_at > now:
            if isinstance(event, CallbackQuery):
                await event.answer("⏳ Не так быстро…", show_alert=False)
            return None

        self._expiry[key] = now + window_ms / 1000
        # Opportunistic cleanup so the dict doesn't grow forever with stale keys —
        # cheap relative to a real event handling, and only runs when we're about to
        # add a new key anyway.
        if len(self._expiry) > 10_000:
            self._expiry = {k: v for k, v in self._expiry.items() if v > now}

        return await handler(event, data)
