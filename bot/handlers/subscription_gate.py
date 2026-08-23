from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery
from redis.asyncio import Redis

from ..database.models import User
from ..database.repositories.required_channels import RequiredChannelRepository
from ..keyboards.inline import subscription_gate_kb
from ..middlewares.subscription_gate import OK_CACHE_TTL, find_missing
from ..utils.emoji import pe
from .start import WELCOME_TEXT, menu_kb

router = Router(name="subscription_gate")


@router.callback_query(F.data == "subgate:check")
async def cb_subgate_check(callback: CallbackQuery, user: User, session_factory, bot: Bot, redis: Redis) -> None:
    async with session_factory() as session:
        channels = await RequiredChannelRepository.list_active(session)

    missing = await find_missing(bot, channels, callback.from_user.id) if channels else []

    if missing:
        await callback.answer("Вы ещё не подписались на все каналы.", show_alert=True)
        await callback.message.edit_reply_markup(reply_markup=subscription_gate_kb(missing))
        return

    await redis.set(f"subgate_ok:{callback.from_user.id}", "1", ex=OK_CACHE_TTL)
    await callback.message.edit_text(pe(WELCOME_TEXT), reply_markup=menu_kb(user), parse_mode="HTML")
    await callback.answer("✅ Подписка подтверждена!")
