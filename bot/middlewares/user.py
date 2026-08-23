import datetime
import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..database.repositories.users import UserRepository

logger = logging.getLogger("boosty.middlewares.user")

_LAST_SEEN_THROTTLE = datetime.timedelta(minutes=5)
_last_seen_cache: dict[int, datetime.datetime] = {}


def _extract_referrer_tg_id(event: TelegramObject) -> int | None:
    """Parses a `/start ref_<tg_id>` deep link. Only meaningful on a brand-new user —
    get_or_create() only applies referrer_id on the INSERT path, so this is a no-op
    for anyone who already has an account."""
    if not isinstance(event, Message) or not event.text:
        return None
    parts = event.text.split(maxsplit=1)
    if len(parts) != 2 or parts[0] != "/start" or not parts[1].startswith("ref_"):
        return None
    try:
        return int(parts[1][len("ref_"):])
    except ValueError:
        return None


class UserMiddleware(BaseMiddleware):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        if tg_user is None:
            return await handler(event, data)

        referrer_tg_id = _extract_referrer_tg_id(event)

        async with self._session_factory() as session:
            referrer_id = None
            if referrer_tg_id is not None and referrer_tg_id != tg_user.id:
                referrer = await UserRepository.get_by_tg_id(session, referrer_tg_id)
                if referrer is not None:
                    referrer_id = referrer.id

            user = await UserRepository.get_or_create(
                session, tg_user.id, tg_user.username, tg_user.full_name, referrer_id=referrer_id
            )

            now = datetime.datetime.now(datetime.timezone.utc)
            last = _last_seen_cache.get(user.id)
            if last is None or now - last > _LAST_SEEN_THROTTLE:
                await UserRepository.touch_last_seen(session, user.id)
                _last_seen_cache[user.id] = now

        if user.is_banned:
            if isinstance(event, CallbackQuery):
                await event.answer("🚫 Вы заблокированы.", show_alert=True)
            elif isinstance(event, Message):
                await event.answer("🚫 Вы заблокированы.")
            return None

        data["user"] = user
        return await handler(event, data)
