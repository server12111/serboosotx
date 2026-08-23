import re

# Warn-not-block: a mismatch shows a warning with an explicit "continue anyway" choice,
# because some upstream services accept bare usernames/IDs instead of full URLs.
PATTERNS: dict[str, re.Pattern] = {
    "telegram": re.compile(r"^(https?://)?(t\.me|telegram\.me)/", re.IGNORECASE),
    "instagram": re.compile(r"^(https?://)?(www\.)?instagram\.com/", re.IGNORECASE),
    "tiktok": re.compile(r"^(https?://)?(www\.)?tiktok\.com/", re.IGNORECASE),
    "youtube": re.compile(r"^(https?://)?(www\.)?(youtube\.com|youtu\.be)/", re.IGNORECASE),
    "vk": re.compile(r"^(https?://)?(www\.)?vk\.com/", re.IGNORECASE),
    "twitter": re.compile(r"^(https?://)?(www\.)?(twitter\.com|x\.com)/", re.IGNORECASE),
    "facebook": re.compile(r"^(https?://)?(www\.)?facebook\.com/", re.IGNORECASE),
    "twitch": re.compile(r"^(https?://)?(www\.)?twitch\.tv/", re.IGNORECASE),
    "spotify": re.compile(r"^(https?://)?open\.spotify\.com/", re.IGNORECASE),
    "discord": re.compile(r"^(https?://)?(www\.)?discord\.(gg|com)/", re.IGNORECASE),
    "soundcloud": re.compile(r"^(https?://)?(www\.)?soundcloud\.com/", re.IGNORECASE),
    "reddit": re.compile(r"^(https?://)?(www\.)?reddit\.com/", re.IGNORECASE),
    "pinterest": re.compile(r"^(https?://)?(www\.)?pinterest\.", re.IGNORECASE),
    "linkedin": re.compile(r"^(https?://)?(www\.)?linkedin\.com/", re.IGNORECASE),
    "github": re.compile(r"^(https?://)?(www\.)?github\.com/", re.IGNORECASE),
    "whatsapp": re.compile(r"^(https?://)?(chat\.whatsapp\.com|wa\.me)/", re.IGNORECASE),
    "onlyfans": re.compile(r"^(https?://)?(www\.)?onlyfans\.com/", re.IGNORECASE),
}


def looks_valid(platform: str, link: str) -> bool:
    pattern = PATTERNS.get(platform)
    if pattern is None:
        return True
    return bool(pattern.match(link.strip()))
