"""➕ Add Profile (এবং Profile-এ ➕ Job যোগ) — ধাপে ধাপে উইজার্ড।
সবকিছু user_data-তে জমা থাকে; শেষে Admin নিশ্চিত করলেই একটি ট্রানজ্যাকশনে সংরক্ষণ হয়।
মাঝপথে Cancel করলে বা ভুল হলে ডাটাবেসে কিছুই লেখা হয় না।"""
import sqlite3
from pathlib import Path

from telegram.ext import (CallbackQueryHandler, CommandHandler, ConversationHandler,
                          MessageHandler, filters)

import auth
import config
import db
import excel_manager
import history
import texts
import ui
from auth import require
from texts import h
from tg_client import normalize_ref

(NAME, JOB_PICK, NJ_NAME, NJ_KEY, NJ_BOT, NJ_GROUP, NJ_RULES, NJ_CONFIRM,
 EXCEL, COLS, RULES, INTERVAL, PREVIEW) = range(13)

SKIP = [[("⏭️ এড়িয়ে যান", "wz:skip")], [("❌ Cancel", "wz:cancel")]]
CANCEL_ONLY = [[("❌ Cancel", "wz:cancel")]]


def _wz(context) -> dict:
    return context.user_data.setdefault("wz", {})


def _cleanup(context):
    wz = context.user_data.pop("wz", None)
    if wz and wz.get("tmp"):
        excel_manager.discard(wz["tmp"])


async def _end_cancel(update, context):
    _cleanup(context)
    if update.callback_query:
        await ui.show(update, texts.CANCELLED)
    else:
        await ui.say(update, texts.CANCELLED, ui.main_menu())
    return ConversationHandler.END


# ---------------- শুরু ----------------
@require("admin")
async def start_new_profile(update, context):
    _cleanup(context)
    context.user_data["wz"] = {"mode": "profile"}
    await ui.say(update, "➕ <b>নতুন Profile</b>\n\nধাপ ১: Profile-এর নাম লিখুন।", ui.kb(CANCEL_ONLY))
    return NAME


@require("admin")
async def start_add_job(update, context):
    _cleanup(context)
    pid = int(update.callback_query.data.split(":")[1])
    p = db.one("SELECT * FROM profiles WHERE id=?", (pid,))
    if not p:
        await ui.show(update, "Profile পাওয়া যায়নি।")
        return ConversationHandler.END
    context.user_data["wz"] = {"mode": "add_job", "profile_id": pid, "name": p["name"]}
    return await _ask_job_pick(update, context)


@require("admin")
async def got_name(update, context):
    name = (update.message.text or "").strip()
    if not name or len(name) > 50:
        await ui.say(update, "⚠️ নাম ১–৫০ অক্ষরের মধ্যে হতে হবে। আবার লিখুন।", ui.kb(CANCEL_ONLY))
        return NAME
    dup = db.one("SELECT 1 FROM profiles WHERE owner_user_id=? AND lower(name)=lower(?)",
                 (update.effective_user.id, name))
    if dup:
        await ui.say(update, "⚠️ এই নামে আপনার একটি Profile আগে থেকেই আছে। অন্য নাম দিন।", ui.kb(CANCEL_ONLY))
        return NAME
    _wz(context)["name"] = name
    return await _ask_job_pick(update, context)


# ---------------- Job নির্বাচন ----------------
async def _ask_job_pick(update, context, note=""):
    wz = _wz(context)
    exclude = wz.get("profile_id")
    jobs = db.all("SELECT * FROM jobs WHERE id NOT IN (SELECT job_id FROM profile_jobs WHERE profile_id=?) "
                  "ORDER BY id", (exclude or 0,))
    rows = [[(texts.job_label(j)[:60], f"wj:{j['id']}")] for j in jobs]
    rows.append([("➕ নতুন Job Add করুন", "wj:new")])
    rows.append([("❌ Cancel", "wz:cancel")])
    step = "ধাপ ২" if wz["mode"] == "profile" else "ধাপ ১"
    text = (note + "\n\n" if note else "") + \
        f"{step}: <b>{h(wz['name'])}</b>-এর জন্য Job নির্বাচন করুন, অথবা নতুন Job যোগ করুন।"
    if update.callback_query:
        await ui.show(update, text, ui.kb(rows))
    else:
        await ui.say(update, text, ui.kb(rows))
    return JOB_PICK


