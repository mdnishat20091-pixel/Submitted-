"""সব Slash Command ও তাদের Callback।"""
import asyncio

import auth
import config
import db
import history
import queue_worker
import texts
import ui
from auth import require
from texts import h, fmt_time

HELP_TEXT = (
    "ℹ️ <b>সাহায্য — কমান্ড তালিকা</b>\n\n"
    "/start — মূল মেনু\n"
    "/stor — Job Bot-এর বোর্ড এখনই যাচাই\n"
    "/status — Profile ও Job-এর বর্তমান অবস্থা\n"
    "/jobs — সব Job-এর তালিকা\n"
    "/openjob — বন্ধ Job আবার খুলুন (Admin)\n"
    "/closejob — Job বন্ধ করুন (Admin)\n"
    "/pausejobs — Job সাময়িক বিরতি (Admin)\n"
    "/resumejobs — বিরতি দেওয়া Job চালু (Admin)\n"
    "/rules — Rules ও Format দেখুন\n"
    "/queue — Queue দেখুন ও অনিশ্চিত কাজ নিশ্চিত করুন\n"
    "/report — সংক্ষিপ্ত রিপোর্ট\n"
    "/stopjob — Job বন্ধের অবস্থা যাচাই/নির্দেশ (Admin)\n"
    "/cancel — চলমান ধাপ বাতিল\n\n"
    "মূল মেনুর চারটি বাটন: Profile, Add Profile, Telegram Session, History।"
)

COMMANDS_FOR_MENU = [
    ("start", "মূল মেনু"), ("stor", "Job বোর্ড এখনই যাচাই"), ("status", "বর্তমান অবস্থা"),
    ("jobs", "Job তালিকা"), ("openjob", "Job খুলুন"), ("closejob", "Job বন্ধ করুন"),
    ("pausejobs", "Job বিরতি"), ("resumejobs", "Job চালু"), ("rules", "Rules ও Format"),
    ("queue", "Queue দেখুন"), ("report", "রিপোর্ট"), ("stopjob", "Job বন্ধের অবস্থা"),
    ("help", "সাহায্য"),
]


@require("viewer")
async def start(update, context):
    role = auth.get_role(update.effective_user.id)
    who = {"owner": "Owner", "admin": "Admin", "viewer": "দর্শক (শুধু দেখার অনুমতি)"}[role]
    await ui.say(update, f"👋 স্বাগতম! আপনার ভূমিকা: <b>{who}</b>\n\n"
                         "নিচের মেনু থেকে কাজ বেছে নিন। সব কমান্ড দেখতে /help।", ui.main_menu())


@require("viewer")
async def help_cmd(update, context):
    await ui.say(update, HELP_TEXT)


# ---------------- /jobs ----------------
@require("viewer")
async def jobs_cmd(update, context):
    jobs = db.all("SELECT * FROM jobs ORDER BY id")
    if not jobs:
        await ui.say(update, "কোনো Job নেই।")
        return
    out = ["🧩 <b>সব Job</b>\n"]
    for j in jobs:
        users = db.all("SELECT p.name FROM profile_jobs pj JOIN profiles p ON p.id=pj.profile_id "
                       "WHERE pj.job_id=?", (j["id"],))
        out.append(f"{h(texts.job_label(j))}\n   Bot: {h(j['bot_chat_id'])} · Profile: "
                   f"{h(', '.join(u['name'] for u in users) or '—')}")
    await ui.say(update, "\n".join(out))


