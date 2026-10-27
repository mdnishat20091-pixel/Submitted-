"""📜 History: Profile অনুযায়ী ফিল্টার ও পৃষ্ঠা-ভাগ।"""
import db
import texts
import ui
from auth import require
from texts import h, fmt_time

PAGE = 8


@require("viewer")
async def history_menu(update, context):
    rows = db.all("SELECT id, name FROM profiles ORDER BY id")
    buttons = [[("📜 সব Profile", "hs:0:0")]] + [[(f"👤 {r['name']}", f"hs:{r['id']}:0")] for r in rows]
    await ui.show(update, "📜 <b>History</b>\nকোনটি দেখতে চান?", ui.kb(buttons))


@require("viewer")
async def history_page(update, context):
    _, pid, off = update.callback_query.data.split(":")
    pid, off = int(pid), int(off)
    where, params = ("WHERE h.profile_id=?", (pid,)) if pid else ("", ())
    total = db.one(f"SELECT COUNT(*) n FROM job_history h {where}", params)["n"]
    rows = db.all(
        "SELECT h.*, p.name pname, j.name jname FROM job_history h "
        "LEFT JOIN profiles p ON p.id=h.profile_id LEFT JOIN jobs j ON j.id=h.job_id "
        f"{where} ORDER BY h.id DESC LIMIT ? OFFSET ?", params + (PAGE, off))
    if not rows:
        await ui.show(update, "📜 কোনো রেকর্ড নেই।", ui.kb([[("⬅️ ফিরে যান", "hs_menu")]]))
        return
    out = [f"📜 <b>History</b> ({off + 1}–{off + len(rows)} / {total})\n"]
    for r in rows:
        who = " · ".join(x for x in (f"👤 {r['pname']}" if r["pname"] else "",
                                      f"🧩 {r['jname']}" if r["jname"] else "") if x)
        label = texts.EVENT_LABEL.get(r["event_type"], r["event_type"])
        out.append(f"🕒 {fmt_time(r['created_at'])} — <b>{h(label)}</b>" + (f"\n   {h(who)}" if who else "") +
                   f"\n   {h((r['message'] or '')[:140])}")
    nav = []
    if off > 0:
        nav.append(("⬅️ নতুনতর", f"hs:{pid}:{max(off - PAGE, 0)}"))
    if off + PAGE < total:
        nav.append(("পুরোনো ➡️", f"hs:{pid}:{off + PAGE}"))
    markup = ui.kb(([nav] if nav else []) + [[("🔎 অন্য ফিল্টার", "hs_menu")]])
    await ui.show(update, "\n".join(out), markup)