@require("admin")
async def pick_job(update, context):
    choice = update.callback_query.data.split(":")[1]
    wz = _wz(context)
    if choice == "new":
        wz["new_job"] = {}
        await ui.show(update, "🧩 <b>নতুন Job</b>\n\nJob-এর নাম লিখুন (যেমন: <code>2FA dgddigital</code>)।",
                      ui.kb(CANCEL_ONLY))
        return NJ_NAME
    job = db.one("SELECT * FROM jobs WHERE id=?", (int(choice),))
    if not job:
        await update.callback_query.answer("Job পাওয়া যায়নি।", show_alert=True)
        return JOB_PICK
    if job["status"] == "closed":
        await update.callback_query.answer("এই Job বন্ধ (Closed)। আগে /openjob দিয়ে খুলুন।", show_alert=True)
        return JOB_PICK
    wz["job_id"] = job["id"]
    wz.pop("new_job", None)
    return await _after_job(update, context)


async def _after_job(update, context):
    wz = _wz(context)
    if wz["mode"] == "profile":
        await ui.show(update, "ধাপ ৩: Profile-এর <b>Excel ফাইল</b> (.xlsx) পাঠান।\n"
                              f"(সর্বোচ্চ {config.MAX_EXCEL_BYTES // (1024 * 1024)} MB)", ui.kb(CANCEL_ONLY))
        return EXCEL
    return await _ask_interval(update, context)


# ---------------- নতুন Job-এর তথ্য ----------------
@require("admin")
async def nj_name(update, context):
    name = (update.message.text or "").strip()
    if not name or len(name) > 80:
        await ui.say(update, "⚠️ নাম ১–৮০ অক্ষরের মধ্যে হতে হবে।", ui.kb(CANCEL_ONLY))
        return NJ_NAME
    _wz(context)["new_job"]["name"] = name
    await ui.say(update, "External Job ID/Key লিখুন (যেমন: <code>Sesi sesi4</code>)।\n"
                         "Job Bot-এর বোর্ডে Job চিনতে এটি ব্যবহার হবে। না থাকলে এড়িয়ে যান।", ui.kb(SKIP))
    return NJ_KEY


@require("admin")
async def nj_key(update, context):
    nj = _wz(context)["new_job"]
    if update.callback_query:           # skip
        await update.callback_query.answer()
        nj["external_job_key"] = None
    else:
        key = (update.message.text or "").strip()
        if not key or len(key) > 80:
            await ui.say(update, "⚠️ ১–৮০ অক্ষরের Key দিন, অথবা এড়িয়ে যান।", ui.kb(SKIP))
            return NJ_KEY
        nj["external_job_key"] = key
    await _say_or_show(update, "Job Bot-এর <b>@username</b> লিখুন (যেমন: <code>@my_job_bot</code>)।",
                       ui.kb(CANCEL_ONLY))
    return NJ_BOT


async def _say_or_show(update, text, markup):
    if update.callback_query:
        await ui.show(update, text, markup)
    else:
        await ui.say(update, text, markup)


async def _ref_step(update, context, field, next_state, same_state, prompt):
    ref = normalize_ref(update.message.text or "")
    if not ref:
        await ui.say(update, "⚠️ ঠিকমতো @username অথবা সংখ্যার Chat ID দিন।", ui.kb(CANCEL_ONLY))
        return same_state
    ok, note = await context.application.bot_data["tg"].check_ref(ref)
    if ok is False:
        await ui.say(update, f"⚠️ {note}। ঠিকানা মিলিয়ে আবার দিন।", ui.kb(CANCEL_ONLY))
        return same_state
    _wz(context)["new_job"][field] = ref
    warn = "\n(⚠️ Session নেই বলে যাচাই করা হয়নি)" if ok is None else ""
    await ui.say(update, prompt + warn, ui.kb(next_state[1]))
    return next_state[0]


@require("admin")
async def nj_bot(update, context):
    return await _ref_step(update, context, "bot_chat_id", (NJ_GROUP, CANCEL_ONLY), NJ_BOT,
                           "Job-এর <b>Telegram Group</b>-এর @username বা Chat ID লিখুন।")


@require("admin")
async def nj_group(update, context):
    return await _ref_step(update, context, "group_chat_id", (NJ_RULES, SKIP), NJ_GROUP,
                           "Job-এর <b>Rules/Format</b> লিখুন (ঐচ্ছিক)।")