# ---------------- /status ----------------
@require("viewer")
async def status_cmd(update, context):
    profiles = db.all("SELECT * FROM profiles ORDER BY id")
    sess = db.one("SELECT status FROM telegram_sessions ORDER BY id DESC LIMIT 1")
    out = ["📊 <b>বর্তমান অবস্থা</b>",
           "Session: " + ("🟢 সংযুক্ত" if sess and sess["status"] == "connected" else "🔴 সংযুক্ত নেই"), ""]
    if not profiles:
        out.append("কোনো Profile নেই।")
    for p in profiles:
        out.append(f"👤 <b>{h(p['name'])}</b> — {texts.PROFILE_STATUS.get(p['status'], p['status'])}")
        for r in db.all("SELECT j.name, j.status jstatus, pj.monitor_state, pj.last_check_at FROM profile_jobs pj "
                        "JOIN jobs j ON j.id=pj.job_id WHERE pj.profile_id=?", (p["id"],)):
            out.append(f"   • {h(r['name'])} [{texts.JOB_STATUS.get(r['jstatus'], '')}] — "
                       f"{texts.MONITOR_STATE.get(r['monitor_state'], '')} · {fmt_time(r['last_check_at'])}")
    await ui.say(update, "\n".join(out))


# ---------------- প্রোফাইল বা জব বাছাই ----------------
async def _pick_profile(update, cmd, title):
    rows = db.all("SELECT id, name FROM profiles ORDER BY id")
    if not rows:
        await ui.say(update, "কোনো Profile নেই।")
        return
    await ui.say(update, title, ui.kb([[(f"👤 {r['name']}", f"cp:{cmd}:{r['id']}")] for r in rows]))


async def _pick_job(update, cmd, title, statuses, allow_all=False):
    q = "SELECT * FROM jobs"
    if statuses:
        q += " WHERE status IN (" + ",".join("?" * len(statuses)) + ")"
    jobs = db.all(q + " ORDER BY id", tuple(statuses or ()))
    if not jobs:
        await ui.say(update, "এই কাজের জন্য উপযুক্ত কোনো Job নেই।")
        return
    rows = [[(texts.job_label(j)[:60], f"cj:{cmd}:{j['id']}")] for j in jobs]
    if allow_all:
        rows.append([("📦 সবগুলো", f"cj:{cmd}:0")])
    await ui.say(update, title, ui.kb(rows))


@require("admin")
async def stor_cmd(update, context):
    await _pick_profile(update, "stor", "🔎 কোন Profile-এর Job বোর্ড যাচাই করবেন?")


@require("viewer")
async def rules_cmd(update, context):
    await _pick_profile(update, "rules", "📝 কোন Profile-এর Rules দেখবেন?")


@require("admin")
async def openjob_cmd(update, context):
    await _pick_job(update, "open", "🔓 কোন বন্ধ Job খুলবেন?", ["closed"])


@require("admin")
async def closejob_cmd(update, context):
    await _pick_job(update, "close", "🔒 কোন Job বন্ধ করবেন?", ["active", "paused"])


@require("admin")
async def pausejobs_cmd(update, context):
    await _pick_job(update, "pause", "⏸️ কোন Job বিরতিতে দেবেন?", ["active"], allow_all=True)


@require("admin")
async def resumejobs_cmd(update, context):
    await _pick_job(update, "resume", "⏯️ কোন Job আবার চালু করবেন?", ["paused"], allow_all=True)


@require("admin")
async def stopjob_cmd(update, context):
    await _pick_job(update, "stop", "🛑 কোন Job-এর বন্ধের অবস্থা যাচাই করবেন?", ["active", "paused", "closed"])


@require("viewer")
async def profile_pick_cb(update, context):
    _, cmd, pid = update.callback_query.data.split(":")
    pid = int(pid)
    p = db.one("SELECT * FROM profiles WHERE id=?", (pid,))
    if not p:
        await ui.show(update, "Profile পাওয়া যায়নি।")
        return
    if cmd == "rules":
        out = [f"📝 <b>{h(p['name'])}</b> — Rules ও Format",
               f"Profile Rules: {h(p['rules_text'] or '—')}",
               f"প্রয়োজনীয় Excel কলাম: {h(p['required_columns'] or '—')}", ""]
        for j in db.all("SELECT j.* FROM profile_jobs pj JOIN jobs j ON j.id=pj.job_id WHERE pj.profile_id=?",
                        (pid,)):
            out.append(f"🧩 <b>{h(j['name'])}</b>: {h(j['rules_text'] or '—')}")
        await ui.show(update, "\n".join(out))
    elif cmd == "stor":
        if not auth.has_role(update.effective_user.id, "admin"):
            await update.callback_query.answer(texts.NEED_ADMIN, show_alert=True)
            return
        jids = [r["job_id"] for r in db.all("SELECT job_id FROM profile_jobs WHERE profile_id=?", (pid,))]
        if not jids:
            await ui.show(update, "এই Profile-এ কোনো Job নেই।")
            return
        await update.callback_query.answer("⏳ Check চলছে…")
        monitor = context.application.bot_data["monitor"]
        out = [f"🔎 <b>{h(p['name'])}</b> — বোর্ড যাচাই\n"]
        for jid in jids:
            job = db.one("SELECT * FROM jobs WHERE id=?", (jid,))
            r = await monitor.check(pid, jid)
            out.append(f"• <b>{h(job['name'])}</b>: {texts.MONITOR_STATE.get(r['state'], r['state'])}"
                       f"{'' if r['ok'] else ' ⚠️'}\n  {h(r['detail'])}")
        await ui.show(update, "\n".join(out))


