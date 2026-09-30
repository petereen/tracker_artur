"""Second half of the tenant bot handshake (see app/services/telegram_bots.py).

The tenant admin opens ``t.me/<bot>?start=oyuns-<code>`` from Settings. The
``/start`` arrives through that very bot, so completing it here proves the
ERP holds a live token and the runner polls it.
"""
import asyncio
import html

from aiogram import F, Router
from aiogram.filters import CommandObject, CommandStart
from aiogram.types import Message

from app.services.telegram_bots import HANDSHAKE_PREFIX, complete_handshake_sync

router = Router()

HANDSHAKE_ERRORS = {
    "expired": "⌛ Холболтын кодын хугацаа дууссан. Тохиргоо → Интеграци хэсгээс шинэ холбоос үүсгэнэ үү.",
    "invalid": "❌ Холболтын код буруу эсвэл аль хэдийн ашиглагдсан байна. Тохиргооноос шинэ холбоос авна уу.",
    "not_found": "❌ Энэ бот OYUNS ERP-д холбогдоогүй байна.",
}


@router.message(CommandStart(deep_link=True, magic=F.args.startswith(HANDSHAKE_PREFIX)))
async def cmd_handshake(message: Message, command: CommandObject):
    code = (command.args or "")[len(HANDSHAKE_PREFIX):]
    error, linked_name = await asyncio.to_thread(complete_handshake_sync, message.bot.id, code, message.from_user)
    if error:
        await message.answer(HANDSHAKE_ERRORS.get(error, HANDSHAKE_ERRORS["invalid"]))
        return
    text = "✅ Telegram бот OYUNS ERP-тэй амжилттай холбогдлоо. Одоо ажилтнуудад Telegram ID оноож, мэдэгдэл хүлээн авах боломжтой."
    if linked_name:
        text += f"\n\n👤 Таны Telegram бүртгэл «{html.escape(linked_name)}» профайлд холбогдлоо."
    await message.answer(text)
