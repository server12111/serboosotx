import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    InputMediaVideo,
    Message,
)
from sqlalchemy import select

from ...database.models import User
from ...keyboards.inline import (
    MAX_BROADCAST_MEDIA,
    admin_broadcast_confirm_kb,
    back_kb,
    broadcast_link_button_kb,
    broadcast_media_kb,
    broadcast_skip_button_kb,
    broadcast_skip_text_kb,
)
from ...utils.emoji import pe

logger = logging.getLogger("boosty.admin.broadcast")

router = Router(name="admin_broadcast")

# FSM data is JSON-serialized by RedisStorage, so the draft is kept as a plain dict
# (not a dataclass) — dataclass instances aren't JSON-serializable out of the box.
_EMPTY_DRAFT = {"text": None, "media": [], "button_text": None, "button_url": None}


class AdminStates(StatesGroup):
    broadcast_waiting_text = State()
    broadcast_waiting_media = State()
    broadcast_waiting_button = State()
    broadcast_confirming = State()


async def _get_draft(state: FSMContext) -> dict:
    data = await state.get_data()
    return data.get("draft") or dict(_EMPTY_DRAFT)


async def _save_draft(state: FSMContext, draft: dict) -> None:
    await state.update_data(draft=draft)


def _draft_reply_markup(draft: dict) -> InlineKeyboardMarkup | None:
    if not draft.get("button_url"):
        return None
    return broadcast_link_button_kb(draft["button_text"], draft["button_url"])


@router.callback_query(F.data == "admin:broadcast:start")
async def cb_broadcast_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminStates.broadcast_waiting_text)
    await _save_draft(state, dict(_EMPTY_DRAFT))
    await callback.message.edit_text(
        pe("📢 Отправьте текст рассылки (поддерживаются премиум-эмодзи, если вставить их прямо в сообщение):"),
        reply_markup=broadcast_skip_text_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.broadcast_waiting_text)
async def on_broadcast_text(message: Message, state: FSMContext) -> None:
    draft = await _get_draft(state)
    draft["text"] = message.html_text or None
    await _save_draft(state, draft)
    await _enter_media_step(message, state, draft)


@router.callback_query(F.data == "admin:broadcast:skip_text", AdminStates.broadcast_waiting_text)
async def cb_skip_text(callback: CallbackQuery, state: FSMContext) -> None:
    draft = await _get_draft(state)
    draft["text"] = None
    await _save_draft(state, draft)
    await callback.answer()
    await _enter_media_step(callback.message, state, draft, edit=True)


async def _enter_media_step(message: Message, state: FSMContext, draft: dict, edit: bool = False) -> None:
    await state.set_state(AdminStates.broadcast_waiting_media)
    text = pe(f"🖼 Пришлите до {MAX_BROADCAST_MEDIA} фото/видео по одному, или нажмите Готово:")
    kb = broadcast_media_kb(len(draft["media"]))
    if edit:
        await message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.message(AdminStates.broadcast_waiting_media, F.photo | F.video)
async def on_broadcast_media(message: Message, state: FSMContext) -> None:
    draft = await _get_draft(state)
    if len(draft["media"]) >= MAX_BROADCAST_MEDIA:
        await message.answer(pe(f"⚠️ Уже добавлено максимум {MAX_BROADCAST_MEDIA}. Нажмите Готово."))
        return

    if message.photo:
        draft["media"].append({"type": "photo", "file_id": message.photo[-1].file_id})
    else:
        draft["media"].append({"type": "video", "file_id": message.video.file_id})
    await _save_draft(state, draft)

    await message.answer(
        pe(f"Добавлено {len(draft['media'])}/{MAX_BROADCAST_MEDIA}."),
        reply_markup=broadcast_media_kb(len(draft["media"])),
    )
    if len(draft["media"]) >= MAX_BROADCAST_MEDIA:
        await _enter_button_step(message, state, draft)


@router.message(AdminStates.broadcast_waiting_media)
async def on_broadcast_media_wrong_type(message: Message) -> None:
    await message.answer(pe("⚠️ Пришлите фото или видео, либо нажмите Готово/Очистить."))


@router.callback_query(F.data == "admin:broadcast:media_clear", AdminStates.broadcast_waiting_media)
async def cb_media_clear(callback: CallbackQuery, state: FSMContext) -> None:
    draft = await _get_draft(state)
    if not draft["media"]:
        await callback.answer("Уже пусто.")
        return
    draft["media"] = []
    await _save_draft(state, draft)
    await callback.message.edit_reply_markup(reply_markup=broadcast_media_kb(0))
    await callback.answer("Очищено.")


@router.callback_query(F.data == "admin:broadcast:media_done", AdminStates.broadcast_waiting_media)
async def cb_media_done(callback: CallbackQuery, state: FSMContext) -> None:
    draft = await _get_draft(state)
    if not draft["text"] and not draft["media"]:
        await callback.answer("Нужен хотя бы текст или одно фото/видео.", show_alert=True)
        return
    await callback.answer()
    await _enter_button_step(callback.message, state, draft, edit=True)


