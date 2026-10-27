"""টেলিগ্রাম UI সহায়ক: বাটন, মেনু, মেসেজ দেখানো।"""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest

# মূল মেনুতে ঠিক চারটি অপশন
BTN_PROFILE = "👤 Profile"
BTN_ADD = "➕ Add Profile"
BTN_SESSION = "📱 Telegram Session"
BTN_HISTORY = "📜 History"
MENU_BUTTONS = (BTN_PROFILE, BTN_ADD, BTN_SESSION, BTN_HISTORY)
MENU_REGEX = "^(" + "|".join(MENU_BUTTONS).replace("+", r"\+") + ")$"


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[BTN_PROFILE, BTN_ADD], [BTN_SESSION, BTN_HISTORY]],
                               resize_keyboard=True)


def kb(rows) -> InlineKeyboardMarkup:
    """rows = [[(লেখা, callback_data), ...], ...]"""
    return InlineKeyboardMarkup([[InlineKeyboardButton(t, callback_data=d) for t, d in row] for row in rows])


async def show(update, text: str, markup=None):
    """Callback হলে বর্তমান মেসেজ সম্পাদনা, নইলে নতুন মেসেজ পাঠায়।"""
    q = update.callback_query
    if q:
        await q.answer()
        try:
            await q.edit_message_text(text, reply_markup=markup, parse_mode=ParseMode.HTML,
                                      disable_web_page_preview=True)
            return
        except BadRequest as e:
            if "not modified" in str(e).lower():
                return
        await q.message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.HTML,
                                   disable_web_page_preview=True)
    else:
        await update.effective_message.reply_text(text, reply_markup=markup, parse_mode=ParseMode.HTML,
                                                  disable_web_page_preview=True)


async def say(update, text: str, markup=None):
    """সবসময় নতুন মেসেজ।"""
    msg = update.effective_message
    await msg.reply_text(text, reply_markup=markup, parse_mode=ParseMode.HTML,
                         disable_web_page_preview=True)


async def try_delete(message):
    """গোপন তথ্য (API Hash, কোড, পাসওয়ার্ড) চ্যাট থেকে মুছে ফেলার চেষ্টা।"""
    try:
        await message.delete()
    except Exception:
        pass