# ---------------- Job-ভিত্তিক কাজ (Admin) ----------------
def _set_job_status(jid: int, new: str, why: str):
    old = db.one("SELECT status FROM jobs WHERE id=?", (jid,))["status"]
    db.run("UPDATE jobs SET status=? WHERE id=?", (new, jid))
    if new == "active":     # আবার খোলা হলে নতুন Open-পর্ব ধরার জন্য রিসেট
        db.run("UPDATE profile_jobs SET open_episode_handled=0, monitor_state='unknown' WHERE job_id=?", (jid,))
    history.add("job_status", f"{old} → {new} ({why})", None, jid)


@require("admin")
async def job_pick_cb(update, context):
    parts = update.callback_query.data.split(":")
    cmd, jid = parts[1], int(parts[2])
    sub = parts[3] if len(parts) > 3 else None
    job = db.one("SELECT * FROM jobs WHERE id=?", (jid,)) if jid else None

    if cmd in ("pause", "resume") and jid == 0:
        src, dst = ("active", "paused") if cmd == "pause" else ("paused", "active")
        if sub != "y":
            n = db.one("SELECT COUNT(*) n FROM jobs WHERE status=?", (src,))["n"]
            await ui.show(update, f"{n}টি Job-এর অবস্থা <b>{dst}</b> করবেন?",
                          ui.kb([[("✅ হ্যাঁ", f"cj:{cmd}:0:y"), ("↩️ না", "noop")]]))
            return
        for j in db.all("SELECT id FROM jobs WHERE status=?", (src,)):
            _set_job_status(j["id"], dst, "Admin: সবগুলো")
        await ui.show(update, "✅ সম্পন্ন হয়েছে।")
        return

    if not job:
        await ui.show(update, "Job পাওয়া যায়নি।")
        return

    if cmd == "stop":
        await _stop_screen(update, context, job, sub)
        return

    labels = {"open": ("🔓 খুলবেন", "active"), "close": ("🔒 বন্ধ করবেন", "closed"),
              "pause": ("⏸️ বিরতি দেবেন", "paused"), "resume": ("⏯️ চালু করবেন", "active")}
    label, new = labels[cmd]
    if sub != "y":
        extra = "\nবন্ধ হলে Monitor ও নতুন Submission থামবে।" if new == "closed" else ""
        await ui.show(update, f"<b>{h(job['name'])}</b> {label}?{extra}",
                      ui.kb([[("✅ হ্যাঁ", f"cj:{cmd}:{jid}:y"), ("↩️ না", "noop")]]))
        return
    _set_job_status(jid, new, "Admin")
    await ui.show(update, f"✅ <b>{h(job['name'])}</b> — {texts.JOB_STATUS[new]}")


