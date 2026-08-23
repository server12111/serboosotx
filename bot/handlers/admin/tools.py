"""Admin-only utility: harvest custom-emoji document ids from a message so new glyphs
can be added to bot/utils/emoji.py's EMOJI_MAP. Real ids can't be invented — they must
come from a real Telegram client, so this is the practical way to collect them: send or
forward a message containing the desired custom emoji (from a Premium account) to the
bot and it replies with each glyph's document id."""
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from ...utils.emoji import pe

router = Router(name="admin_tools")


@router.message(Command("emojiid"))
async def cmd_emoji_id_hint(message: Message) -> None:
    await message.answer(
        pe("🧰 Отправьте (или перешлите) сообщение с нужными кастомными эмодзи следующим сообщением.")
    )


@router.message(F.entities)
async def on_message_with_entities(message: Message) -> None:
    custom = [e for e in (message.entities or []) if e.type == "custom_emoji"]
    if not custom:
        return
    lines = ["🧰 Найдены custom emoji:"]
    for entity in custom:
        glyph = message.text[entity.offset : entity.offset + entity.length]
        lines.append(f"{glyph} → {entity.custom_emoji_id}")
    await message.answer("\n".join(lines))