@require("admin")
async def nj_rules(update, context):
    nj = _wz(context)["new_job"]
    if update.callback_query:
        await update.callback_query.answer()
        nj["rules_text"] = None
    else:
        nj["rules_text"] = (update.message.text or "").strip()[:1000]
    await _say_or_show(
        update,
        "সফল Submission-এর পর Job Bot উত্তরে যে <b>শব্দ/বাক্যাংশ</b> পাঠায় সেটি লিখুন "
        "(যেমন: <code>berhasil</code>)।\n\n⚠️ এড়িয়ে গেলে বট সফলতা নিজে নিশ্চিত করতে পারবে না — "
        "প্রতিটি Submission 'অনিশ্চিত' থাকবে এবং আপনাকে হাতে নিশ্চিত করতে হবে; Excel মোছা হবে না।",
        ui.kb(SKIP))
    return NJ_CONFIRM


@require("admin")
async def nj_confirm(update, context):
    wz = _wz(context)
    nj = wz["new_job"]
    if update.callback_query:
        await update.callback_query.answer()
        nj["confirm_keyword"] = None
    else:
        nj["confirm_keyword"] = (update.message.text or "").strip()[:100] or None
    dup = _find_duplicate_job(nj)
    if dup:
        wz.pop("new_job", None)
        return await _ask_job_pick(
            update, context,
            note=f"⚠️ এই Job আগে থেকেই আছে (<b>#{dup['id']} {h(dup['name'])}</b>)। "
                 "নতুন করে না বানিয়ে তালিকা থেকে নির্বাচন করুন।")
    return await _after_new_job(update, context)


def _find_duplicate_job(nj):
    if nj.get("external_job_key"):
        return db.one("SELECT * FROM jobs WHERE lower(bot_chat_id)=lower(?) AND lower(external_job_key)=lower(?)",
                      (nj["bot_chat_id"], nj["external_job_key"]))
    return db.one("SELECT * FROM jobs WHERE lower(bot_chat_id)=lower(?) AND lower(group_chat_id)=lower(?) "
                  "AND lower(name)=lower(?) AND (external_job_key IS NULL OR external_job_key='')",
                  (nj["bot_chat_id"], nj["group_chat_id"], nj["name"]))


async def _after_new_job(update, context):
    return await _after_job(update, context)


# ---------------- Excel ----------------
@require("admin")
async def got_excel(update, context):
    wz = _wz(context)
    doc = update.message.document
    if doc.file_size and doc.file_size > config.MAX_EXCEL_BYTES:
        await ui.say(update, "⚠️ ফাইল অনেক বড়। ছোট ফাইল পাঠান।", ui.kb(CANCEL_ONLY))
        return EXCEL
    tmp = excel_manager.new_tmp_path()
    f = await context.bot.get_file(doc.file_id)
    await f.download_to_drive(custom_path=str(tmp))
    errors, headers, rows = excel_manager.validate(tmp)
    if errors:
        excel_manager.discard(tmp)
        await ui.say(update, "⚠️ " + "\n".join(errors) + "\nআবার সঠিক ফাইল পাঠান।", ui.kb(CANCEL_ONLY))
        return EXCEL
    if wz.get("tmp"):
        excel_manager.discard(wz["tmp"])
    wz.update(tmp=str(tmp), excel_name=doc.file_name or "file.xlsx", headers=headers, rows=rows)
    await ui.say(update, f"✅ Excel পাওয়া গেছে: {rows}টি সারি।\nকলাম: <code>{h(', '.join(headers))}</code>\n\n"
                         "ধাপ ৪: প্রয়োজনীয় কলামের নাম কমা দিয়ে লিখুন (যেমন: <code>Email, Password</code>)। "
                         "Excel-এ সেগুলো আছে কিনা যাচাই হবে।", ui.kb(SKIP))
    return COLS


@require("admin")
async def wrong_excel(update, context):
    await ui.say(update, "⚠️ অনুগ্রহ করে .xlsx ফাইলটি Document হিসেবে পাঠান।", ui.kb(CANCEL_ONLY))
    return EXCEL


