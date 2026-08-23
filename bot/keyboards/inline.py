"""Button text is plain text — Telegram does NOT parse HTML/markdown in button labels
(unlike message text with parse_mode=HTML), so never wrap it with utils.emoji.pe().
Premium/custom emoji on a button instead goes through the dedicated
icon_custom_emoji_id field: _btn() auto-detects a leading glyph from EMOJI_MAP,
promotes it there, and strips that glyph out of the visible text — otherwise Telegram
renders both the custom icon AND the plain unicode glyph, showing the emoji twice.
"""
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from ..database.models import Order, RequiredChannel, Service, User
from ..services import platform_map, service_type_map
from ..utils.emoji import EMOJI_MAP
from ..utils.pagination import Page
from ..utils.slug import short_hash

_DANGER_WORDS = ("отмена", "отменить", "удал", "бан", "закрыть")
_SUCCESS_WORDS = ("подтверд", "оплат", "продолжить", "готово", "сохранить")

# Longest glyphs first so multi-codepoint emoji (flags, keycaps) match before a
# shorter glyph that happens to be a prefix of them.
_SORTED_GLYPHS = sorted(EMOJI_MAP, key=len, reverse=True)


def _auto_style(text: str) -> str:
    low = text.lower()
    if any(word in low for word in _DANGER_WORDS):
        return "danger"
    if any(word in low for word in _SUCCESS_WORDS):
        return "success"
    return "primary"


def _split_leading_icon(text: str) -> tuple[str | None, str]:
    """Returns (custom_emoji_id, text_with_glyph_stripped) if text starts with a known
    glyph, else (None, text) unchanged."""
    for glyph in _SORTED_GLYPHS:
        if text.startswith(glyph):
            return EMOJI_MAP[glyph], text[len(glyph):].lstrip()
    return None, text


def _btn(
    text: str,
    callback_data: str | None = None,
    url: str | None = None,
    style: str | None = None,
    icon_custom_emoji_id: str | None = None,
) -> InlineKeyboardButton:
    auto_icon, stripped_text = _split_leading_icon(text)
    icon = icon_custom_emoji_id or auto_icon
    display_text = stripped_text if icon else text
    return InlineKeyboardButton(
        text=display_text,
        callback_data=callback_data,
        url=url,
        style=style or _auto_style(text),
        icon_custom_emoji_id=icon,
    )


def _pagination_row(prefix: str, page: Page) -> list[InlineKeyboardButton]:
    row = []
    if page.has_prev:
        row.append(_btn("◀️ Назад", f"{prefix}:{page.page - 1}", style="primary"))
    if page.has_next:
        row.append(_btn("➡️ Далее", f"{prefix}:{page.page + 1}", style="primary"))
    return row


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _btn("🗂 Каталог услуг", "catalog:platforms:0"),
                _btn("💵 Баланс", "balance:quick"),
            ],
            [_btn("👤 Профиль", "profile:menu")],
        ]
    )


def insufficient_funds_kb(missing_amount) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn(f"➕ Пополнить {missing_amount} ₽", f"balance:topup:quick:{missing_amount}", style="success")],
            [_btn("◀️ В меню", "menu:main", style="primary")],
        ]
    )


def balance_quick_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("➕ Пополнить", "balance:topup:start", style="success")],
            [_btn("👤 Профиль", "profile:menu", style="primary")],
            [_btn("◀️ В меню", "menu:main", style="primary")],
        ]
    )


def with_admin_row(kb: InlineKeyboardMarkup) -> InlineKeyboardMarkup:
    kb.inline_keyboard.append([_btn("⚙️ Админ-панель", "admin:panel")])
    return kb


def back_kb(callback_data: str, text: str = "◀️ Назад") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn(text, callback_data, style="primary")]])


