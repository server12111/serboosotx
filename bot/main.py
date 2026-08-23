import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import ErrorEvent, Update
from redis.asyncio import Redis

from .config import config
from .database.engine import async_session_factory
from .database.repositories.settings import SettingsRepository
from .handlers import setup_routers
from .middlewares.admin import AdminMiddleware
from .middlewares.subscription_gate import SubscriptionGateMiddleware
from .middlewares.throttling import ThrottlingMiddleware
from .middlewares.user import UserMiddleware
from .services import catalog_sync, invoice_reconciler, order_poller
from .services.icheatbot import IcheatbotClient

logger = logging.getLogger("boosty.main")


async def _seed_default_settings() -> None:
    async with async_session_factory() as session:
        await SettingsRepository.set_if_absent(session, "markup_percent", str(config.DEFAULT_MARKUP_PERCENT))
        await SettingsRepository.set_if_absent(
            session, "catalog_sync_interval_sec", str(config.CATALOG_SYNC_INTERVAL_SEC)
        )
        await SettingsRepository.set_if_absent(
            session, "order_poll_interval_sec", str(config.ORDER_POLL_INTERVAL_SEC)
        )
        await SettingsRepository.set_if_absent(
            session, "invoice_poll_interval_sec", str(config.INVOICE_POLL_INTERVAL_SEC)
        )


async def main() -> None:
    await _seed_default_settings()

    redis = Redis.from_url(config.REDIS_URL)
    storage = RedisStorage(redis)

    bot = Bot(token=config.BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher(storage=storage)

    api_client = IcheatbotClient(config.ICHEATBOT_API_KEY, config.ICHEATBOT_BASE_URL)

    dp["session_factory"] = async_session_factory
    dp["api_client"] = api_client
    dp["redis"] = redis

    user_router, admin_router = setup_routers()
    admin_router.message.middleware(AdminMiddleware(config.ADMIN_IDS))
    admin_router.callback_query.middleware(AdminMiddleware(config.ADMIN_IDS))

    # Subscription gate is scoped to user_router only — admins must always retain
    # access to the admin panel regardless of their own channel memberships.
    user_router.message.middleware(SubscriptionGateMiddleware(async_session_factory, redis))
    user_router.callback_query.middleware(SubscriptionGateMiddleware(async_session_factory, redis))

    dp.message.middleware(ThrottlingMiddleware(redis))
    dp.callback_query.middleware(ThrottlingMiddleware(redis))
    dp.message.middleware(UserMiddleware(async_session_factory))
    dp.callback_query.middleware(UserMiddleware(async_session_factory))

    dp.include_router(user_router)
    dp.include_router(admin_router)

    @dp.errors()
    async def on_error(event: ErrorEvent) -> bool:
        update: Update = event.update

        # Harmless Telegram quirk: editing a message with content identical to what's
        # already shown (e.g. double-tapping a button that doesn't change anything)
        # raises this instead of being a no-op. Not a real error — don't alarm the
        # user or spam the log for it.
        if (
            isinstance(event.exception, TelegramBadRequest)
            and "message is not modified" in str(event.exception)
        ):
            if update.callback_query:
                try:
                    await update.callback_query.answer()
                except Exception:
                    pass
            return True

        logger.exception("unhandled error while processing update %s", update, exc_info=event.exception)
        try:
            if update.callback_query:
                await update.callback_query.answer("Произошла ошибка, попробуйте ещё раз.", show_alert=True)
            elif update.message:
                await update.message.answer("⚠️ Произошла ошибка, попробуйте ещё раз.")
        except Exception:
            pass
        return True

    background_tasks = [
        asyncio.create_task(
            catalog_sync.loop(async_session_factory, api_client, config.CATALOG_SYNC_INTERVAL_SEC)
        ),
        asyncio.create_task(
            order_poller.loop(async_session_factory, api_client, bot, config.ORDER_POLL_INTERVAL_SEC)
        ),
        asyncio.create_task(
            invoice_reconciler.loop(
                async_session_factory, config.CRYPTOBOT_TOKEN, bot, storage, config.INVOICE_POLL_INTERVAL_SEC
            )
        ),
    ]

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        for task in background_tasks:
            task.cancel()
        await asyncio.gather(*background_tasks, return_exceptions=True)
        await bot.session.close()
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
