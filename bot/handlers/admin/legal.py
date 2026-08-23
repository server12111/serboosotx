from aiogram import F, Router
from aiogram.types import CallbackQuery

from ...database.repositories.admin_actions import AdminActionRepository
from ...database.repositories.settings import SettingsRepository
from ...keyboards.inline import admin_legal_kb, back_kb
from ...services import telegraph
from ...utils.emoji import pe
from ...utils.legal import (
    BRAND_NAME,
    PRIVACY_POLICY,
    PRIVACY_POLICY_TITLE,
    USER_AGREEMENT,
    USER_AGREEMENT_TITLE,
)

router = Router(name="admin_legal")

AUTHOR_NAME = BRAND_NAME


@router.callback_query(F.data == "admin:legal:show")
async def cb_legal_show(callback: CallbackQuery, session_factory) -> None:
    async with session_factory() as session:
        agreement_url = await SettingsRepository.get(session, "legal_agreement_url")
        privacy_url = await SettingsRepository.get(session, "legal_privacy_url")

    text = (
        "📄 Юридические документы\n\n"
        f"Соглашение: {agreement_url or 'не опубликовано'}\n"
        f"Конфиденциальность: {privacy_url or 'не опубликовано'}\n\n"
        "Текст редактируется в bot/utils/legal.py. После правок нажмите «Опубликовать», "
        "чтобы обновить страницы на Telegra.ph (ссылка останется той же)."
    )
    await callback.message.edit_text(pe(text), reply_markup=admin_legal_kb(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin:legal:publish")
async def cb_legal_publish(callback: CallbackQuery, session_factory) -> None:
    await callback.answer("📄 Публикация…")

    async with session_factory() as session:
        access_token = await SettingsRepository.get(session, "telegraph_access_token")
        if not access_token:
            access_token = await telegraph.create_account("feboost", AUTHOR_NAME)
            await SettingsRepository.set(session, "telegraph_access_token", access_token)

        agreement_path = await SettingsRepository.get(session, "legal_agreement_path")
        privacy_path = await SettingsRepository.get(session, "legal_privacy_path")

        try:
            if agreement_path:
                agreement_url = await telegraph.edit_page(access_token, agreement_path, USER_AGREEMENT_TITLE, AUTHOR_NAME, USER_AGREEMENT)
            else:
                agreement_url, agreement_path = await telegraph.create_page(access_token, USER_AGREEMENT_TITLE, AUTHOR_NAME, USER_AGREEMENT)
                await SettingsRepository.set(session, "legal_agreement_path", agreement_path)
            await SettingsRepository.set(session, "legal_agreement_url", agreement_url)

            if privacy_path:
                privacy_url = await telegraph.edit_page(access_token, privacy_path, PRIVACY_POLICY_TITLE, AUTHOR_NAME, PRIVACY_POLICY)
            else:
                privacy_url, privacy_path = await telegraph.create_page(access_token, PRIVACY_POLICY_TITLE, AUTHOR_NAME, PRIVACY_POLICY)
                await SettingsRepository.set(session, "legal_privacy_path", privacy_path)
            await SettingsRepository.set(session, "legal_privacy_url", privacy_url)
        except telegraph.TelegraphError as e:
            await callback.message.edit_text(pe(f"❌ Ошибка публикации: {e}"), reply_markup=back_kb("admin:legal:show", "◀️ Назад"))
            return

        await AdminActionRepository.log(
            session, callback.from_user.id, "legal_publish", payload={"agreement": agreement_url, "privacy": privacy_url}
        )

    text = f"✅ Опубликовано:\n\n📄 {agreement_url}\n🔒 {privacy_url}"
    await callback.message.edit_text(pe(text), reply_markup=admin_legal_kb(), parse_mode="HTML")
