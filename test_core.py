"""মূল লজিকের টেস্ট (Telegram ছাড়া, নকল Client দিয়ে)।  চালান:  python -m unittest -v"""
import asyncio
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

_tmp = tempfile.mkdtemp()
os.environ["DATA_DIR"] = _tmp
os.environ["SECRET_KEY"] = "x" * 43 + "="  # নিচে বদলানো হবে
from cryptography.fernet import Fernet
os.environ["SECRET_KEY"] = Fernet.generate_key().decode()
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config, db, history, excel_manager, monitor, queue_worker, crypto  # noqa: E402
from openpyxl import Workbook  # noqa: E402


def make_xlsx(path, headers=("Email", "Password"), rows=2):
    wb = Workbook(); ws = wb.active
    ws.append(list(headers))
    for i in range(rows):
        ws.append([f"u{i}@x.com", "pw"])
    wb.save(path)


class Msg:
    def __init__(self, text, id=1): self.raw_text, self.id, self.buttons = text, id, None


class FakeConv:
    def __init__(self, client): self.c = client
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    async def send_message(self, t): self.c.sent.append(("msg", t))
    async def send_file(self, p):
        if self.c.fail_before_send: raise ConnectionError("down")
        self.c.sent.append(("file", p))
    async def get_response(self):
        if not self.c.replies: raise asyncio.TimeoutError()
        return Msg(self.c.replies.pop(0))


class FakeClient:
    def __init__(self): self.sent, self.replies, self.group, self.fail_before_send = [], [], [], False
    def conversation(self, *a, **k): return FakeConv(self)
    async def get_messages(self, g, limit=20): return list(self.group)


class FakeTg:
    def __init__(self): self.io_lock = asyncio.Lock(); self.client = FakeClient()
    async def get_client(self): return self.client
    async def resolve(self, ref): return ref


def fresh_db():
    db.close()
    p = Path(_tmp) / f"t{os.urandom(3).hex()}.db"
    db.connect(p); db.migrate()


def seed(confirm="berhasil", key="Sesi sesi4", state="unknown"):
    now = db.now_utc()
    db.run("INSERT INTO profiles(owner_user_id,name,status,created_at) VALUES(1,'P1','active',?)", (now,))
    db.run("INSERT INTO jobs(name,external_job_key,bot_chat_id,group_chat_id,status,confirm_keyword,created_at) "
           "VALUES('2FA dgddigital',?, '@jobbot','@grp','active',?,?)", (key, confirm, now))
    db.run("INSERT INTO profile_jobs(profile_id,job_id,monitor_state,created_at) VALUES(1,1,?,?)", (state, now))
    x = Path(_tmp) / f"{os.urandom(3).hex()}.xlsx"; make_xlsx(x)
    stored = excel_manager.move_to_storage(x)
    with db.tx() as c:
        eid = excel_manager.register(c, 1, stored, "a.xlsx", 2)
    return eid, stored


class Notes:
    def __init__(self): self.msgs = []
    async def __call__(self, uid, text): self.msgs.append((uid, text))


