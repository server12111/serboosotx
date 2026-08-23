import logging
from typing import Any, Awaitable, Callable

from aiogram import Bot, BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..database.models import RequiredChannel
from ..database.repositories.required_channels import RequiredChannelRepository
from ..keyboards.inline import subscription_gate_kb
from ..utils.emoji import pe

logger = logging.getLogger("boosty.middlewares.subscription_gate")

OK_CACHE_TTL = 300  # only cache the *positive* result — a still-missing subscription
# should be re-checked on the user's very next tap, not force them to wait out a TTL.

_MEMBER_STATUSES = ("member", "administrator", "creator")


class SubscriptionGateMiddleware(BaseMiddleware):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], redis: Redis):
        self._session_factory = session_factory
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

        # the "I've subscribed, check again" button performs its own fresh check —
        # let it through unconditionally so it can never be blocked by itself.
        if isinstance(event, CallbackQuery) and event.data == "subgate:check":
            return await handler(event, data)

        cache_key = f"subgate_ok:{tg_user.id}"
        if await self._redis.get(cache_key):
            return await handler(event, data)

        async with self._session_factory() as session:
            channels = await RequiredChannelRepository.list_active(session)
        if not channels:
            return await handler(event, data)

        bot: Bot = data["bot"]
        missing = await find_missing(bot, channels, tg_user.id)

        if not missing:
            await self._redis.set(cache_key, "1", ex=OK_CACHE_TTL)
            return await handler(event, data)

        text = pe("🔒 Чтобы пользоваться ботом, подпишитесь на каналы:")
        kb = subscription_gate_kb(missing)
        if isinstance(event, CallbackQuery):
            await event.answer()
            try:
                await event.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
            except Exception:
                await event.message.answer(text, reply_markup=kb, parse_mode="HTML")
        elif isinstance(event, Message):
            await event.answer(text, reply_markup=kb, parse_mode="HTML")
        return None


async def find_missing(bot: Bot, channels: list[RequiredChannel], user_id: int) -> list[RequiredChannel]:
    missing = []
    for channel in channels:
        try:
            member = await bot.get_chat_member(channel.chat_id, user_id)
            if member.status not in _MEMBER_STATUSES:
                missing.append(channel)
        except Exception:
            # Fail open per-channel: if we can't verify (e.g. the bot lost admin
            # rights in that channel after it was added), don't brick the whole bot
            # over one misconfigured entry — log it so an admin notices.
            logger.warning("could not verify membership in channel %s (chat_id=%s)", channel.username, channel.chat_id)
    return missing
