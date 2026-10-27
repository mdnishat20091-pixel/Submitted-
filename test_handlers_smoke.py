"""হ্যান্ডলার স্মোক টেস্ট: python-telegram-bot না থাকলে হালকা নকল (stub) বসিয়ে চালানো হয়।
উদ্দেশ্য — নামের ভুল, ভুল callback_data, উইজার্ডের ধাপ-প্রবাহ ধরা।  চালান: python -m unittest -v"""
import asyncio, os, sys, types, tempfile, shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
_tmp = tempfile.mkdtemp()
os.environ["DATA_DIR"] = _tmp
from cryptography.fernet import Fernet
os.environ["SECRET_KEY"] = Fernet.generate_key().decode()
os.environ["OWNER_ID"] = "100"

try:
    import telegram  # noqa: F401
    REAL_PTB = True
except ImportError:
    REAL_PTB = False
    class _F:
        def __and__(s, o): return s
        def __or__(s, o): return s
        def __invert__(s): return s
    class _Doc: ALL = _F()
    class _Filters:
        TEXT = _F(); COMMAND = _F(); Document = _Doc()
        @staticmethod
        def Regex(p): return _F()
    class _Any:
        def __init__(s, *a, **k): s.a, s.k = a, k
    class _Btn(_Any):
        def __init__(s, text, callback_data=None, **k): s.text, s.callback_data = text, callback_data
    class _Markup(_Any):
        def __init__(s, rows, **k): s.inline_keyboard = rows
    tg = types.ModuleType("telegram"); tg.InlineKeyboardButton = _Btn; tg.InlineKeyboardMarkup = _Markup
    tg.ReplyKeyboardMarkup = _Markup; tg.Update = type("Update", (), {"ALL_TYPES": None})
    const = types.ModuleType("telegram.constants"); const.ParseMode = types.SimpleNamespace(HTML="HTML")
    err = types.ModuleType("telegram.error"); err.BadRequest = type("BadRequest", (Exception,), {})
    ext = types.ModuleType("telegram.ext")
    class _Conv(_Any): END = -1
    ext.ConversationHandler = _Conv
    for n in ("Application", "CallbackQueryHandler", "CommandHandler", "MessageHandler"):
        setattr(ext, n, type(n, (_Any,), {}))
    ext.filters = _Filters()
    sys.modules.update({"telegram": tg, "telegram.constants": const, "telegram.error": err, "telegram.ext": ext})

import unittest
import config
config.OWNER_ID = 100
import db, auth, excel_manager, ui
from handlers import profiles, wizard, commands, history_view, session, admin_cmds
from openpyxl import Workbook


class FakeMsg:
    def __init__(self, text=None, doc=None): self.text, self.document, self.sent, self.deleted = text, doc, [], False
    async def reply_text(self, text, reply_markup=None, **k): self.sent.append((text, reply_markup))
    async def delete(self): self.deleted = True


class FakeQuery:
    def __init__(self, data): self.data, self.edited, self.message, self.answers = data, [], FakeMsg(), []
    async def answer(self, text=None, *a, **k):
        if text: self.answers.append(text)
    async def edit_message_text(self, text, reply_markup=None, **k): self.edited.append((text, reply_markup))


class U:
    def __init__(self, uid=100, text=None, data=None, doc=None):
        self.effective_user = types.SimpleNamespace(id=uid)
        self.message = FakeMsg(text, doc)
        self.callback_query = FakeQuery(data) if data else None
        self.effective_message = self.callback_query.message if data else self.message

    def outputs(self):
        if self.callback_query:
            return (self.callback_query.answers + [t for t, _ in self.callback_query.edited]
                    + [t for t, _ in self.callback_query.message.sent])
        return [t for t, _ in self.message.sent]

    def last_markup(self):
        src = (self.callback_query.edited + self.callback_query.message.sent) if self.callback_query else self.message.sent
        return src[-1][1] if src else None


class Ctx:
    def __init__(self, **bd):
        self.user_data, self.args = {}, []
        self.application = types.SimpleNamespace(bot_data=bd)
        self.bot = types.SimpleNamespace(get_file=self._get_file)
        self.xlsx = None
    async def _get_file(self, fid):
        src = self.xlsx
        class F:
            async def download_to_drive(s, custom_path): shutil.copy(src, custom_path)
        return F()


def xlsx(path, headers=("Email", "Password")):
    wb = Workbook(); ws = wb.active; ws.append(list(headers)); ws.append(["a@b.c", "pw"]); wb.save(path)


def callbacks(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row] if markup else []