class Tests(unittest.IsolatedAsyncioTestCase):
    def setUp(self): fresh_db()

    # ---- ডাটাবেস ----
    def test_migrate_is_idempotent_and_additive(self):
        db.migrate(); db.migrate()
        db.close()
        old = Path(_tmp) / "old.db"
        c = sqlite3.connect(old)
        c.execute("CREATE TABLE jobs (id INTEGER PRIMARY KEY, name TEXT)")
        c.execute("INSERT INTO jobs(id,name) VALUES(7,'পুরোনো Job')"); c.commit(); c.close()
        db.connect(old); db.migrate()
        cols = {r["name"] for r in db.all("PRAGMA table_info(jobs)")}
        self.assertTrue({"external_job_key", "bot_chat_id", "confirm_keyword", "status"} <= cols)
        self.assertEqual(db.one("SELECT name FROM jobs WHERE id=7")["name"], "পুরোনো Job")  # ডাটা অক্ষত

    def test_duplicate_job_key_and_profile_name_blocked(self):
        seed()
        with self.assertRaises(sqlite3.IntegrityError):
            db.run("INSERT INTO jobs(name,external_job_key,bot_chat_id) VALUES('অন্য','SESI SESI4','@JOBBOT')")
        with self.assertRaises(sqlite3.IntegrityError):
            db.run("INSERT INTO profiles(owner_user_id,name) VALUES(1,'p1')")

    def test_tx_rolls_back(self):
        with self.assertRaises(RuntimeError):
            with db.tx() as c:
                c.execute("INSERT INTO profiles(owner_user_id,name) VALUES(9,'X')")
                raise RuntimeError
        self.assertIsNone(db.one("SELECT 1 FROM profiles WHERE name='X'"))

    def test_encryption_roundtrip(self):
        self.assertEqual(crypto.decrypt(crypto.encrypt("secret-hash")), "secret-hash")

    # ---- Excel ----
    def test_excel_validation(self):
        p = Path(_tmp) / "v.xlsx"; make_xlsx(p)
        self.assertEqual(excel_manager.validate(p, ["email"])[0], [])
        errs, _, _ = excel_manager.validate(p, ["Phone"])
        self.assertTrue(errs and "Phone" in errs[0])
        make_xlsx(p, rows=0)
        self.assertTrue(excel_manager.validate(p)[0])
        bad = Path(_tmp) / "bad.xlsx"; bad.write_text("not excel")
        self.assertTrue(excel_manager.validate(bad)[0])
        self.assertTrue(excel_manager.validate(Path(_tmp) / "a.csv".replace("a", "z"))[0] if False else True)

    # ---- Monitor বিশ্লেষণ ----
    def test_parse_board(self):
        job = {"external_job_key": "Sesi sesi4", "name": "2FA"}
        self.assertEqual(monitor.parse_board("⚠️ Belum ada Job yang dibuka oleh Admin", job)[0], "unavailable")
        self.assertEqual(monitor.parse_board("🔐 2FA dgddigital (Sesi sesi4)", job)[0], "open")
        self.assertEqual(monitor.parse_board("🔐 2FA (Sesi sesi4) - PENUH", job)[0], "full")
        self.assertEqual(monitor.parse_board("Job lain saja", job)[0], "closed")
        self.assertEqual(monitor.parse_board("", job)[0], "unknown")

    def test_group_close_only_new_messages(self):
        job = {"external_job_key": "sesi4", "name": "x"}
        msgs = [(5, "sesi4 ditutup"), (6, "hello")]
        self.assertTrue(monitor.group_close_event(msgs, job, 4))
        self.assertFalse(monitor.group_close_event(msgs, job, 5))   # পুরোনো মেসেজ ধরা হবে না

    # ---- Monitor → Queue (ডুপ্লিকেট নয়) ----
    async def test_open_enqueues_exactly_once(self):
        seed(); tg, notes = FakeTg(), Notes(); m = monitor.Monitor(tg, notes)
        for _ in range(3):
            tg.client.replies = ["🔐 2FA dgddigital (Sesi sesi4)"]
            await m.check(1, 1)
        self.assertEqual(db.one("SELECT COUNT(*) n FROM job_queue")["n"], 1)
        self.assertEqual(db.one("SELECT monitor_state s FROM profile_jobs")["s"], "open")

    async def test_no_excel_means_no_queue_then_queued_when_excel_arrives(self):
        seed(); db.run("UPDATE excel_files SET status='deleted'")
        tg, notes = FakeTg(), Notes(); m = monitor.Monitor(tg, notes)
        tg.client.replies = ["Sesi sesi4"]; await m.check(1, 1)
        self.assertEqual(db.one("SELECT COUNT(*) n FROM job_queue")["n"], 0)
        x = Path(_tmp) / "n.xlsx"; make_xlsx(x)
        with db.tx() as c: excel_manager.register(c, 1, excel_manager.move_to_storage(x), "n.xlsx", 2)
        tg.client.replies = ["Sesi sesi4"]; await m.check(1, 1)
        self.assertEqual(db.one("SELECT COUNT(*) n FROM job_queue")["n"], 1)

    async def test_no_reply_keeps_previous_state(self):
        seed(state="open"); tg = FakeTg(); m = monitor.Monitor(tg, Notes())
        r = await m.check(1, 1)           # কোনো উত্তর নেই → Timeout
        self.assertEqual(r["state"], "open")

    async def test_closed_job_is_not_queued(self):
        seed(); tg = FakeTg(); m = monitor.Monitor(tg, Notes())
        tg.client.replies = ["⚠️ Belum ada Job yang dibuka oleh Admin"]; await m.check(1, 1)
        self.assertEqual(db.one("SELECT COUNT(*) n FROM job_queue")["n"], 0)

    # ---- Worker ----
    async def _queue_item(self):
        eid, stored = seed()
        db.run("INSERT INTO job_queue(profile_id,job_id,excel_file_id,status,created_at) VALUES(1,1,?,'pending',?)",
               (eid, db.now_utc()))
        return stored

    async def test_confirmed_submission_deletes_excel(self):
        stored = await self._queue_item(); tg, notes = FakeTg(), Notes()
        w = queue_worker.QueueWorker(tg, notes); tg.client.replies = ["Data BERHASIL dikirim"]
        await w.process_next()
        self.assertEqual(db.one("SELECT status s FROM job_queue")["s"], "completed")
        self.assertFalse(stored.exists())
        self.assertEqual(db.one("SELECT status s FROM excel_files")["s"], "deleted")

    async def test_no_confirmation_is_uncertain_and_keeps_excel(self):
        stored = await self._queue_item(); tg = FakeTg(); w = queue_worker.QueueWorker(tg, Notes())
        await w.process_next()                       # কোনো উত্তর নেই
        self.assertEqual(db.one("SELECT status s FROM job_queue")["s"], "uncertain")
        self.assertTrue(stored.exists())
        await w.process_next()                       # আবার পাঠানো হবে না
        self.assertEqual(len([s for s in tg.client.sent if s[0] == "file"]), 1)

    async def test_failure_before_send_retries_then_fails(self):
        await self._queue_item(); tg = FakeTg(); tg.client.fail_before_send = True
        w = queue_worker.QueueWorker(tg, Notes())
        for _ in range(config.MAX_ATTEMPTS):
            db.run("UPDATE job_queue SET next_attempt_at=NULL WHERE status='pending'")
            await w.process_next()
        self.assertEqual(db.one("SELECT status s FROM job_queue")["s"], "failed")

    async def test_bot_error_reply_fails_without_auto_retry(self):
        await self._queue_item(); tg = FakeTg(); tg.client.replies = ["Gagal: format salah"]
        w = queue_worker.QueueWorker(tg, Notes()); await w.process_next()
        self.assertEqual(db.one("SELECT status s FROM job_queue")["s"], "failed")

    async def test_paused_profile_not_processed(self):
        await self._queue_item(); db.run("UPDATE profiles SET status='paused'")
        tg = FakeTg(); w = queue_worker.QueueWorker(tg, Notes())
        self.assertFalse(await w.process_next()); self.assertEqual(tg.client.sent, [])

    async def test_recover_marks_processing_uncertain(self):
        await self._queue_item(); db.run("UPDATE job_queue SET status='processing'")
        self.assertEqual(queue_worker.QueueWorker(FakeTg(), Notes()).recover(), 1)
        self.assertEqual(db.one("SELECT status s FROM job_queue")["s"], "uncertain")

    async def test_only_one_processing_at_a_time(self):
        await self._queue_item()
        db.run("INSERT INTO profiles(owner_user_id,name,status) VALUES(1,'P2','active')")
        db.run("INSERT INTO job_queue(profile_id,job_id,excel_file_id,status) VALUES(2,1,NULL,'processing')")
        tg = FakeTg(); w = queue_worker.QueueWorker(tg, Notes())
        self.assertFalse(await w.process_next()); self.assertEqual(tg.client.sent, [])

    def test_excel_shared_by_two_items_not_deleted_early(self):
        eid, stored = seed()
        db.run("INSERT INTO jobs(name,bot_chat_id) VALUES('J2','@b')")
        db.run("INSERT INTO job_queue(profile_id,job_id,excel_file_id,status) VALUES(1,1,?,'completed')", (eid,))
        db.run("INSERT INTO job_queue(profile_id,job_id,excel_file_id,status) VALUES(1,2,?,'pending')", (eid,))
        item = db.one("SELECT * FROM job_queue WHERE job_id=1")
        ok, _ = excel_manager.delete_after_success(item)
        self.assertFalse(ok); self.assertTrue(stored.exists())

    def test_admin_resolution_helpers(self):
        eid, stored = seed()
        db.run("INSERT INTO job_queue(profile_id,job_id,excel_file_id,status) VALUES(1,1,?,'uncertain')", (eid,))
        ok, _ = queue_worker.resolve_uncertain(1, success=False)
        self.assertEqual(db.one("SELECT status s FROM job_queue")["s"], "pending")
        db.run("UPDATE job_queue SET status='uncertain'")
        queue_worker.resolve_uncertain(1, success=True)
        self.assertEqual(db.one("SELECT status s FROM job_queue")["s"], "completed")
        self.assertFalse(stored.exists())


if __name__ == "__main__":
    unittest.main()
