import hashlib


def short_hash(text: str) -> str:
    """Stable short identifier for embedding arbitrary text in callback_data, which
    Telegram caps at 64 bytes. Content-derived (not positional), so it stays valid
    even if the underlying list's order or membership shifts between catalog syncs."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]
