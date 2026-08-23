from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from ..config import config
from ..database.models import User
from ..database.repositories.settings import SettingsRepository
from ..database.repositories.transactions import LedgerRepository
from ..database.repositories.users import UserRepository
from ..keyboards.inline import legal_doc_kb, profile_help_kb, profile_kb, profile_referral_kb
from ..utils.emoji import pe
from ..utils.formatting import fmt_rub
from ..utils.legal import PRIVACY_POLICY, USER_AGREEMENT

router = Router(name="profile")


@router.callback_query(F.data == "profile:menu")
async def cb_profile_menu(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    # Cancel buttons from balance top-up etc. route here — clear any stale FSM state.
    await state.clear()
    text = f"👤 Профиль\n\n💵 Баланс: {fmt_rub(user.balance)}"
    await callback.message.edit_text(pe(text), reply_markup=profile_kb(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "profile:referral")
async def cb_profile_referral(callback: CallbackQuery, user: User, session_factory, bot: Bot) -> None:
    async with session_factory() as session:
        referred_count = await UserRepository.count_referrals(session, user.id)
        earned = await LedgerRepository.sum_by_type(session, user.id, "referral_bonus")
        referral_percent = await SettingsRepository.get_decimal(
            session, "referral_percent", config.DEFAULT_REFERRAL_PERCENT
        )

    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{user.tg_id}"

    text = (
        f"👥 Реферальная программа\n\n"
        f"Приглашайте друзей и получайте {referral_percent}% от суммы каждого их пополнения баланса — навсегда.\n\n"
        f"🔗 Ваша ссылка:\n{link}\n\n"
        f"👤 Приглашено: {referred_count}\n"
        f"💰 Заработано: {fmt_rub(earned)}"
    )
    await callback.message.edit_text(pe(text), reply_markup=profile_referral_kb(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "profile:help")
async def cb_profile_help(callback: CallbackQuery, session_factory) -> None:
    async with session_factory() as session:
        support_username = await SettingsRepository.get(session, "support_username") or config.SUPPORT_USERNAME
        agreement_url = await SettingsRepository.get(session, "legal_agreement_url")
        privacy_url = await SettingsRepository.get(session, "legal_privacy_url")

    text = "🆘 Помощь\n\nЗдесь можно ознакомиться с условиями использования сервиса или связаться с поддержкой."
    kb = profile_help_kb(support_username, agreement_url, privacy_url)
    await callback.message.edit_text(pe(text), reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "profile:help:agreement")
async def cb_help_agreement(callback: CallbackQuery) -> None:
    await callback.message.edit_text(pe(USER_AGREEMENT), reply_markup=legal_doc_kb(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "profile:help:privacy")
async def cb_help_privacy(callback: CallbackQuery) -> None:
    await callback.message.edit_text(pe(PRIVACY_POLICY), reply_markup=legal_doc_kb(), parse_mode="HTML")
    await callback.answer()