async def _enter_button_step(message: Message, state: FSMContext, draft: dict, edit: bool = False) -> None:
    await state.set_state(AdminStates.broadcast_waiting_button)
    text = pe(
        "🔘 Добавить кнопку под сообщением? Пришлите в формате:\nТекст кнопки | https://ссылка\nили нажмите Пропустить."
    )
    kb = broadcast_skip_button_kb()
    if edit:
        await message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.message(AdminStates.broadcast_waiting_button)
async def on_broadcast_button(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if "|" not in raw:
        await message.answer(pe("⚠️ Формат: Текст кнопки | https://ссылка"))
        return
    label, url = (part.strip() for part in raw.split("|", 1))
    if not label or not url.startswith(("http://", "https://")):
        await message.answer(pe("⚠️ Ссылка должна начинаться с http:// или https://"))
        return

    draft = await _get_draft(state)
    draft["button_text"] = label[:64]
    draft["button_url"] = url
    await _save_draft(state, draft)
    await _enter_confirm_step(message, state, draft)


@router.callback_query(F.data == "admin:broadcast:skip_button", AdminStates.broadcast_waiting_button)
async def cb_skip_button(callback: CallbackQuery, state: FSMContext) -> None:
    draft = await _get_draft(state)
    await callback.answer()
    await _enter_confirm_step(callback.message, state, draft, edit=True)


async def _enter_confirm_step(message: Message, state: FSMContext, draft: dict, edit: bool = False) -> None:
    await state.set_state(AdminStates.broadcast_confirming)
    summary = (
        f"🧾 Проверьте рассылку:\n\n"
        f"📝 Текст: {'есть' if draft['text'] else 'нет'}\n"
        f"🖼 Медиа: {len(draft['media'])}\n"
        f"🔘 Кнопка: {draft['button_text'] or 'нет'}"
    )
    if edit:
        await message.edit_text(pe(summary), reply_markup=admin_broadcast_confirm_kb(), parse_mode="HTML")
    else:
        await message.answer(pe(summary), reply_markup=admin_broadcast_confirm_kb(), parse_mode="HTML")

    try:
        await _deliver(message.bot, message.chat.id, draft, _draft_reply_markup(draft))
    except Exception:
        logger.exception("broadcast preview failed to render")


async def _deliver(bot: Bot, chat_id: int, draft: dict, reply_markup: InlineKeyboardMarkup | None) -> None:
    media = draft["media"]
    text = draft["text"]

    if not media:
        await bot.send_message(chat_id, text or "​", parse_mode="HTML", reply_markup=reply_markup)
        return

    if len(media) == 1:
        item = media[0]
        if item["type"] == "photo":
            await bot.send_photo(chat_id, item["file_id"], caption=text, parse_mode="HTML", reply_markup=reply_markup)
        else:
            await bot.send_video(chat_id, item["file_id"], caption=text, parse_mode="HTML", reply_markup=reply_markup)
        return

    # sendMediaGroup does not support reply_markup at all — a Telegram platform
    # limitation, not something aiogram lets us work around. The caption goes on the
    # first item; a requested button is sent as a short follow-up message instead.
    media_group = []
    for i, item in enumerate(media):
        cls = InputMediaPhoto if item["type"] == "photo" else InputMediaVideo
        kwargs = {"media": item["file_id"]}
        if i == 0 and text:
            kwargs["caption"] = text
            kwargs["parse_mode"] = "HTML"
        media_group.append(cls(**kwargs))
    await bot.send_media_group(chat_id, media_group)
    if reply_markup:
        await bot.send_message(chat_id, draft["button_text"] or "👇", reply_markup=reply_markup)


@router.callback_query(F.data == "admin:broadcast:cancel")
async def cb_broadcast_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text(pe("❌ Рассылка отменена."), reply_markup=back_kb("admin:panel"))
    await callback.answer()


@router.callback_query(F.data == "admin:broadcast:confirm", AdminStates.broadcast_confirming)
async def cb_broadcast_confirm(callback: CallbackQuery, state: FSMContext, session_factory, bot: Bot) -> None:
    draft = await _get_draft(state)
    await state.clear()

    await callback.message.edit_text(pe("📢 Рассылка запущена…"))
    await callback.answer()

    reply_markup = _draft_reply_markup(draft)

    async with session_factory() as session:
        tg_ids = (await session.execute(select(User.tg_id).where(User.is_banned.is_(False)))).scalars().all()

    sent, failed = 0, 0
    for tg_id in tg_ids:
        try:
            await _deliver(bot, tg_id, draft, reply_markup)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)  # ~20 msg/s, under Telegram's broadcast rate limits

    await bot.send_message(
        callback.from_user.id, pe(f"✅ Рассылка завершена: отправлено {sent}, ошибок {failed}."), parse_mode="HTML"
    )
