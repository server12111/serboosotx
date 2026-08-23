from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..config import config
from ..database.repositories.services import ServiceRepository
from ..database.repositories.settings import SettingsRepository
from ..keyboards.inline import (
    back_kb,
    categories_kb,
    platform_types_kb,
    platforms_kb,
    search_results_kb,
    service_detail_kb,
    services_list_kb,
)
from ..services import platform_map, service_type_map
from ..services.pricing import compute_price
from ..utils.emoji import pe
from ..utils.formatting import fmt_rub
from ..utils.pagination import paginate
from ..utils.slug import short_hash

router = Router(name="catalog")


class SearchStates(StatesGroup):
    waiting_query = State()


SEARCH_PAGE_SIZE = 10
PLATFORMS_PAGE_SIZE = 16  # 4 per row x 4 rows


@router.callback_query(F.data.startswith("catalog:platforms:"))
async def cb_platforms(
    callback: CallbackQuery, state: FSMContext, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    # Reset any leftover FSM state (e.g. an abandoned search) — this button is the
    # universal "back to catalog root" target from several sub-flows.
    await state.clear()
    page_num = int(callback.data.split(":")[-1])
    async with session_factory() as session:
        platforms = await ServiceRepository.list_platforms(session)

    platforms = platform_map.sort_platforms(platforms)
    page = paginate(page_num, len(platforms), PLATFORMS_PAGE_SIZE)
    chunk = platforms[page.offset : page.offset + page.limit]

    if not chunk:
        await callback.answer("Каталог пока пуст, загляните позже.", show_alert=True)
        return

    await callback.message.edit_text(
        pe("🗂 Выберите платформу:"), reply_markup=platforms_kb(chunk, page), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("platform:open:"))
async def cb_platform_open(callback: CallbackQuery, session_factory: async_sessionmaker[AsyncSession]) -> None:
    slug = callback.data.split(":")[2]

    async with session_factory() as session:
        types = await ServiceRepository.list_types_for_platform(session, slug)

    if not types:
        await callback.answer("В этой категории пока нет услуг.", show_alert=True)
        return

    label = platform_map.label_for(slug)
    await callback.message.edit_text(
        pe(f"{label}\nВыберите категорию услуг:"),
        reply_markup=platform_types_kb(slug, types),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("platform:type:"))
async def cb_platform_type_open(callback: CallbackQuery, session_factory: async_sessionmaker[AsyncSession]) -> None:
    _, _, slug, service_type, page_raw = callback.data.split(":")
    page_num = int(page_raw)

    async with session_factory() as session:
        categories = await ServiceRepository.list_categories_for_platform_type(session, slug, service_type)

    platform_label = platform_map.label_for(slug)
    type_label = service_type_map.label_for(service_type)

    # Real upstream sub-categories exist (e.g. "by country" / "premium" / "bots"
    # within followers) - show a picker for them instead of one long flat list. With
    # 0 or 1 distinct categories a picker would be pointless friction, so skip to the
    # flat services list in that case.
    if len(categories) > 1:
        entries = [(cat, count, short_hash(cat)) for cat, count in categories]
        await callback.message.edit_text(
            pe(f"{platform_label} · {type_label}\nВыберите категорию:"),
            reply_markup=categories_kb(slug, service_type, entries),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    async with session_factory() as session:
        total = await ServiceRepository.count_by_platform_and_type(session, slug, service_type)
        page = paginate(page_num, total)
        services = await ServiceRepository.list_by_platform_and_type(session, slug, service_type, page.offset, page.limit)

    if not services:
        await callback.answer("В этой категории пока нет услуг.", show_alert=True)
        return

    await callback.message.edit_text(
        pe(f"{platform_label} · {type_label}\nВыберите услугу:"),
        reply_markup=services_list_kb(services, slug, service_type, None, page),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("platform:cat:"))
async def cb_platform_category_open(callback: CallbackQuery, session_factory: async_sessionmaker[AsyncSession]) -> None:
    _, _, slug, service_type, slug_hash, page_raw = callback.data.split(":")
    page_num = int(page_raw)

    async with session_factory() as session:
        categories = await ServiceRepository.list_categories_for_platform_type(session, slug, service_type)
        category_raw = next((cat for cat, _ in categories if short_hash(cat) == slug_hash), None)
        if category_raw is None:
            await callback.answer("Категория больше недоступна, попробуйте заново.", show_alert=True)
            return

        total = await ServiceRepository.count_by_platform_type_category(session, slug, service_type, category_raw)
        page = paginate(page_num, total)
        services = await ServiceRepository.list_by_platform_type_category(
            session, slug, service_type, category_raw, page.offset, page.limit
        )

    if not services:
        await callback.answer("В этой категории пока нет услуг.", show_alert=True)
        return

    await callback.message.edit_text(
        pe(f"{category_raw}\nВыберите услугу:"),
        reply_markup=services_list_kb(services, slug, service_type, slug_hash, page),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("service:open:"))
async def cb_service_open(callback: CallbackQuery, session_factory: async_sessionmaker[AsyncSession]) -> None:
    service_id = int(callback.data.split(":")[-1])
    async with session_factory() as session:
        service = await ServiceRepository.get_by_id(session, service_id)
        if service is None or not service.is_active:
            await callback.answer("Услуга больше недоступна.", show_alert=True)
            return
        markup = await SettingsRepository.get_decimal(session, "markup_percent", config.DEFAULT_MARKUP_PERCENT)

    price_per_1000 = compute_price(service.rate_rub, 1000, markup)
    badges = []
    if service.refill:
        badges.append("🔄 реролл")
    if service.cancel:
        badges.append("❌ отмена")
    if service.dripfeed:
        badges.append("💧 дрип-фид")
    badges_text = f"\n{' · '.join(badges)}" if badges else ""

    text = (
        f"🗂 {service.name}\n\n"
        f"💵 Цена за 1000: {fmt_rub(price_per_1000)}\n"
        f"📉 Мин: {service.min_quantity}  📈 Макс: {service.max_quantity}"
        f"{badges_text}"
    )
    await callback.message.edit_text(pe(text), reply_markup=service_detail_kb(service), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "catalog:search:start")
async def cb_search_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SearchStates.waiting_query)
    await callback.message.edit_text(
        pe("🔎 Введите название услуги, ключевое слово или платформу (например «telegram» или «яндекс»):"),
        reply_markup=back_kb("catalog:platforms:0", "❌ Отмена"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(SearchStates.waiting_query)
async def on_search_query(
    message: Message, state: FSMContext, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    query = (message.text or "").strip()
    if len(query) < 2:
        await message.answer(pe("⚠️ Введите минимум 2 символа."))
        return

    # If the query itself names a platform (in Russian or English — platform_map's
    # keyword lists cover both), jump straight to that platform's categories instead
    # of a flat text search — this is what people actually mean typing "telegram" or
    # "телеграм", and plain name/category matching alone won't find it since neither
    # word necessarily appears verbatim in a service's name.
    matched_platform = platform_map.classify(query, "")
    if matched_platform != "other":
        async with session_factory() as session:
            types = await ServiceRepository.list_types_for_platform(session, matched_platform)
        if types:
            await state.clear()
            label = platform_map.label_for(matched_platform)
            await message.answer(
                pe(f"{label}\nВыберите категорию услуг:"),
                reply_markup=platform_types_kb(matched_platform, types),
                parse_mode="HTML",
            )
            return

    await state.update_data(search_query=query)
    await _show_search_page(message, session_factory, query, 0)


@router.callback_query(F.data.startswith("catalog:search:page:"))
async def cb_search_page(
    callback: CallbackQuery, state: FSMContext, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    page_num = int(callback.data.split(":")[-1])
    data = await state.get_data()
    query = data.get("search_query")
    if not query:
        await callback.answer("Начните поиск заново.", show_alert=True)
        return
    await _show_search_page(callback.message, session_factory, query, page_num, edit=True)
    await callback.answer()


async def _show_search_page(
    message: Message,
    session_factory: async_sessionmaker[AsyncSession],
    query: str,
    page_num: int,
    edit: bool = False,
) -> None:
    async with session_factory() as session:
        total = await ServiceRepository.count_search(session, query)
        page = paginate(page_num, total, SEARCH_PAGE_SIZE)
        services = await ServiceRepository.search_by_name(session, query, page.offset, page.limit)

    if not services:
        text = pe(f"По запросу «{query}» ничего не найдено.")
        kb = back_kb("catalog:search:start", "🔎 Новый поиск")
    else:
        text = pe(f"🔎 Результаты по запросу «{query}»:")
        kb = search_results_kb(services, page)

    if edit:
        await message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=kb, parse_mode="HTML")
