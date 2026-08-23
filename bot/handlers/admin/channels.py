from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ...database.repositories.admin_actions import AdminActionRepository
from ...database.repositories.required_channels import RequiredChannelRepository
from ...keyboards.inline import admin_channels_list_kb, back_kb
from ...utils.emoji import pe
from ...utils.pagination import paginate

router = Router(name="admin_channels")

PAGE_SIZE = 8


class AdminStates(StatesGroup):
    channel_waiting_username = State()


@router.callback_query(F.data.startswith("admin:channels:list:"))
async def cb_channels_list(callback: CallbackQuery, session_factory, state: FSMContext) -> None:
    await state.clear()
    page_num = int(callback.data.split(":")[-1])
    async with session_factory() as session:
        all_channels = await RequiredChannelRepository.list_active(session)

    page = paginate(page_num, len(all_channels), PAGE_SIZE)
    chunk = all_channels[page.offset : page.offset + page.limit]

    text = (
        "📢 Обязательные каналы для подписки\n\n"
        "Пользователи не смогут пользоваться ботом, пока не подпишутся на все каналы ниже.\n"
        "⚠️ Бот должен быть администратором канала, иначе проверка подписки не сработает."
        if all_channels
        else "📢 Обязательных каналов пока нет — бот доступен всем без ограничений."
    )
    await callback.message.edit_text(pe(text), reply_markup=admin_channels_list_kb(chunk, page), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin:channels:add")
async def cb_channel_add_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminStates.channel_waiting_username)
    await callback.message.edit_text(
        pe("📢 Отправьте username канала (без @). Бот уже должен быть добавлен туда администратором:"),
        reply_markup=back_kb("admin:channels:list:0", "❌ Отмена"),
    )
    await callback.answer()


@router.message(AdminStates.channel_waiting_username)
async def on_channel_username(message: Message, state: FSMContext, session_factory, bot: Bot) -> None:
    username = (message.text or "").strip().lstrip("@")
    if not username:
        await message.answer(pe("⚠️ Отправьте непустой username."))
        return

    try:
        chat = await bot.get_chat(f"@{username}")
    except Exception as e:
        await message.answer(pe(f"❌ Не удалось найти канал @{username}: {e}"))
        return

    # Verify the bot can actually query membership before saving — getChatMember on a
    # channel requires the bot to be an admin there; catching this now (instead of
    # letting the gate silently fail-open for everyone later) is the whole point.
    try:
        await bot.get_chat_member(chat.id, message.from_user.id)
    except Exception:
        await message.answer(
            pe(
                f"⚠️ Бот не может проверять подписчиков канала @{username} — "
                f"добавьте бота туда администратором (с правом просмотра участников) и попробуйте снова."
            )
        )
        return

    async with session_factory() as session:
        await RequiredChannelRepository.add(
            session, chat_id=chat.id, username=username, title=chat.title or username, added_by=message.from_user.id
        )
        await AdminActionRepository.log(
            session, message.from_user.id, "channel_add", payload={"username": username, "chat_id": chat.id}
        )
    await state.clear()
    await message.answer(pe(f"✅ Канал @{username} добавлен в обязательные."), reply_markup=back_kb("admin:channels:list:0", "◀️ Назад"))


@router.callback_query(F.data.startswith("admin:channels:remove:"))
async def cb_channel_remove(callback: CallbackQuery, session_factory) -> None:
    channel_id = int(callback.data.split(":")[-1])
    async with session_factory() as session:
        channel = await RequiredChannelRepository.get_by_id(session, channel_id)
        if channel is None:
            await callback.answer("Канал не найден.", show_alert=True)
            return
        await RequiredChannelRepository.deactivate(session, channel_id)
        await AdminActionRepository.log(
            session, callback.from_user.id, "channel_remove", payload={"username": channel.username}
        )
    await callback.answer(f"Канал @{channel.username} удалён из обязательных.", show_alert=True)
    await cb_channels_list_refresh(callback, session_factory)


async def cb_channels_list_refresh(callback: CallbackQuery, session_factory) -> None:
    async with session_factory() as session:
        all_channels = await RequiredChannelRepository.list_active(session)
    page = paginate(0, len(all_channels), PAGE_SIZE)
    chunk = all_channels[page.offset : page.offset + page.limit]
    text = (
        "📢 Обязательные каналы для подписки"
        if all_channels
        else "📢 Обязательных каналов пока нет — бот доступен всем без ограничений."
    )
    await callback.message.edit_text(pe(text), reply_markup=admin_channels_list_kb(chunk, page), parse_mode="HTML")