def platforms_kb(platforms: list[tuple[str, int]], page: Page) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for slug, count in platforms:
        label = f"{platform_map.label_for(slug)} ({count})"
        row.append(_btn(label, f"platform:open:{slug}:0", style="primary"))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    nav = _pagination_row("catalog:platforms", page)
    if nav:
        rows.append(nav)
    rows.append([_btn("🔎 Поиск", "catalog:search:start", style="success")])
    rows.append([_btn("◀️ В меню", "menu:main", style="primary")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def search_results_kb(services: list[Service], page: Page) -> InlineKeyboardMarkup:
    # The query text itself is kept in FSM state, not in callback_data — Telegram caps
    # callback_data at 64 bytes and a search phrase could easily blow past that.
    rows = [[_btn(s.name[:60], f"service:open:{s.id}", style="primary")] for s in services]
    nav = _pagination_row("catalog:search:page", page)
    if nav:
        rows.append(nav)
    rows.append([_btn("🔎 Новый поиск", "catalog:search:start", style="primary")])
    rows.append([_btn("◀️ К платформам", "catalog:platforms:0", style="primary")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def platform_types_kb(platform: str, types: list[tuple[str, int]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for service_type, count in types:
        label = f"{service_type_map.label_for(service_type)} ({count})"
        row.append(_btn(label, f"platform:type:{platform}:{service_type}:0", style="primary"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([_btn("◀️ К платформам", "catalog:platforms:0", style="primary")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def categories_kb(
    platform: str, service_type: str, categories: list[tuple[str, int, str]]
) -> InlineKeyboardMarkup:
    """categories: list of (category_raw, count, slug) — slug is the short content
    hash used in callback_data since category_raw text itself won't fit reliably."""
    rows = [
        [_btn(f"{label}  ({count})", f"platform:cat:{platform}:{service_type}:{slug}:0", style="primary")]
        for label, count, slug in categories
    ]
    rows.append([_btn("◀️ К категориям услуг", f"platform:open:{platform}:0", style="primary")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def services_list_kb(
    services: list[Service], platform: str, service_type: str, category_slug: str | None, page: Page
) -> InlineKeyboardMarkup:
    rows = [[_btn(s.name[:60], f"service:open:{s.id}", style="primary")] for s in services]
    if category_slug:
        nav = _pagination_row(f"platform:cat:{platform}:{service_type}:{category_slug}", page)
        back_target = f"platform:type:{platform}:{service_type}:0"
    else:
        nav = _pagination_row(f"platform:type:{platform}:{service_type}", page)
        back_target = f"platform:open:{platform}:0"
    if nav:
        rows.append(nav)
    rows.append([_btn("◀️ Назад", back_target, style="primary")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def service_detail_kb(service: Service) -> InlineKeyboardMarkup:
    if service.category_raw:
        back_target = f"platform:cat:{service.platform}:{service.service_type}:{short_hash(service.category_raw)}:0"
    else:
        back_target = f"platform:type:{service.platform}:{service.service_type}:0"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("🚀 Заказать", f"service:order:{service.id}", style="success")],
            [_btn("◀️ Назад", back_target, style="primary")],
        ]
    )


def link_warning_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("Всё равно продолжить", "order:link_continue", style="primary")],
            [_btn("Ввести заново", "order:link_retry", style="danger")],
        ]
    )


def order_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("✅ Подтвердить", "order:confirm", style="success")],
            [_btn("❌ Отмена", "order:cancel", style="danger")],
        ]
    )


def orders_list_kb(orders: list[Order], page: Page) -> InlineKeyboardMarkup:
    status_icon = {
        "pending": "⏳",
        "placed": "🕓",
        "in_progress": "🔷",
        "completed": "✅",
        "partial": "🟡",
        "canceled": "❌",
        "failed": "❌",
        "refunded": "↩️",
    }
    rows = [
        [_btn(f"{status_icon.get(o.status, '•')} #{o.id} — {o.quantity} шт.", f"orders:view:{o.id}", style="primary")]
        for o in orders
    ]
    nav = _pagination_row("orders:list", page)
    if nav:
        rows.append(nav)
    rows.append([_btn("◀️ В меню", "menu:main", style="primary")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def order_detail_kb(order: Order, service: Service) -> InlineKeyboardMarkup:
    # Cancellation is deliberately not exposed here — the upstream cancel endpoint
    # doesn't reliably cancel orders in practice regardless of the service's `cancel`
    # flag, so a button for it would just mislead users into thinking it worked.
    rows = []
    if service.refill and order.status in ("completed", "partial"):
        rows.append([_btn("🔄 Реролл", f"order:refill:{order.id}", style="primary")])
    rows.append([_btn("◀️ К заказам", "orders:list:0", style="primary")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def profile_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("➕ Пополнить", "balance:topup:start", style="success"), _btn("🏷 Мои заказы", "orders:list:0", style="primary")],
            [_btn("🗃 История операций", "balance:history:0", style="primary"), _btn("👥 Рефералка", "profile:referral", style="primary")],
            [_btn("🆘 Помощь", "profile:help", style="primary"), _btn("◀️ В меню", "menu:main", style="primary")],
        ]
    )


def profile_referral_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn("◀️ Назад", "profile:menu", style="primary")]])


def profile_help_kb(
    support_username: str | None, agreement_url: str | None, privacy_url: str | None
) -> InlineKeyboardMarkup:
    agreement_btn = (
        _btn("📄 Соглашение", url=agreement_url, style="primary")
        if agreement_url
        else _btn("📄 Соглашение", "profile:help:agreement", style="primary")
    )
    privacy_btn = (
        _btn("🔒 Конфиденциальность", url=privacy_url, style="primary")
        if privacy_url
        else _btn("🔒 Конфиденциальность", "profile:help:privacy", style="primary")
    )
    rows = [[agreement_btn, privacy_btn]]
    if support_username:
        rows.append([_btn("🆘 Поддержка", url=f"https://t.me/{support_username.lstrip('@')}", style="success")])
    rows.append([_btn("◀️ Назад", "profile:menu", style="primary")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_legal_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("🔄 Опубликовать/обновить", "admin:legal:publish", style="success")],
            [_btn("◀️ Назад", "admin:panel", style="primary")],
        ]
    )


def legal_doc_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn("◀️ Назад", "profile:help", style="primary")]])


