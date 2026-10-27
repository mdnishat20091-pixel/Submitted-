"""👤 Profile: তালিকা, বিস্তারিত, Start/Pause/Resume/Stop, Job-ভিত্তিক নিয়ন্ত্রণ।"""
import config
import db
import history
import auth
import excel_manager
import texts
import ui
from auth import require
from texts import h, fmt_time


def _can_edit(update) -> bool:
    return auth.has_role(update.effective_user.id, "admin")


def profile_screen(pid: int, editable: bool):
    p = db.one("SELECT * FROM profiles WHERE id=?", (pid,))
    if not p:
        return "Profile পাওয়া যায়নি।", ui.kb([[("⬅️ ফিরে যান", "pf_list")]])
    ex = excel_manager.get_active(pid)
    counts = {r["status"]: r["n"] for r in db.all(
        "SELECT status, COUNT(*) n FROM job_queue WHERE profile_id=? GROUP BY status", (pid,))}
    jobs = db.all("SELECT j.*, pj.monitor_state, pj.last_check_at, pj.enabled, pj.check_interval_seconds "
                  "FROM profile_jobs pj JOIN jobs j ON j.id=pj.job_id WHERE pj.profile_id=? ORDER BY j.id", (pid,))
    lines = [f"👤 <b>{h(p['name'])}</b>", f"অবস্থা: {texts.PROFILE_STATUS.get(p['status'], p['status'])}"]
    lines.append("📊 Excel: " + (f"✅ {h(ex['original_name'])} ({ex['row_count']} সারি)" if ex else "❌ নেই"))
    lines.append(f"📋 Queue: ⏳{counts.get('pending', 0)} 🔄{counts.get('processing', 0)} "
                 f"❓{counts.get('uncertain', 0)} ❌{counts.get('failed', 0)} ✅{counts.get('completed', 0)}")
    if p["rules_text"]:
        lines.append(f"📝 Rules: {h(p['rules_text'][:200])}")
    if p["status"] == "active" and not _session_ok():
        lines.append("⚠️ Telegram Session সংযুক্ত নেই — Monitor কাজ করবে না।")
    lines.append("\n<b>Jobs:</b>" if jobs else "\nএই Profile-এ কোনো Job নেই।")
    rows = []
    for j in jobs:
        off = "" if j["enabled"] else " (Monitor বন্ধ)"
        lines.append(f"• {h(texts.job_label(j))} — {texts.MONITOR_STATE.get(j['monitor_state'], '')}"
                     f" · শেষ Check: {fmt_time(j['last_check_at'])}{off}")
        rows.append([(f"🧩 {j['name'][:28]}", f"pj:{pid}:{j['id']}")])
    if editable:
        st = p["status"]
        ctl = []
        if st == "stopped":
            ctl.append(("▶️ Start", f"pa:{pid}:start"))
        if st == "active":
            ctl.append(("⏸️ Pause", f"pa:{pid}:pause"))
        if st == "paused":
            ctl.append(("⏯️ Resume", f"pa:{pid}:resume"))
        if st in ("active", "paused"):
            ctl.append(("⏹️ Stop", f"pa:{pid}:stop"))
        rows.append(ctl)
        rows.append([("📊 Excel আপলোড", f"xl:{pid}"), ("➕ Job যোগ", f"pj_add:{pid}")])
        rows.append([("🔎 এখনই Check", f"pc:{pid}"), ("📋 Queue", f"pq:{pid}")])
    else:
        rows.append([("📋 Queue", f"pq:{pid}")])
    rows.append([("⬅️ Profile তালিকা", "pf_list")])
    return "\n".join(lines), ui.kb(rows)


def _session_ok() -> bool:
    return db.one("SELECT 1 FROM telegram_sessions WHERE status='connected'") is not None


@require("viewer")
async def profiles_menu(update, context):
    rows = db.all("SELECT * FROM profiles ORDER BY id")
    if not rows:
        await ui.show(update, "কোনো Profile নেই।\n➕ <b>Add Profile</b> থেকে নতুন তৈরি করুন।")
        return
    icon = {"active": "🟢", "paused": "⏸️", "stopped": "🔴"}
    buttons = [[(f"{icon.get(r['status'], '')} {r['name']}", f"pf:{r['id']}")] for r in rows]
    await ui.show(update, "👤 <b>আপনার Profile সমূহ</b>\nদেখতে একটি নির্বাচন করুন:", ui.kb(buttons))


@require("viewer")
async def profile_detail(update, context):
    pid = int(update.callback_query.data.split(":")[1])
    text, markup = profile_screen(pid, _can_edit(update))
    await ui.show(update, text, markup)


