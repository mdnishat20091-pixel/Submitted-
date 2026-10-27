"""📱 Telegram Session: স্ট্যাটাস, Connect, Disconnect, Revoke, Error History।
শুধু Owner নিজের (বা স্পষ্টভাবে অনুমোদিত) Account সংযুক্ত করবেন।
API Hash, লগইন কোড ও পাসওয়ার্ড পাঠানোর পরপরই চ্যাট থেকে মুছে ফেলার চেষ্টা হয় এবং কোথাও লগ হয় না।"""
import re

from telegram.ext import (CallbackQueryHandler, CommandHandler, ConversationHandler,
                          MessageHandler, filters)

import db
import history
import texts
import ui
from auth import require
from texts import h, fmt_time
from tg_client import NeedPassword, mask_phone

API_ID, API_HASH, PHONE, CODE, PASSWORD = range(5)
CANCEL = [[("❌ Cancel", "ss_cancel")]]

SESSION_STATUS = {
    "connected": "🟢 সংযুক্ত", "disconnected": "⚪ বিচ্ছিন্ন",
    "revoked": "🔴 Revoke করা হয়েছে", "error": "⚠️ ত্রুটি — আবার Connect করুন",
}


def _screen(is_owner: bool):
    row = db.one("SELECT * FROM telegram_sessions ORDER BY id DESC LIMIT 1")
    if row:
        text = (f"📱 <b>Telegram Session</b>\nঅবস্থা: {SESSION_STATUS.get(row['status'], row['status'])}\n"
                f"ফোন: <code>{h(row['phone_hint'] or '—')}</code>\nসর্বশেষ বদল: {fmt_time(row['updated_at'])}")
        if row["last_error"]:
            text += f"\nশেষ ত্রুটি: {h(row['last_error'])}"
    else:
        text = "📱 <b>Telegram Session</b>\nকোনো Session সংযুক্ত নেই।"
    text += ("\n\nℹ️ এই Session দিয়ে বট আপনার Account থেকে Job Bot ও Group-এর সাথে কথা বলে। "
             "শুধু নিজের বা স্পষ্টভাবে অনুমোদিত Account সংযুক্ত করুন।")
    rows = []
    if is_owner:
        rows.append([("🔗 Connect Session", "ss_connect")])
        if row and row["status"] in ("connected", "error"):
            rows.append([("🔌 Disconnect", "ss_off"), ("🗑️ Revoke", "ss_rev")])
    rows.append([("⚠️ Error History", "ss_err")])
    return text, ui.kb(rows)


@require("admin")
async def session_menu(update, context):
    from auth import has_role
    text, markup = _screen(has_role(update.effective_user.id, "owner"))
    await ui.show(update, text, markup)


@require("admin")
async def error_history(update, context):
    rows = db.all("SELECT * FROM job_history WHERE event_type='session_error' ORDER BY id DESC LIMIT 10")
    text = "⚠️ <b>Session Error History</b>\n\n" + (
        "\n".join(f"🕒 {fmt_time(r['created_at'])} — {h(r['message'])}" for r in rows) if rows else "কোনো ত্রুটি নেই।")
    await ui.show(update, text, ui.kb([[("⬅️ ফিরে যান", "ss_menu")]]))


@require("owner")
async def disconnect_ask(update, context):
    act = "off" if update.callback_query.data == "ss_off" else "rev"
    info = ("🔌 <b>Disconnect:</b> বট এই Session আর ব্যবহার করবে না এবং সংরক্ষিত তথ্য মুছবে। "
            "তবে Telegram-এর দিকে Session বৈধ থাকবে।" if act == "off" else
            "🗑️ <b>Revoke:</b> Telegram থেকেও Session লগআউট হবে এবং সংরক্ষিত তথ্য মুছবে।")
    await ui.show(update, info + "\n\nনিশ্চিত?",
                  ui.kb([[("✅ হ্যাঁ", f"ss_do:{act}"), ("↩️ না", "ss_menu")]]))


