"""Role ও Permission যাচাই। প্রতিটি Handler-এ @require(...) বসানো আছে।"""
import functools

from telegram.ext import ConversationHandler

import config
import db
import texts

RANK = {"viewer": 1, "admin": 2, "owner": 3}


def seed_owner():
    if config.OWNER_ID:
        db.run("INSERT OR IGNORE INTO admin_users(telegram_user_id, role, enabled, created_at) "
               "VALUES(?, 'owner', 1, ?)", (config.OWNER_ID, db.now_utc()))


def get_role(user_id: int | None):
    if not user_id:
        return None
    if user_id == config.OWNER_ID:
        return "owner"
    row = db.one("SELECT role FROM admin_users WHERE telegram_user_id=? AND enabled=1", (user_id,))
    return row["role"] if row else None


def has_role(user_id, minimum: str) -> bool:
    role = get_role(user_id)
    return bool(role) and RANK[role] >= RANK[minimum]


async def _deny(update, message: str):
    q = update.callback_query
    if q:
        await q.answer(message[:190], show_alert=True)
    elif update.effective_message:
        await update.effective_message.reply_text(message, parse_mode="HTML")


def require(minimum: str = "viewer"):
    def deco(fn):
        @functools.wraps(fn)
        async def wrapper(update, context, *args, **kwargs):
            user = update.effective_user
            role = get_role(user.id) if user else None
            if not role:
                uid = user.id if user else "?"
                await _deny(update, texts.NO_ACCESS.format(uid=uid))
                return ConversationHandler.END
            if RANK[role] < RANK[minimum]:
                await _deny(update, texts.NEED_OWNER if minimum == "owner" else texts.NEED_ADMIN)
                return ConversationHandler.END
            return await fn(update, context, *args, **kwargs)
        return wrapper
    return deco