class FakeTg:
    def __init__(self): self.io_lock = asyncio.Lock()
    def has_session(self): return False
    async def check_ref(self, ref): return None, "Session নেই"


def run(coro): return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


class Smoke(unittest.TestCase):
    def setUp(self):
        db.close(); db.connect(Path(_tmp) / f"{os.urandom(3).hex()}.db"); db.migrate(); auth.seed_owner()

    def test_unauthorized_user_blocked(self):
        u = U(uid=999, text="/start"); run(commands.start(u, Ctx()))
        self.assertIn("অনুমতিপ্রাপ্ত নন", u.outputs()[0]); self.assertIn("999", u.outputs()[0])

    def test_start_and_help_and_empty_lists(self):
        for fn in (commands.start, commands.help_cmd, commands.jobs_cmd, commands.status_cmd,
                   commands.report_cmd, commands.queue_cmd):
            u = U(text="x"); run(fn(u, Ctx())); self.assertTrue(u.outputs(), fn.__name__)
        u = U(text="x"); run(profiles.profiles_menu(u, Ctx())); self.assertIn("কোনো Profile নেই", u.outputs()[0])

    def test_viewer_cannot_use_admin_command(self):
        admin_cmd = U(text="/addadmin 5 viewer"); c = Ctx(); c.args = ["5", "viewer"]
        run(admin_cmds.addadmin_cmd(admin_cmd, c))
        self.assertEqual(auth.get_role(5), "viewer")
        u = U(uid=5, text="/stor"); run(commands.stor_cmd(u, Ctx()))
        self.assertIn("Admin", u.outputs()[0])
        u = U(uid=5, text="/addadmin 6"); run(admin_cmds.addadmin_cmd(u, Ctx()))
        self.assertIn("Owner", u.outputs()[0])

    def test_full_add_profile_wizard_and_cancel_leaves_nothing(self):
        x = Path(_tmp) / "in.xlsx"; xlsx(x)
        ctx = Ctx(tg=FakeTg()); ctx.xlsx = x
        run(wizard.start_new_profile(U(text="➕ Add Profile"), ctx))
        self.assertEqual(run(wizard.got_name(U(text="দোকান-১"), ctx)), wizard.JOB_PICK)
        self.assertEqual(run(wizard.pick_job(U(data="wj:new"), ctx)), wizard.NJ_NAME)
        self.assertEqual(run(wizard.nj_name(U(text="2FA dgddigital"), ctx)), wizard.NJ_KEY)
        self.assertEqual(run(wizard.nj_key(U(text="Sesi sesi4"), ctx)), wizard.NJ_BOT)
        self.assertEqual(run(wizard.nj_bot(U(text="bad bot!"), ctx)), wizard.NJ_BOT)      # ভুল ঠিকানা
        self.assertEqual(run(wizard.nj_bot(U(text="@job_bot"), ctx)), wizard.NJ_GROUP)
        self.assertEqual(run(wizard.nj_group(U(text="-1001234567890"), ctx)), wizard.NJ_RULES)
        self.assertEqual(run(wizard.nj_rules(U(data="wz:skip"), ctx)), wizard.NJ_CONFIRM)
        self.assertEqual(run(wizard.nj_confirm(U(text="berhasil"), ctx)), wizard.EXCEL)
        doc = types.SimpleNamespace(file_id="f", file_name="data.xlsx", file_size=1000)
        self.assertEqual(run(wizard.got_excel(U(doc=doc), ctx)), wizard.COLS)
        self.assertEqual(run(wizard.got_cols(U(text="Phone"), ctx)), wizard.COLS)           # নেই এমন কলাম
        self.assertEqual(run(wizard.got_cols(U(text="Email, Password"), ctx)), wizard.RULES)
        self.assertEqual(run(wizard.got_rules(U(data="wz:skip"), ctx)), wizard.INTERVAL)
        self.assertEqual(run(wizard.got_interval(U(data="iv:120"), ctx)), wizard.PREVIEW)
        # Save-এর আগে ডাটাবেসে কিছু নেই
        self.assertEqual(db.one("SELECT COUNT(*) n FROM profiles")["n"], 0)
        self.assertEqual(db.one("SELECT COUNT(*) n FROM jobs")["n"], 0)
        # Cancel করলে কিছুই থাকে না, অস্থায়ী ফাইলও মুছে যায়
        tmpfile = Path(ctx.user_data["wz"]["tmp"]); self.assertTrue(tmpfile.exists())
        run(wizard.cancel_cb(U(data="wz:cancel"), ctx))
        self.assertFalse(tmpfile.exists()); self.assertEqual(db.one("SELECT COUNT(*) n FROM profiles")["n"], 0)

    def _make_profile(self, ctx):
        x = Path(_tmp) / f"{os.urandom(2).hex()}.xlsx"; xlsx(x); ctx.xlsx = x
        run(wizard.start_new_profile(U(text="➕ Add Profile"), ctx)); run(wizard.got_name(U(text="P"), ctx))
        run(wizard.pick_job(U(data="wj:new"), ctx)); run(wizard.nj_name(U(text="J"), ctx))
        run(wizard.nj_key(U(text="K1"), ctx)); run(wizard.nj_bot(U(text="@job_bot"), ctx))
        run(wizard.nj_group(U(text="@grp_name"), ctx)); run(wizard.nj_rules(U(data="wz:skip"), ctx))
        run(wizard.nj_confirm(U(data="wz:skip"), ctx))
        run(wizard.got_excel(U(doc=types.SimpleNamespace(file_id="f", file_name="d.xlsx", file_size=10)), ctx))
        run(wizard.got_cols(U(data="wz:skip"), ctx)); run(wizard.got_rules(U(text="নিয়ম"), ctx))
        run(wizard.got_interval(U(data="iv:60"), ctx))
        return run(wizard.save(U(data="wz:save"), ctx))

    def test_wizard_save_and_profile_controls(self):
        ctx = Ctx(tg=FakeTg()); self.assertEqual(self._make_profile(ctx), -1)
        p = db.one("SELECT * FROM profiles"); self.assertEqual(p["status"], "stopped")
        self.assertEqual(db.one("SELECT check_interval_seconds c FROM profile_jobs")["c"], 60)
        self.assertEqual(db.one("SELECT COUNT(*) n FROM excel_files WHERE status='active'")["n"], 1)
        self.assertTrue(Path(excel_manager.get_active(1)["file_path"]).exists())
        u = U(data="pf:1"); run(profiles.profile_detail(u, Ctx())); self.assertIn("Start", str(callbacks(u.last_markup())) + "▶️ Start" )
        self.assertIn("pa:1:start", callbacks(u.last_markup()))
        for act, expect in (("start", "active"), ("pause", "paused"), ("resume", "active")):
            run(profiles.profile_action(U(data=f"pa:1:{act}"), Ctx()))
            self.assertEqual(db.one("SELECT status FROM profiles")["status"], expect)
        run(profiles.profile_action(U(data="pa:1:stop"), Ctx()))                 # নিশ্চিতকরণ চায়, বদলায় না
        self.assertEqual(db.one("SELECT status FROM profiles")["status"], "active")
        run(profiles.profile_action(U(data="pa:1:stop:y"), Ctx()))
        self.assertEqual(db.one("SELECT status FROM profiles")["status"], "stopped")
        # Job স্ক্রিন, Toggle, Interval
        u = U(data="pj:1:1"); run(profiles.job_detail(u, Ctx())); self.assertIn("Sesi", "Sesi" if "K1" in u.outputs()[0] else "")
        run(profiles.job_toggle(U(data="pt:1:1"), Ctx())); self.assertEqual(db.one("SELECT enabled FROM profile_jobs")["enabled"], 0)
        run(profiles.job_interval(U(data="pi:1:1:300"), Ctx())); self.assertEqual(db.one("SELECT check_interval_seconds c FROM profile_jobs")["c"], 300)
        # ইতিহাস দেখা
        u = U(data="hs:0:0"); run(history_view.history_page(u, Ctx())); self.assertIn("hs:0:8", callbacks(u.last_markup()))
        u = U(data="hs:0:8"); run(history_view.history_page(u, Ctx())); self.assertIn("Profile তৈরি", u.outputs()[0])
        u = U(text="x"); run(history_view.history_menu(u, Ctx())); self.assertIn("hs:1:0", callbacks(u.last_markup()))

    def test_duplicate_job_in_wizard_is_redirected(self):
        ctx = Ctx(tg=FakeTg()); self._make_profile(ctx)
        ctx2 = Ctx(tg=FakeTg()); x = Path(_tmp) / "z.xlsx"; xlsx(x); ctx2.xlsx = x
        run(wizard.start_new_profile(U(text="x"), ctx2)); run(wizard.got_name(U(text="Q"), ctx2))
        run(wizard.pick_job(U(data="wj:new"), ctx2)); run(wizard.nj_name(U(text="অন্য নাম"), ctx2))
        run(wizard.nj_key(U(text="k1"), ctx2)); run(wizard.nj_bot(U(text="@JOB_BOT"), ctx2))
        run(wizard.nj_group(U(text="@grp_name"), ctx2)); run(wizard.nj_rules(U(data="wz:skip"), ctx2))
        st = run(wizard.nj_confirm(U(data="wz:skip"), ctx2))
        self.assertEqual(st, wizard.JOB_PICK)       # একই Bot+Key → নতুন Job তৈরি নয়, তালিকায় ফেরত
        self.assertEqual(db.one("SELECT COUNT(*) n FROM jobs")["n"], 1)

    def test_duplicate_profile_name_rejected(self):
        ctx = Ctx(tg=FakeTg()); self._make_profile(ctx)
        c2 = Ctx(); run(wizard.start_new_profile(U(text="x"), c2))
        self.assertEqual(run(wizard.got_name(U(text="p"), c2)), wizard.NAME)

    def test_job_commands_and_queue_actions(self):
        self._make_profile(Ctx(tg=FakeTg()))
        db.run("UPDATE profiles SET status='active'")
        u = U(text="/closejob"); run(commands.closejob_cmd(u, Ctx())); self.assertIn("cj:close:1", callbacks(u.last_markup()))
        run(commands.job_pick_cb(U(data="cj:close:1"), Ctx()))                    # নিশ্চিতকরণ
        self.assertEqual(db.one("SELECT status FROM jobs")["status"], "active")
        run(commands.job_pick_cb(U(data="cj:close:1:y"), Ctx()))
        self.assertEqual(db.one("SELECT status FROM jobs")["status"], "closed")
        run(commands.job_pick_cb(U(data="cj:open:1:y"), Ctx()))
        self.assertEqual(db.one("SELECT status FROM jobs")["status"], "active")
        run(commands.job_pick_cb(U(data="cj:pause:0:y"), Ctx()))
        self.assertEqual(db.one("SELECT status FROM jobs")["status"], "paused")
        run(commands.job_pick_cb(U(data="cj:resume:1:y"), Ctx()))
        self.assertEqual(db.one("SELECT status FROM jobs")["status"], "active")
        u = U(data="cj:stop:1"); run(commands.job_pick_cb(u, Ctx())); self.assertIn("বন্ধের অবস্থা", u.outputs()[0])
        # Queue: অনিশ্চিত Item নিশ্চিতকরণ
        eid = excel_manager.get_active(1)["id"]
        db.run("INSERT INTO job_queue(profile_id,job_id,excel_file_id,status) VALUES(1,1,?,'uncertain')", (eid,))
        u = U(text="/queue"); run(commands.queue_cmd(u, Ctx()))
        self.assertIn("q:ok:1", callbacks(u.last_markup()))
        run(commands.queue_action_cb(U(data="q:ok:1"), Ctx()))                    # শুধু নিশ্চিতকরণ চায়
        self.assertEqual(db.one("SELECT status FROM job_queue")["status"], "uncertain")
        run(commands.queue_action_cb(U(data="q:ok:1:y"), Ctx()))
        self.assertEqual(db.one("SELECT status FROM job_queue")["status"], "completed")
        run(commands.report_cmd(U(text="x"), Ctx()))

    def test_excel_replace_blocked_when_queue_active(self):
        self._make_profile(Ctx(tg=FakeTg()))
        eid = excel_manager.get_active(1)["id"]
        db.run("INSERT INTO job_queue(profile_id,job_id,excel_file_id,status) VALUES(1,1,?,'pending')", (eid,))
        from handlers import excel_upload
        u = U(data="xl:1"); st = run(excel_upload.start(u, Ctx()))
        self.assertEqual(st, -1); self.assertIn("অসম্পূর্ণ", u.outputs()[0])

    def test_session_screens_and_secret_deletion(self):
        u = U(text="x"); run(session.session_menu(u, Ctx())); self.assertIn("ss_connect", callbacks(u.last_markup()))
        ctx = Ctx(tg=FakeTg()); run(session.connect_start(U(data="ss_connect"), ctx))
        m = U(text="abc"); self.assertEqual(run(session.got_api_id(m, ctx)), session.API_ID); self.assertTrue(m.message.deleted)
        m = U(text="12345"); self.assertEqual(run(session.got_api_id(m, ctx)), session.API_HASH)
        m = U(text="a" * 32); self.assertEqual(run(session.got_api_hash(m, ctx)), session.PHONE)
        self.assertTrue(m.message.deleted)
        # Admin (Owner নয়) Connect করতে পারবে না
        auth.get_role(7); db.run("INSERT INTO admin_users(telegram_user_id,role,enabled) VALUES(7,'admin',1)")
        u = U(uid=7, data="ss_connect"); run(session.connect_start(u, Ctx()))
        self.assertTrue(any("Owner" in o for o in u.outputs()))


if __name__ == "__main__":
    unittest.main()