@require("owner")
async def disconnect_do(update, context):
    tg = context.application.bot_data["tg"]
    if update.callback_query.data.endswith("off"):
        await tg.disconnect()
    else:
        await tg.revoke()
    text, markup = _screen(True)
    await ui.show(update, "✅ সম্পন্ন।\n\n" + text, markup)


# ---------------- Connect ----------------
async def _drop_pending(context):
    ss = context.user_data.pop("ss", None)
    if ss and ss.get("client"):
        try:
            await ss["client"].disconnect()
        except Exception:
            pass


@require("owner")
async def connect_start(update, context):
    await _drop_pending(context)
    context.user_data["ss"] = {}
    await ui.show(update,
                  "🔗 <b>Session Connect</b>\n\n১) my.telegram.org থেকে পাওয়া <b>API ID</b> (শুধু সংখ্যা) পাঠান।\n"
                  "🔒 গোপন তথ্য পাঠানোর পর বট মেসেজটি চ্যাট থেকে মুছে ফেলার চেষ্টা করবে।", ui.kb(CANCEL))
    return API_ID


@require("owner")
async def got_api_id(update, context):
    text = (update.message.text or "").strip()
    await ui.try_delete(update.message)
    if not text.isdigit():
        await ui.say(update, "⚠️ API ID শুধু সংখ্যা। আবার পাঠান।", ui.kb(CANCEL))
        return API_ID
    context.user_data["ss"]["api_id"] = int(text)
    await ui.say(update, "২) <b>API Hash</b> পাঠান।", ui.kb(CANCEL))
    return API_HASH


@require("owner")
async def got_api_hash(update, context):
    text = (update.message.text or "").strip()
    await ui.try_delete(update.message)
    if not re.fullmatch(r"[0-9a-fA-F]{32}", text):
        await ui.say(update, "⚠️ API Hash ৩২ অক্ষরের (০-৯, a-f) হয়। আবার পাঠান।", ui.kb(CANCEL))
        return API_HASH
    context.user_data["ss"]["api_hash"] = text
    await ui.say(update, "৩) ফোন নম্বর দেশের কোডসহ পাঠান (যেমন: <code>+8801XXXXXXXXX</code>)।", ui.kb(CANCEL))
    return PHONE


@require("owner")
async def got_phone(update, context):
    phone = re.sub(r"[^\d+]", "", update.message.text or "")
    await ui.try_delete(update.message)
    if not re.fullmatch(r"\+\d{8,15}", phone):
        await ui.say(update, "⚠️ নম্বর + এবং দেশের কোডসহ দিন।", ui.kb(CANCEL))
        return PHONE
    ss = context.user_data["ss"]
    tg = context.application.bot_data["tg"]
    try:
        client, code_hash = await tg.begin_login(ss["api_id"], ss["api_hash"], phone)
    except Exception as e:
        msg = _login_error(e)
        history.add("session_error", f"কোড পাঠাতে ব্যর্থ: {type(e).__name__}")
        await _drop_pending(context)
        await ui.say(update, f"⚠️ {msg}\nআবার শুরু করতে 📱 Telegram Session মেনু খুলুন।", ui.kb([[("⬅️ ফিরে যান", "ss_menu")]]))
        return ConversationHandler.END
    ss.update(client=client, phone=phone, code_hash=code_hash)
    await ui.say(update,
                 "৪) Telegram-এ আসা <b>লগইন কোড</b> পাঠান।\n⚠️ কোডের সংখ্যাগুলোর মাঝে ড্যাশ দিন "
                 "(যেমন <code>1-2-3-4-5</code>); নইলে Telegram কোডটি বাতিল করে দিতে পারে।", ui.kb(CANCEL))
    return CODE


@require("owner")
async def got_code(update, context):
    raw = update.message.text or ""
    await ui.try_delete(update.message)
    code = re.sub(r"\D", "", raw)
    if not code:
        await ui.say(update, "⚠️ কোডে সংখ্যা থাকতে হবে। আবার পাঠান।", ui.kb(CANCEL))
        return CODE
    return await _finish(update, context, code=code)


