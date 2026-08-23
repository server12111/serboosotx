"""Derives a stable `platform` slug from the upstream API's free-text category/name
fields, since the real taxonomy is unknown until the catalog is synced against a real
API key. Classification is a best-effort keyword match — unmatched services fall back
to "other" rather than being dropped, so the full catalog is always represented."""

PLATFORM_KEYWORDS: dict[str, list[str]] = {
    "telegram": ["telegram", "тг", " tg "],
    "instagram": ["instagram", "инстаграм", "инст ", "ig "],
    "tiktok": ["tiktok", "тикток", "тик ток"],
    "youtube": ["youtube", "ютуб", "юту6"],
    "vk": ["vkontakte", "vk.com", " vk ", "вконтакте", "вк "],
    "twitter": ["twitter", "твиттер", " x.com", " x "],
    "facebook": ["facebook", "фейсбук", " fb "],
    "twitch": ["twitch", "твич"],
    "spotify": ["spotify", "спотифай"],
    "discord": ["discord", "дискорд"],
    "soundcloud": ["soundcloud", "саундклауд"],
    "reddit": ["reddit", "реддит"],
    "pinterest": ["pinterest", "пинтерест"],
    "linkedin": ["linkedin", "линкедин"],
    "github": ["github", "гитхаб"],
    "whatsapp": ["whatsapp", "ватсап", "вотсап"],
    "onlyfans": ["onlyfans"],
    "kick": ["kick"],
    "threads": ["threads"],
    "rutube": ["rutube", "рутуб"],
    "yandex": ["yandex", "яндекс"],
    "max": ["maxmessanger", "max мессенджер", "макс мессенджер"],
    "steam": ["steam", "стим"],
    "applemusic": ["apple music", "applemusic", "эпл мьюзик"],
    "shazam": ["shazam", "шазам"],
    "wibes": ["wibes"],
    "website": ["website", "сайт", "traffic", "трафик", "coinmarketcap"],
}

PLATFORM_LABELS: dict[str, str] = {
    "telegram": "✈️ Telegram",
    "instagram": "📷 Instagram",
    "tiktok": "🎬 TikTok",
    "youtube": "📹 YouTube",
    "vk": "🔵 ВКонтакте",
    "twitter": "🐦 Twitter / X",
    "facebook": "📘 Facebook",
    "twitch": "🟣 Twitch",
    "spotify": "🎧 Spotify",
    "discord": "🕹 Discord",
    "soundcloud": "🔊 SoundCloud",
    "reddit": "👽 Reddit",
    "pinterest": "📌 Pinterest",
    "linkedin": "💼 LinkedIn",
    "github": "🐙 GitHub",
    "whatsapp": "💚 WhatsApp",
    "onlyfans": "🔞 OnlyFans",
    "kick": "🥊 Kick",
    "threads": "🧵 Threads",
    "rutube": "📺 Rutube",
    "yandex": "🟨 Яндекс",
    "max": "🅼 MAX",
    "steam": "🎮 Steam",
    "applemusic": "🎵 Apple Music",
    "shazam": "🎙 Shazam",
    "wibes": "📱 Wibes",
    "website": "🌐 Сайты",
    "other": "🗂 Другое",
}


def classify(category_raw: str | None, name: str) -> str:
    haystack = f"{category_raw or ''} {name}".lower()
    for platform, keywords in PLATFORM_KEYWORDS.items():
        if any(keyword in haystack for keyword in keywords):
            return platform
    return "other"


def label_for(platform: str) -> str:
    return PLATFORM_LABELS.get(platform, PLATFORM_LABELS["other"])


# Explicit display order, per product decision — everything else falls back to
# descending service count (busier categories surface first) then alphabetical.
PLATFORM_PRIORITY: list[str] = [
    "telegram",
    "facebook",
    "instagram",
    "youtube",
    "tiktok",
    "pinterest",
    "max",
    "twitter",
    "twitch",
    "threads",
    "vk",
    "whatsapp",
]
_PRIORITY_INDEX = {slug: i for i, slug in enumerate(PLATFORM_PRIORITY)}


def sort_platforms(platforms: list[tuple[str, int]]) -> list[tuple[str, int]]:
    def key(item: tuple[str, int]) -> tuple[int, int, str]:
        slug, count = item
        priority = _PRIORITY_INDEX.get(slug, len(PLATFORM_PRIORITY))
        return (priority, -count, slug)

    return sorted(platforms, key=key)