async def _stop_screen(update, context, job, sub):
    jid = job["id"]
    if sub == "send":
        await ui.show(update, f"📨 <b>{h(job['name'])}</b>-এর Job Bot-কে <code>/stopjob</code> পাঠাবেন?\n"
                              "⚠️ বাইরের Bot এই কমান্ড সমর্থন করে কিনা নিশ্চিত নয়।",
                      ui.kb([[("✅ পাঠান", f"cj:stop:{jid}:sendy"), ("↩️ না", f"cj:stop:{jid}")]]))
        return
    if sub == "sendy":
        await update.callback_query.answer("⏳ পাঠানো হচ্ছে…")
        tg = context.application.bot_data["tg"]
        try:
            async with tg.io_lock:
                client = await tg.get_client()
                bot = await tg.resolve(job["bot_chat_id"])
                async with client.conversation(bot, timeout=15) as conv:
                    await conv.send_message("/stopjob")
                    try:
                        reply = (await conv.get_response()).raw_text or ""
                    except asyncio.TimeoutError:
                        reply = ""
            history.add("admin_action", f"/stopjob পাঠানো হয়েছে। উত্তর: {reply[:200] or '—'}", None, jid)
            msg = f"📨 পাঠানো হয়েছে।\nBot-এর উত্তর: {h(reply[:300]) or 'কোনো উত্তর আসেনি'}"
        except Exception as e:
            msg = f"⚠️ পাঠানো যায়নি ({type(e).__name__})।"
        await ui.show(update, msg, ui.kb([[("⬅️ ফিরে যান", f"cj:stop:{jid}")]]))
        return
    states = db.all("SELECT p.name, pj.monitor_state, pj.last_check_at FROM profile_jobs pj "
                    "JOIN profiles p ON p.id=pj.profile_id WHERE pj.job_id=?", (jid,))
    out = [f"🛑 <b>{h(job['name'])}</b> — বন্ধের অবস্থা",
           f"Job অবস্থা: {texts.JOB_STATUS.get(job['status'], job['status'])}"]
    out += [f"• {h(s['name'])}: {texts.MONITOR_STATE.get(s['monitor_state'], '')} · {fmt_time(s['last_check_at'])}"
            for s in states] or ["কোনো Profile-এ যুক্ত নেই।"]
    rows = []
    if job["status"] != "closed":
        rows.append([("🔒 বন্ধ হিসেবে চিহ্নিত করুন", f"cj:close:{jid}")])
    rows.append([("📨 Job Bot-কে /stopjob পাঠান", f"cj:stop:{jid}:send")])
    await ui.show(update, "\n".join(out), ui.kb(rows))


@require("viewer")
async def noop(update, context):
    await ui.show(update, "↩️ কিছু পরিবর্তন করা হয়নি।")


# ---------------- /queue ----------------
@require("viewer")
async def queue_cmd(update, context):
    await _queue_view(update, 0)


@require("viewer")
async def queue_profile_cb(update, context):
    await _queue_view(update, int(update.callback_query.data.split(":")[1]))


async def _queue_view(update, pid: int):
    where, params = ("AND q.profile_id=?", (pid,)) if pid else ("", ())
    items = db.all(
        "SELECT q.*, p.name pname, j.name jname FROM job_queue q JOIN profiles p ON p.id=q.profile_id "
        f"JOIN jobs j ON j.id=q.job_id WHERE q.status<>'completed' {where} ORDER BY q.id DESC LIMIT 10", params)
    done = db.one("SELECT COUNT(*) n FROM job_queue q WHERE q.status='completed' " + where, params)["n"]
    if not items:
        await ui.show(update, f"📋 Queue-তে কোনো অসম্পূর্ণ কাজ নেই। (সম্পন্ন: {done})")
        return
    admin = auth.has_role(update.effective_user.id, "admin")
    out, rows = [f"📋 <b>Queue</b> (সম্পন্ন: {done})\n"], []
    for it in items:
        out.append(f"<b>#{it['id']}</b> 👤 {h(it['pname'])} · 🧩 {h(it['jname'])}\n"
                   f"   {texts.QUEUE_STATUS.get(it['status'], it['status'])} · চেষ্টা {it['attempt_count']}"
                   + (f"\n   ⚠️ {h(it['last_error'][:160])}" if it["last_error"] else ""))
        if admin:
            if it["status"] == "uncertain":
                rows.append([(f"✅ #{it['id']} সফল হয়েছে", f"q:ok:{it['id']}"),
                             (f"🔁 #{it['id']} হয়নি", f"q:no:{it['id']}")])
            elif it["status"] == "failed":
                rows.append([(f"🔁 #{it['id']} আবার চেষ্টা", f"q:rt:{it['id']}")])
            elif it["status"] == "pending":
                rows.append([(f"🚫 #{it['id']} বাতিল", f"q:cx:{it['id']}")])
    await ui.show(update, "\n".join(out), ui.kb(rows) if rows else None)


