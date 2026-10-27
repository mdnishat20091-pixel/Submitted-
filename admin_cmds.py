"""শুধু Owner: /admins, /addadmin <ID> [admin|viewer], /removeadmin <ID>"""
import db
import history
import texts
import ui
from auth import require, get_role
from texts import h


@require("owner")
async def admins_cmd(update, context):
    rows = db.all("SELECT * FROM admin_users ORDER BY role DESC, telegram_user_id")
    out = ["👥 <b>অনুমোদিত ব্যবহারকারী</b>\n"]
    for r in rows:
        out.append(f"<code>{r['telegram_user_id']}</code> — {r['role']}" + ("" if r["enabled"] else " (বন্ধ)"))
    out.append("\nযোগ: <code>/addadmin ID admin</code> বা <code>/addadmin ID viewer</code>\n"
               "সরানো: <code>/removeadmin ID</code>")
    await ui.say(update, "\n".join(out))


@require("owner")
async def addadmin_cmd(update, context):
    args = context.args or []
    if not args or not args[0].lstrip("-").isdigit():
        await ui.say(update, "ব্যবহার: <code>/addadmin ID [admin|viewer]</code>")
        return
    uid = int(args[0])
    role = (args[1] if len(args) > 1 else "admin").lower()
    if role not in ("admin", "viewer"):
        await ui.say(update, "ভূমিকা হতে হবে <code>admin</code> বা <code>viewer</code>।")
        return
    if get_role(uid) == "owner":
        await ui.say(update, "Owner-এর ভূমিকা বদলানো যায় না।")
        return
    db.run("INSERT INTO admin_users(telegram_user_id, role, enabled, created_at) VALUES(?,?,1,?) "
           "ON CONFLICT(telegram_user_id) DO UPDATE SET role=excluded.role, enabled=1", (uid, role, db.now_utc()))
    history.add("admin_action", f"ব্যবহারকারী {uid}-কে {role} করা হয়েছে")
    await ui.say(update, f"✅ <code>{uid}</code> এখন <b>{role}</b>।")


@require("owner")
async def removeadmin_cmd(update, context):
    args = context.args or []
    if not args or not args[0].lstrip("-").isdigit():
        await ui.say(update, "ব্যবহার: <code>/removeadmin ID</code>")
        return
    uid = int(args[0])
    if get_role(uid) == "owner":
        await ui.say(update, "Owner-কে সরানো যায় না।")
        return
    db.run("UPDATE admin_users SET enabled=0 WHERE telegram_user_id=?", (uid,))
    history.add("admin_action", f"ব্যবহারকারী {uid}-এর অনুমতি বন্ধ করা হয়েছে")
    await ui.say(update, f"✅ <code>{uid}</code>-এর অনুমতি বন্ধ করা হয়েছে।")