@require("admin")
async def got_cols(update, context):
    wz = _wz(context)
    if update.callback_query:
        await update.callback_query.answer()
        wz["required_columns"] = ""
    else:
        cols = excel_manager.parse_columns(update.message.text or "")
        have = {c.lower() for c in wz["headers"]}
        missing = [c for c in cols if c.lower() not in have]
        if missing:
            await ui.say(update, "⚠️ Excel-এ এই কলামগুলো নেই: <code>" + h(", ".join(missing)) +
                                 "</code>\nসঠিক নাম লিখুন, অথবা এড়িয়ে যান।", ui.kb(SKIP))
            return COLS
        wz["required_columns"] = ", ".join(cols)
    await _say_or_show(update, "ধাপ ৫: এই Profile-এর <b>Rules/Format</b> লিখুন (ঐচ্ছিক)।", ui.kb(SKIP))
    return RULES


@require("admin")
async def got_rules(update, context):
    wz = _wz(context)
    if update.callback_query:
        await update.callback_query.answer()
        wz["rules_text"] = ""
    else:
        wz["rules_text"] = (update.message.text or "").strip()[:1000]
    return await _ask_interval(update, context)


# ---------------- Monitor Interval ----------------
async def _ask_interval(update, context):
    btns = [[(f"{s} সেকেন্ড" + (" (ডিফল্ট)" if s == config.DEFAULT_INTERVAL else ""), f"iv:{s}")]
            for s in config.INTERVAL_CHOICES]
    btns.append([("❌ Cancel", "wz:cancel")])
    await _say_or_show(update, "Monitor কত সেকেন্ড পরপর Job Check করবে?", ui.kb(btns))
    return INTERVAL


@require("admin")
async def got_interval(update, context):
    sec = int(update.callback_query.data.split(":")[1])
    if sec not in config.INTERVAL_CHOICES:
        return INTERVAL
    wz = _wz(context)
    wz["interval"] = sec
    await ui.show(update, _preview_text(wz),
                  ui.kb([[("✅ নিশ্চিত করে Save", "wz:save")], [("❌ Cancel", "wz:cancel")]]))
    return PREVIEW


def _preview_text(wz) -> str:
    nj = wz.get("new_job")
    if nj:
        job = (f"🆕 নতুন Job: <b>{h(nj['name'])}</b>\n   External ID: {h(nj.get('external_job_key') or '—')}\n"
               f"   Bot: {h(nj['bot_chat_id'])} · Group: {h(nj['group_chat_id'])}\n"
               f"   Confirmation শব্দ: {h(nj.get('confirm_keyword') or 'নেই (Submission অনিশ্চিত থাকবে)')}")
    else:
        j = db.one("SELECT * FROM jobs WHERE id=?", (wz["job_id"],))
        job = f"🧩 Job: <b>{h(texts.job_label(j))}</b>"
    head = (f"👤 Profile: <b>{h(wz['name'])}</b>" if wz["mode"] == "profile"
            else f"👤 Profile <b>{h(wz['name'])}</b>-এ Job যোগ")
    lines = ["📝 <b>চূড়ান্ত যাচাই</b>", head, job, f"⏱️ Check বিরতি: {wz['interval']} সেকেন্ড"]
    if wz["mode"] == "profile":
        lines += [f"📊 Excel: {h(wz['excel_name'])} ({wz['rows']} সারি)",
                  f"প্রয়োজনীয় কলাম: {h(wz.get('required_columns') or '—')}",
                  f"Rules: {h(wz.get('rules_text') or '—')}",
                  "শুরুতে Profile <b>Stopped</b> থাকবে; Profile খুলে ▶️ Start দিলে Monitor চালু হবে।"]
    lines.append("\nসব ঠিক থাকলে Save করুন।")
    return "\n".join(lines)