def invoice_kb(pay_url: str, invoice_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("💳 Оплатить", url=pay_url, style="success")],
            [_btn("🔄 Проверить оплату", f"balance:invoice:check:{invoice_id}", style="primary")],
            [_btn("◀️ В меню", "menu:main", style="primary")],
        ]
    )


def history_kb(page: Page) -> InlineKeyboardMarkup:
    rows = []
    nav = _pagination_row("balance:history", page)
    if nav:
        rows.append(nav)
    rows.append([_btn("◀️ Назад", "profile:menu", style="primary")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_panel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("📊 Статистика", "admin:stats", style="primary"), _btn("📢 Рассылка", "admin:broadcast:start", style="primary")],
            [_btn("📈 Наценка %", "admin:markup:show", style="primary"), _btn("👤 Пользователь", "admin:user:search", style="primary")],
            [_btn("🆘 Поддержка", "admin:support:show", style="primary"), _btn("📢 Обязат. каналы", "admin:channels:list:0", style="primary")],
            [_btn("📄 Документы", "admin:legal:show", style="primary"), _btn("🔄 Ресинк каталога", "admin:catalog:resync", style="primary")],
            [_btn("◀️ В меню", "menu:main", style="primary")],
        ]
    )


def subscription_gate_kb(channels: list[RequiredChannel]) -> InlineKeyboardMarkup:
    rows = [[_btn(f"📢 {ch.title}", url=f"https://t.me/{ch.username}")] for ch in channels]
    rows.append([_btn("✅ Я подписался", "subgate:check", style="success")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_channels_list_kb(channels: list[RequiredChannel], page: Page) -> InlineKeyboardMarkup:
    rows = [[_btn(f"🗑 {ch.title}", f"admin:channels:remove:{ch.id}", style="danger")] for ch in channels]
    nav = _pagination_row("admin:channels:list", page)
    if nav:
        rows.append(nav)
    rows.append([_btn("➕ Добавить канал", "admin:channels:add", style="success")])
    rows.append([_btn("◀️ Назад", "admin:panel", style="primary")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_support_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("✍ Изменить", "admin:support:set", style="primary")],
            [_btn("◀️ Назад", "admin:panel", style="primary")],
        ]
    )


def admin_markup_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("✍ Изменить", "admin:markup:set", style="primary")],
            [_btn("◀️ Назад", "admin:panel", style="primary")],
        ]
    )


def admin_broadcast_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("✅ Отправить", "admin:broadcast:confirm", style="success")],
            [_btn("❌ Отмена", "admin:broadcast:cancel", style="danger")],
        ]
    )


def broadcast_skip_text_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("⏭ Без текста", "admin:broadcast:skip_text")],
            [_btn("❌ Отмена", "admin:broadcast:cancel", style="danger")],
        ]
    )


MAX_BROADCAST_MEDIA = 5


def broadcast_media_kb(count: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn(f"✅ Готово ({count}/{MAX_BROADCAST_MEDIA})", "admin:broadcast:media_done", style="success")],
            [_btn("🗑 Очистить", "admin:broadcast:media_clear", style="danger")],
            [_btn("❌ Отмена", "admin:broadcast:cancel", style="danger")],
        ]
    )


def broadcast_skip_button_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("⏭ Пропустить", "admin:broadcast:skip_button")],
            [_btn("❌ Отмена", "admin:broadcast:cancel", style="danger")],
        ]
    )


def broadcast_link_button_kb(button_text: str, button_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=button_text, url=button_url)]])


def admin_user_actions_kb(user: User) -> InlineKeyboardMarkup:
    ban_btn = (
        _btn("🙆 Разбанить", f"admin:unban:{user.id}", style="success")
        if user.is_banned
        else _btn("🙅 Забанить", f"admin:ban:{user.id}", style="danger")
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_btn("💵 Изменить баланс", f"admin:balance:adjust:{user.id}", style="primary")],
            [ban_btn],
            [_btn("◀️ Назад", "admin:panel", style="primary")],
        ]
    )