@require("admin")
async def profile_action(update, context):
    parts = update.callback_query.data.split(":")
    pid, act = int(parts[1]), parts[2]
    confirmed = len(parts) > 3 and parts[3] == "y"
    p = db.one("SELECT * FROM profiles WHERE id=?", (pid,))
    if not p:
        await ui.show(update, "Profile পাওয়া যায়নি।")
        return
    if act == "stop" and not confirmed:
        await ui.show(update,
                      f"⏹️ <b>{h(p['name'])}</b> বন্ধ করবেন?\nMonitor ও নতুন Submission থেমে যাবে। "
                      "Queue-র কাজ মুছবে না।",
                      ui.kb([[("✅ হ্যাঁ, বন্ধ করুন", f"pa:{pid}:stop:y"), ("↩️ না", f"pf:{pid}")]]))
        return
    new = {"start": "active", "resume": "active", "pause": "paused", "stop": "stopped"}.get(act)
    if not new:
        return
    db.run("UPDATE profiles SET status=?, updated_at=? WHERE id=?", (new, db.now_utc(), pid))
    history.add("profile_status", f"{p['status']} → {new}", pid)
    text, markup = profile_screen(pid, True)
    await ui.show(update, text, markup)


def _job_screen(pid: int, jid: int, editable: bool):
    pj = db.one("SELECT * FROM profile_jobs WHERE profile_id=? AND job_id=?", (pid, jid))
    j = db.one("SELECT * FROM jobs WHERE id=?", (jid,))
    if not (pj and j):
        return "Job পাওয়া যায়নি।", ui.kb([[("⬅️ ফিরে যান", f"pf:{pid}")]])
    text = (f"🧩 <b>{h(j['name'])}</b>  (#{j['id']})\n"
            f"External Job ID: {h(j['external_job_key'] or '—')}\n"
            f"Job Bot: {h(j['bot_chat_id'])}\nGroup: {h(j['group_chat_id'])}\n"
            f"Job অবস্থা: {texts.JOB_STATUS.get(j['status'], j['status'])}\n"
            f"Monitor অবস্থা: {texts.MONITOR_STATE.get(pj['monitor_state'], '')}\n"
            f"Monitor: {'চালু' if pj['enabled'] else 'বন্ধ'} · প্রতি {pj['check_interval_seconds']} সেকেন্ডে\n"
            f"শেষ Check: {fmt_time(pj['last_check_at'])}\nশেষ ফলাফল: {h(pj['last_result'] or '—')}\n"
            f"Confirmation শব্দ: {h(j['confirm_keyword'] or 'দেওয়া নেই (Submission অনিশ্চিত থাকবে)')}")
    if j["rules_text"]:
        text += f"\n📝 Rules: {h(j['rules_text'][:300])}"
    rows = []
    if editable:
        rows.append([("🔎 এখনই Check", f"pc:{pid}:{jid}"),
                     (("⏸️ Monitor বন্ধ" if pj["enabled"] else "▶️ Monitor চালু"), f"pt:{pid}:{jid}")])
        rows.append([(("✔ " if pj["check_interval_seconds"] == s else "") + f"{s}s", f"pi:{pid}:{jid}:{s}")
                     for s in config.INTERVAL_CHOICES])
    rows.append([("⬅️ Profile", f"pf:{pid}")])
    return text, ui.kb(rows)


@require("viewer")
async def job_detail(update, context):
    _, pid, jid = update.callback_query.data.split(":")
    text, markup = _job_screen(int(pid), int(jid), _can_edit(update))
    await ui.show(update, text, markup)


@require("admin")
async def job_toggle(update, context):
    _, pid, jid = update.callback_query.data.split(":")
    db.run("UPDATE profile_jobs SET enabled=1-enabled WHERE profile_id=? AND job_id=?", (pid, jid))
    history.add("profile_status", "Job Monitor চালু/বন্ধ পরিবর্তন", int(pid), int(jid))
    text, markup = _job_screen(int(pid), int(jid), True)
    await ui.show(update, text, markup)


@require("admin")
async def job_interval(update, context):
    _, pid, jid, sec = update.callback_query.data.split(":")
    if int(sec) not in config.INTERVAL_CHOICES:
        return
    db.run("UPDATE profile_jobs SET check_interval_seconds=? WHERE profile_id=? AND job_id=?", (int(sec), pid, jid))
    text, markup = _job_screen(int(pid), int(jid), True)
    await ui.show(update, text, markup)


@require("admin")
async def check_now(update, context):
    """pc:<pid> (Profile-এর সব Job) বা pc:<pid>:<jid> (একটি Job)"""
    parts = update.callback_query.data.split(":")
    pid = int(parts[1])
    monitor = context.application.bot_data["monitor"]
    if len(parts) > 2:
        jids = [int(parts[2])]
    else:
        jids = [r["job_id"] for r in db.all("SELECT job_id FROM profile_jobs WHERE profile_id=?", (pid,))]
    if not jids:
        await update.callback_query.answer("এই Profile-এ কোনো Job নেই।", show_alert=True)
        return
    await update.callback_query.answer("⏳ Check চলছে…")
    lines = []
    for jid in jids:
        job = db.one("SELECT * FROM jobs WHERE id=?", (jid,))
        r = await monitor.check(pid, jid)
        mark = "" if r["ok"] else " ⚠️"
        lines.append(f"• <b>{h(job['name'])}</b>: {texts.MONITOR_STATE.get(r['state'], r['state'])}{mark}\n"
                     f"  {h(r['detail'])}")
    back = f"pj:{pid}:{jids[0]}" if len(jids) == 1 else f"pf:{pid}"
    await ui.show(update, "🔎 <b>Check ফলাফল</b>\n\n" + "\n".join(lines), ui.kb([[("⬅️ ফিরে যান", back)]]))