@require("admin")
async def queue_action_cb(update, context):
    parts = update.callback_query.data.split(":")
    act, qid = parts[1], int(parts[2])
    if len(parts) < 4:
        ask = {"ok": "✅ নিশ্চিত করছেন যে Submission <b>সফল</b> হয়েছে? (Excel মুছে যেতে পারে)",
               "no": "🔁 নিশ্চিত করছেন যে Submission <b>হয়নি</b>? আবার Queue-তে পাঠানো হবে।",
               "rt": "🔁 ব্যর্থ কাজটি আবার চেষ্টায় দেবেন?", "cx": "🚫 এই অপেক্ষমাণ কাজটি বাতিল করবেন?"}[act]
        await ui.show(update, f"<b>#{qid}</b> — {ask}",
                      ui.kb([[("✅ হ্যাঁ", f"q:{act}:{qid}:y"), ("↩️ না", "noop")]]))
        return
    if act == "ok":
        ok, msg = queue_worker.resolve_uncertain(qid, True)
    elif act == "no":
        ok, msg = queue_worker.resolve_uncertain(qid, False)
    elif act == "rt":
        ok, msg = queue_worker.retry_failed(qid)
    else:
        ok, msg = queue_worker.cancel_pending(qid)
    await ui.show(update, msg, ui.kb([[("📋 Queue", "pq:0")]]))


# ---------------- /report ----------------
@require("viewer")
async def report_cmd(update, context):
    q = {r["status"]: r["n"] for r in db.all("SELECT status, COUNT(*) n FROM job_queue GROUP BY status")}
    pstat = {r["status"]: r["n"] for r in db.all("SELECT status, COUNT(*) n FROM profiles GROUP BY status")}
    jstat = {r["status"]: r["n"] for r in db.all("SELECT status, COUNT(*) n FROM jobs GROUP BY status")}
    since = db.one("SELECT datetime('now','-1 day') d")["d"]
    day = {r["event_type"]: r["n"] for r in db.all(
        "SELECT event_type, COUNT(*) n FROM job_history WHERE created_at>=? GROUP BY event_type", (since,))}
    ex = db.one("SELECT COUNT(*) n FROM excel_files WHERE status='active'")["n"]
    out = ["📈 <b>রিপোর্ট</b>",
           f"👤 Profile: 🟢{pstat.get('active', 0)} ⏸️{pstat.get('paused', 0)} 🔴{pstat.get('stopped', 0)}",
           f"🧩 Job: 🟢{jstat.get('active', 0)} ⏸️{jstat.get('paused', 0)} 🔴{jstat.get('closed', 0)}",
           f"📊 সক্রিয় Excel: {ex}",
           f"📋 Queue: ⏳{q.get('pending', 0)} 🔄{q.get('processing', 0)} ❓{q.get('uncertain', 0)} "
           f"❌{q.get('failed', 0)} ✅{q.get('completed', 0)}",
           "\n<b>গত ২৪ ঘণ্টা:</b>",
           f"✅ সফল Submission: {day.get('submission_success', 0)}",
           f"❌ ব্যর্থ: {day.get('submission_failed', 0)} · ❓ অনিশ্চিত: {day.get('submission_uncertain', 0)}",
           f"🔔 Job অবস্থা পরিবর্তন: {day.get('monitor_state', 0)}"]
    await ui.say(update, "\n".join(out))


async def stale_cb(update, context):
    """চলমান নয় এমন ধাপের পুরোনো বাটন চাপলে।"""
    await update.callback_query.answer("এই ধাপ আর সক্রিয় নেই। মূল মেনু থেকে আবার শুরু করুন।", show_alert=True)
