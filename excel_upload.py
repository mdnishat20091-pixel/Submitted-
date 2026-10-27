"""📊 বিদ্যমান Profile-এ নতুন Excel আপলোড (পুরোনোটি বদলায়)।"""
from pathlib import Path

from telegram.ext import (CallbackQueryHandler, CommandHandler, ConversationHandler,
                          MessageHandler, filters)

import db
import excel_manager
import texts
import ui
from auth import require
from texts import h

WAIT = 0


@require("admin")
async def start(update, context):
    pid = int(update.callback_query.data.split(":")[1])
    p = db.one("SELECT * FROM profiles WHERE id=?", (pid,))
    if not p:
        await ui.show(update, "Profile পাওয়া যায়নি।")
        return ConversationHandler.END
    cur = excel_manager.get_active(pid)
    if cur and excel_manager.in_use(cur["id"]):
        await ui.show(update, "⚠️ বর্তমান Excel-এর সাথে Queue-তে অসম্পূর্ণ কাজ আছে। "
                              "আগে সেগুলো সম্পন্ন বা বাতিল করুন (/queue)।",
                      ui.kb([[("⬅️ ফিরে যান", f"pf:{pid}")]]))
        return ConversationHandler.END
    context.user_data["xl_pid"] = pid
    note = "\nনতুন ফাইল আপলোড করলে আগেরটি বদলে যাবে।" if cur else ""
    req = f"\nপ্রয়োজনীয় কলাম: <code>{h(p['required_columns'])}</code>" if p["required_columns"] else ""
    await ui.show(update, f"📊 <b>{h(p['name'])}</b>-এর জন্য Excel (.xlsx) পাঠান।{note}{req}",
                  ui.kb([[("❌ Cancel", "xl_cancel")]]))
    return WAIT


@require("admin")
async def got_file(update, context):
    pid = context.user_data.get("xl_pid")
    p = db.one("SELECT * FROM profiles WHERE id=?", (pid,)) if pid else None
    if not p:
        return ConversationHandler.END
    doc = update.message.document
    tmp = excel_manager.new_tmp_path()
    f = await context.bot.get_file(doc.file_id)
    await f.download_to_drive(custom_path=str(tmp))
    required = excel_manager.parse_columns(p["required_columns"] or "")
    errors, headers, rows = excel_manager.validate(tmp, required)
    if errors:
        excel_manager.discard(tmp)
        await ui.say(update, "⚠️ " + "\n".join(errors) + "\nআবার সঠিক ফাইল পাঠান।",
                     ui.kb([[("❌ Cancel", "xl_cancel")]]))
        return WAIT
    ok, msg = excel_manager.replace_excel(pid, tmp, doc.file_name or "file.xlsx", rows)
    if not ok:
        excel_manager.discard(tmp)
    context.user_data.pop("xl_pid", None)
    await ui.say(update, ("✅ " if ok else "⚠️ ") + msg + (f" ({rows}টি সারি)" if ok else ""),
                 ui.kb([[("👤 Profile খুলুন", f"pf:{pid}")]]))
    return ConversationHandler.END


async def cancel(update, context):
    context.user_data.pop("xl_pid", None)
    if update.callback_query:
        await ui.show(update, texts.CANCELLED)
    else:
        await ui.say(update, texts.CANCELLED, ui.main_menu())
    return ConversationHandler.END


async def not_a_file(update, context):
    await ui.say(update, "⚠️ .xlsx ফাইলটি Document হিসেবে পাঠান।", ui.kb([[("❌ Cancel", "xl_cancel")]]))
    return WAIT


def build_handler():
    return ConversationHandler(
        entry_points=[CallbackQueryHandler(start, pattern=r"^xl:\d+$")],
        states={WAIT: [MessageHandler(filters.Document.ALL, got_file),
                       MessageHandler(filters.TEXT & ~filters.COMMAND & ~filters.Regex(ui.MENU_REGEX), not_a_file)]},
        fallbacks=[CallbackQueryHandler(cancel, pattern="^xl_cancel$"), CommandHandler("cancel", cancel),
                   MessageHandler(filters.Regex(ui.MENU_REGEX), cancel)],
        name="excel_upload", persistent=False, allow_reentry=True,
    )