@require("owner")
async def got_password(update, context):
    pw = update.message.text or ""
    await ui.try_delete(update.message)
    return await _finish(update, context, password=pw)


async def _finish(update, context, code=None, password=None):
    ss = context.user_data["ss"]
    tg = context.application.bot_data["tg"]
    try:
        session_string = await tg.finish_login(ss["client"], ss["phone"], code, ss["code_hash"], password)
    except NeedPassword:
        await ui.say(update, "৫) আপনার Account-এ Two-step verification চালু আছে। <b>পাসওয়ার্ড</b> পাঠান।",
                     ui.kb(CANCEL))
        return PASSWORD
    except Exception as e:
        name = type(e).__name__
        history.add("session_error", f"লগইন ব্যর্থ: {name}")
        if name in ("PhoneCodeInvalidError", "PasswordHashInvalidError"):
            await ui.say(update, f"⚠️ {_login_error(e)} আবার পাঠান।", ui.kb(CANCEL))
            return PASSWORD if password is not None else CODE
        await _drop_pending(context)
        await ui.say(update, f"⚠️ {_login_error(e)}\nআবার শুরু করতে 📱 Telegram Session মেনু খুলুন।",
                     ui.kb([[("⬅️ ফিরে যান", "ss_menu")]]))
        return ConversationHandler.END
    await tg.drop_client()
    tg.save_session(update.effective_user.id, ss["phone"], ss["api_id"], ss["api_hash"], session_string)
    await ss["client"].disconnect()
    context.user_data.pop("ss", None)
    history.add("session_connected", f"Session সংযুক্ত ({mask_phone(ss['phone'])})")
    await ui.say(update, "✅ Session সংযুক্ত হয়েছে। আপনার পাঠানো গোপন তথ্য চ্যাট থেকে মুছে ফেলা হয়েছে।",
                 ui.kb([[("📱 Session মেনু", "ss_menu")]]))
    return ConversationHandler.END


def _login_error(e: Exception) -> str:
    name = type(e).__name__
    seconds = getattr(e, "seconds", None)
    return {
        "ApiIdInvalidError": "API ID/Hash ভুল।",
        "PhoneNumberInvalidError": "ফোন নম্বর ঠিক নয়।",
        "PhoneCodeInvalidError": "কোড ভুল।",
        "PhoneCodeExpiredError": "কোডের মেয়াদ শেষ।",
        "PasswordHashInvalidError": "পাসওয়ার্ড ভুল।",
        "FloodWaitError": f"Telegram সাময়িক সীমা দিয়েছে — {seconds} সেকেন্ড পরে চেষ্টা করুন।",
        "PhoneNumberBannedError": "এই নম্বর Telegram-এ নিষিদ্ধ।",
    }.get(name, "লগইন করা যায়নি। তথ্য মিলিয়ে আবার চেষ্টা করুন।")


async def cancel(update, context):
    await _drop_pending(context)
    if update.callback_query:
        await ui.show(update, texts.CANCELLED, ui.kb([[("📱 Session মেনু", "ss_menu")]]))
    else:
        await ui.say(update, texts.CANCELLED, ui.main_menu())
    return ConversationHandler.END


def build_handler():
    txt = filters.TEXT & ~filters.COMMAND & ~filters.Regex(ui.MENU_REGEX)
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(connect_start, pattern="^ss_connect$")],
        states={API_ID: [MessageHandler(txt, got_api_id)], API_HASH: [MessageHandler(txt, got_api_hash)],
                PHONE: [MessageHandler(txt, got_phone)], CODE: [MessageHandler(txt, got_code)],
                PASSWORD: [MessageHandler(txt, got_password)]},
        fallbacks=[CallbackQueryHandler(cancel, pattern="^ss_cancel$"), CommandHandler("cancel", cancel),
                   MessageHandler(filters.Regex(ui.MENU_REGEX), cancel)],
        name="session_login", persistent=False, allow_reentry=True,
    )