# ---------------- Save ----------------
@require("admin")
async def save(update, context):
    wz = _wz(context)
    uid = update.effective_user.id
    stored = None
    try:
        if wz["mode"] == "profile":
            stored = excel_manager.move_to_storage(Path(wz["tmp"]))
            wz["tmp"] = None
        with db.tx() as c:
            now = db.now_utc()
            job_id = wz.get("job_id")
            if wz.get("new_job"):
                nj = wz["new_job"]
                if _find_duplicate_job(nj):
                    raise sqlite3.IntegrityError("duplicate job")
                job_id = c.execute(
                    "INSERT INTO jobs(name, external_job_key, bot_chat_id, group_chat_id, status, rules_text,"
                    " confirm_keyword, created_at) VALUES(?,?,?,?, 'active', ?,?,?)",
                    (nj["name"], nj.get("external_job_key"), nj["bot_chat_id"], nj["group_chat_id"],
                     nj.get("rules_text"), nj.get("confirm_keyword"), now)).lastrowid
            if wz["mode"] == "profile":
                pid = c.execute(
                    "INSERT INTO profiles(owner_user_id, name, status, rules_text, required_columns,"
                    " created_at, updated_at) VALUES(?,?, 'stopped', ?,?,?,?)",
                    (uid, wz["name"], wz.get("rules_text"), wz.get("required_columns"), now, now)).lastrowid
                excel_manager.register(c, pid, stored, wz["excel_name"], wz["rows"])
            else:
                pid = wz["profile_id"]
            c.execute("INSERT INTO profile_jobs(profile_id, job_id, check_interval_seconds, created_at) "
                      "VALUES(?,?,?,?)", (pid, job_id, wz["interval"], now))
    except sqlite3.IntegrityError:
        if stored:
            excel_manager.discard(stored)
        _cleanup(context)
        await ui.show(update, "⚠️ এই তথ্য আগে থেকেই আছে (ডুপ্লিকেট)। কিছু সংরক্ষণ করা হয়নি।")
        return ConversationHandler.END
    except Exception:
        if stored:
            excel_manager.discard(stored)
        _cleanup(context)
        await ui.show(update, "⚠️ সংরক্ষণে সমস্যা হয়েছে। কিছু সংরক্ষণ করা হয়নি — আবার চেষ্টা করুন।")
        raise

    if wz["mode"] == "profile":
        history.add("profile_created", f"Profile তৈরি: {wz['name']}", pid, job_id)
        history.add("excel_uploaded", f"Excel আপলোড: {wz['excel_name']} ({wz['rows']} সারি)", pid)
    if wz.get("new_job"):
        history.add("job_created", f"নতুন Job: {wz['new_job']['name']}", pid, job_id)
    history.add("job_linked", "Profile-এ Job যুক্ত", pid, job_id)
    _cleanup(context)
    await ui.show(update, "✅ সংরক্ষণ হয়েছে।",
                  ui.kb([[("👤 Profile খুলুন", f"pf:{pid}")]]))
    return ConversationHandler.END


async def cancel_cb(update, context):
    if update.callback_query:
        await update.callback_query.answer()
    return await _end_cancel(update, context)


def build_handler() -> ConversationHandler:
    cb = CallbackQueryHandler
    txt = filters.TEXT & ~filters.COMMAND & ~filters.Regex(ui.MENU_REGEX)
    skip_cb = lambda fn: cb(fn, pattern="^wz:skip$")
    return ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^" + ui.BTN_ADD.replace("+", r"\+") + "$"), start_new_profile),
                      cb(start_add_job, pattern=r"^pj_add:\d+$")],
        states={
            NAME: [MessageHandler(txt, got_name)],
            JOB_PICK: [cb(pick_job, pattern=r"^wj:(\d+|new)$")],
            NJ_NAME: [MessageHandler(txt, nj_name)],
            NJ_KEY: [MessageHandler(txt, nj_key), skip_cb(nj_key)],
            NJ_BOT: [MessageHandler(txt, nj_bot)],
            NJ_GROUP: [MessageHandler(txt, nj_group)],
            NJ_RULES: [MessageHandler(txt, nj_rules), skip_cb(nj_rules)],
            NJ_CONFIRM: [MessageHandler(txt, nj_confirm), skip_cb(nj_confirm)],
            EXCEL: [MessageHandler(filters.Document.ALL, got_excel), MessageHandler(txt, wrong_excel)],
            COLS: [MessageHandler(txt, got_cols), skip_cb(got_cols)],
            RULES: [MessageHandler(txt, got_rules), skip_cb(got_rules)],
            INTERVAL: [cb(got_interval, pattern=r"^iv:\d+$")],
            PREVIEW: [cb(save, pattern="^wz:save$")],
        },
        fallbacks=[cb(cancel_cb, pattern="^wz:cancel$"),
                   CommandHandler("cancel", _end_cancel),
                   MessageHandler(filters.Regex(ui.MENU_REGEX), _end_cancel)],
        name="profile_wizard", persistent=False, allow_reentry=True,
    )
