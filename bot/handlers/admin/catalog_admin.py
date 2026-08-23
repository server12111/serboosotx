from aiogram import F, Router
from aiogram.types import CallbackQuery

from ...database.repositories.admin_actions import AdminActionRepository
from ...database.repositories.settings import SettingsRepository
from ...keyboards.inline import back_kb
from ...services import catalog_sync
from ...services.icheatbot import IcheatbotClient, IcheatbotError
from ...utils.emoji import pe

router = Router(name="admin_catalog")


@router.callback_query(F.data == "admin:catalog:resync")
async def cb_catalog_resync(callback: CallbackQuery, session_factory, api_client: IcheatbotClient) -> None:
    await callback.answer("🔄 Синхронизация запущена…")
    try:
        stats = await catalog_sync.run_once(session_factory, api_client)
    except IcheatbotError as e:
        await callback.message.edit_text(
            pe(f"❌ Ошибка синхронизации: {e}"), reply_markup=back_kb("admin:panel", "◀️ Назад")
        )
        return

    async with session_factory() as session:
        await AdminActionRepository.log(session, callback.from_user.id, "catalog_resync", payload=stats)
        last_sync = await SettingsRepository.get(session, "catalog_last_sync_at")

    text = (
        f"✅ Каталог синхронизирован.\n\n"
        f"📦 Услуг получено: {stats['total_seen']}\n"
        f"🗑 Деактивировано: {stats['deactivated']}\n"
        f"🕓 {last_sync}"
    )
    await callback.message.edit_text(pe(text), reply_markup=back_kb("admin:panel", "◀️ Назад"), parse_mode="HTML")
