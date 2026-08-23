"""Derives a stable `service_type` bucket (followers/views/reactions/...) from the
upstream API's free-text category/type/name fields — same best-effort keyword-match
approach as platform_map.py, and for the same reason: the real taxonomy varies per
service row and is only knowable by inspecting real synced data."""

TYPE_KEYWORDS: dict[str, list[str]] = {
    "followers": ["подписчик", "подписка", "участник", "follower", "member", "subscriber"],
    "views": ["просмотр", "зрител", "охват", "view", "impression"],
    "reactions": ["реакци", "лайк", "дизлайк", "like", "reaction", "upvote", "downvote"],
    "comments": ["коммент", "comment"],
    "shares": ["репост", "пересыл", "share", "retweet", "ретвит", "forward"],
    "votes": ["голос", "опрос", "vote", "poll"],
    "listens": ["прослуш", "стрим", "listen", "play", "stream"],
    "premium": ["премиум", "premium", "gift", "подарок", "звезд", "stars"],
    "boosts": ["буст", "boost"],
    "saves": ["сохранен", "save", "скачива", "download"],
    "traffic": ["трафик", "traffic"],
    "reports": ["жалоб", "complaint", "report"],
}

TYPE_LABELS: dict[str, str] = {
    "followers": "👥 Подписчики",
    "views": "👁 Просмотры",
    "reactions": "❤️ Реакции",
    "comments": "💬 Комментарии",
    "shares": "🔁 Репосты",
    "votes": "🗳 Голоса/Опросы",
    "listens": "🎧 Прослушивания",
    "premium": "🎁 Премиум/Подарки",
    "boosts": "🚀 Бусты",
    "saves": "💾 Сохранения",
    "traffic": "🌐 Трафик",
    "reports": "🚩 Жалобы",
    "other": "🗂 Другое",
}


def classify(category_raw: str | None, type_raw: str | None, name: str) -> str:
    haystack = f"{category_raw or ''} {type_raw or ''} {name}".lower()
    for service_type, keywords in TYPE_KEYWORDS.items():
        if any(keyword in haystack for keyword in keywords):
            return service_type
    return "other"


def label_for(service_type: str) -> str:
    return TYPE_LABELS.get(service_type, TYPE_LABELS["other"])
