"""টেলিগ্রাম Job Manager বট — প্রবেশ বিন্দু।  চালান:  python main.py"""
import asyncio
import logging
import sys
import warnings

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters)

import auth
import config
import db
import texts
import ui
from handlers import (admin_cmds, commands, excel_upload, history_view, profiles, session, wizard)
from monitor import Monitor
from queue_worker import QueueWorker
from tg_client import TgManager

warnings.filterwarnings("ignore", message=".*per_message.*")
logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
for noisy in ("httpx", "httpcore", "telegram", "telethon"):   # Token/URL যেন লগে না আসে
    logging.getLogger(noisy).setLevel(logging.WARNING)
log = logging.getLogger("main")


async def post_init(app: Application):
    tg = TgManager()
    notify_bot = app.bot

    async def notify(user_id: int, text: str):
        try:
            await notify_bot.send_message(user_id, text, parse_mode=ParseMode.HTML)
        except Exception as e:
            log.warning("নোটিফিকেশন পাঠানো যায়নি: %s", type(e).__name__)

    monitor, worker = Monitor(tg, notify), QueueWorker(tg, notify)
    n = worker.recover()
    if n:
        log.warning("%d টি আটকে থাকা কাজ 'অনিশ্চিত' চিহ্নিত হয়েছে", n)
    app.bot_data.update(tg=tg, monitor=monitor, worker=worker)
    app.bot_data["tasks"] = [asyncio.create_task(monitor.run()), asyncio.create_task(worker.run())]
    await app.bot.set_my_commands(commands.COMMANDS_FOR_MENU)


async def post_shutdown(app: Application):
    for t in app.bot_data.get("tasks", []):
        t.cancel()
    if "tg" in app.bot_data:
        await app.bot_data["tg"].drop_client()


async def on_error(update, context):
    log.error("Handler ত্রুটি: %s", type(context.error).__name__, exc_info=context.error)
    try:
        if isinstance(update, Update):
            if update.callback_query:
                await update.callback_query.answer(texts.GENERIC_ERROR, show_alert=True)
            elif update.effective_message:
                await update.effective_message.reply_text(texts.GENERIC_ERROR)
    except Exception:
        pass


def menu_text(label):
    return filters.Regex("^" + label + "$")


def build_app() -> Application:
    app = (Application.builder().token(config.BOT_TOKEN).concurrent_updates(True)
           .post_init(post_init).post_shutdown(post_shutdown).build())
    cb = CallbackQueryHandler

    # Conversation (আগে নিবন্ধন)
    app.add_handler(wizard.build_handler())
    app.add_handler(excel_upload.build_handler())
    app.add_handler(session.build_handler())

    # মূল মেনুর চারটি বাটন
    app.add_handler(MessageHandler(menu_text(ui.BTN_PROFILE), profiles.profiles_menu))
    app.add_handler(MessageHandler(menu_text(ui.BTN_SESSION), session.session_menu))
    app.add_handler(MessageHandler(menu_text(ui.BTN_HISTORY), history_view.history_menu))

    # Slash Command
    for name, fn in (("start", commands.start), ("help", commands.help_cmd), ("stor", commands.stor_cmd),
                     ("status", commands.status_cmd), ("jobs", commands.jobs_cmd),
                     ("openjob", commands.openjob_cmd), ("closejob", commands.closejob_cmd),
                     ("pausejobs", commands.pausejobs_cmd), ("resumejobs", commands.resumejobs_cmd),
                     ("rules", commands.rules_cmd), ("queue", commands.queue_cmd),
                     ("report", commands.report_cmd), ("stopjob", commands.stopjob_cmd),
                     ("admins", admin_cmds.admins_cmd), ("addadmin", admin_cmds.addadmin_cmd),
                     ("removeadmin", admin_cmds.removeadmin_cmd)):
        app.add_handler(CommandHandler(name, fn))

    # Inline বাটন
    for pattern, fn in ((r"^pf_list$", profiles.profiles_menu), (r"^pf:\d+$", profiles.profile_detail),
                        (r"^pa:\d+:\w+(:y)?$", profiles.profile_action), (r"^pc:\d+(:\d+)?$", profiles.check_now),
                        (r"^pj:\d+:\d+$", profiles.job_detail), (r"^pt:\d+:\d+$", profiles.job_toggle),
                        (r"^pi:\d+:\d+:\d+$", profiles.job_interval), (r"^pq:\d+$", commands.queue_profile_cb),
                        (r"^q:\w+:\d+(:y)?$", commands.queue_action_cb), (r"^cp:\w+:\d+$", commands.profile_pick_cb),
                        (r"^cj:\w+:\d+(:\w+)?$", commands.job_pick_cb), (r"^noop$", commands.noop),
                        (r"^hs_menu$", history_view.history_menu), (r"^hs:\d+:\d+$", history_view.history_page),
                        (r"^ss_menu$", session.session_menu), (r"^ss_err$", session.error_history),
                        (r"^ss_(off|rev)$", session.disconnect_ask), (r"^ss_do:(off|rev)$", session.disconnect_do)):
        app.add_handler(cb(fn, pattern=pattern))

    app.add_handler(cb(commands.stale_cb, pattern=r"^(wz:|iv:|wj:|xl_cancel$|ss_cancel$)"))  # সবার শেষে
    app.add_error_handler(on_error)
    return app


def main():
    if not config.BOT_TOKEN or not config.OWNER_ID:
        sys.exit("❌ BOT_TOKEN ও OWNER_ID Environment/Secrets-এ সেট করুন (.env.example দেখুন)।")
    db.migrate()
    auth.seed_owner()
    log.info("বট চালু হচ্ছে…")
    build_app().run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
