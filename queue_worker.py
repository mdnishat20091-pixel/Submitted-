"""Queue Worker: একসময়ে একটিমাত্র Submission (Global Lock)।

নিরাপত্তা নীতি:
- Excel পাঠানোর আগেই ব্যর্থ হলে → নিরাপদে Retry (সর্বোচ্চ MAX_ATTEMPTS)।
- পাঠানোর পর Confirmation না পেলে/ত্রুটি হলে → 'uncertain'; স্বয়ংক্রিয়ভাবে আর পাঠানো হয় না,
  Admin নিজে যাচাই করে সিদ্ধান্ত দেন। Excel তখন মোছা হয় না।
- বট রিস্টার্টের সময় 'processing' থাকা Item → 'uncertain' (ডুপ্লিকেট Submission এড়াতে)।
"""
import asyncio
import html
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import config
import db
import excel_manager
import history
from tg_client import SessionNotReady

log = logging.getLogger("worker")


def _e(v) -> str:
    return html.escape(str(v))


def classify_reply(text: str, confirm_keyword: str | None) -> str:
    """Job Bot-এর উত্তর → 'confirmed' | 'failed' | 'other'"""
    low = (text or "").lower()
    if any(k in low for k in config.ERROR_KEYWORDS):
        return "failed"
    if confirm_keyword and confirm_keyword.strip().lower() in low:
        return "confirmed"
    return "other"


# ---------- Admin-এর হাতে সিদ্ধান্ত (Handler থেকে ডাকা হয়) ----------
def resolve_uncertain(item_id: int, success: bool):
    item = db.one("SELECT * FROM job_queue WHERE id=? AND status='uncertain'", (item_id,))
    if not item:
        return False, "Item পাওয়া যায়নি বা আর অনিশ্চিত নয়।"
    if success:
        db.run("UPDATE job_queue SET status='completed', completed_at=?, last_error=NULL WHERE id=?",
               (db.now_utc(), item_id))
        history.add("submission_success", "Admin নিশ্চিত করেছেন: Submission সফল", item["profile_id"], item["job_id"])
        _, msg = excel_manager.delete_after_success(item)
        return True, "✅ সফল হিসেবে চিহ্নিত। " + msg
    db.run("UPDATE job_queue SET status='pending', next_attempt_at=NULL, last_error=NULL WHERE id=?", (item_id,))
    history.add("retry", "Admin নিশ্চিত করেছেন: Submission হয়নি — আবার Queue-তে", item["profile_id"], item["job_id"])
    return True, "🔁 আবার Queue-তে দেওয়া হয়েছে।"


def retry_failed(item_id: int):
    item = db.one("SELECT * FROM job_queue WHERE id=? AND status='failed'", (item_id,))
    if not item:
        return False, "Item পাওয়া যায়নি বা ব্যর্থ অবস্থায় নেই।"
    try:
        db.run("UPDATE job_queue SET status='pending', attempt_count=0, next_attempt_at=NULL, last_error=NULL "
               "WHERE id=?", (item_id,))
    except Exception:
        return False, "এই Profile-Job-এর জন্য আরেকটি সক্রিয় Item আছে।"
    history.add("retry", "Admin ব্যর্থ Item আবার চেষ্টায় দিয়েছেন", item["profile_id"], item["job_id"])
    return True, "🔁 আবার Queue-তে দেওয়া হয়েছে।"


def cancel_pending(item_id: int):
    item = db.one("SELECT * FROM job_queue WHERE id=? AND status='pending'", (item_id,))
    if not item:
        return False, "Item পাওয়া যায়নি বা অপেক্ষমাণ নেই।"
    db.run("UPDATE job_queue SET status='failed', last_error='Admin বাতিল করেছেন' WHERE id=?", (item_id,))
    history.add("submission_failed", "Admin Queue Item বাতিল করেছেন", item["profile_id"], item["job_id"])
    return True, "🚫 বাতিল করা হয়েছে।"


class QueueWorker:
    def __init__(self, tg, notify):
        self.tg = tg
        self.notify = notify
        self.lock = asyncio.Lock()     # Global Submission Lock

    def recover(self):
        """বট চালু হওয়ার সময় আটকে থাকা 'processing' Item সামলায়।"""
        stuck = db.all("SELECT * FROM job_queue WHERE status='processing'")
        for it in stuck:
            db.run("UPDATE job_queue SET status='uncertain', last_error=? WHERE id=?",
                   ("বট রিস্টার্টের সময় কাজ চলছিল — Submission হয়েছে কিনা যাচাই করুন", it["id"]))
            history.add("submission_uncertain", "রিস্টার্টের সময় Processing ছিল — যাচাই প্রয়োজন",
                        it["profile_id"], it["job_id"])
        return len(stuck)

    async def run(self):
        while True:
            try:
                await self.process_next()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Worker ব্যর্থ")
            await asyncio.sleep(config.WORKER_TICK)

    async def process_next(self):
        item = db.one(
            "SELECT q.* FROM job_queue q JOIN profiles p ON p.id=q.profile_id JOIN jobs j ON j.id=q.job_id "
            "WHERE q.status='pending' AND p.status='active' AND j.status='active' "
            "AND (q.next_attempt_at IS NULL OR q.next_attempt_at<=?) ORDER BY q.id LIMIT 1", (db.now_utc(),))
        if not item:
            return False
        async with self.lock:
            # শুরুর আগে Lock/Status যাচাই: অন্য কোনো Item চলছে না, এবং এটি এখনো pending
            cur = db.run(
                "UPDATE job_queue SET status='processing', attempt_count=attempt_count+1, started_at=? "
                "WHERE id=? AND status='pending' AND NOT EXISTS "
                "(SELECT 1 FROM job_queue WHERE status='processing')", (db.now_utc(), item["id"]))
            if cur.rowcount == 0:
                return False
            await self._submit(db.one("SELECT * FROM job_queue WHERE id=?", (item["id"],)))
        return True

    # ---------- Submission ----------
    async def _submit(self, item):
        pid, jid, qid = item["profile_id"], item["job_id"], item["id"]
        profile = db.one("SELECT * FROM profiles WHERE id=?", (pid,))
        job = db.one("SELECT * FROM jobs WHERE id=?", (jid,))
        owner = profile["owner_user_id"]

        excel = db.one("SELECT * FROM excel_files WHERE id=? AND profile_id=? AND status='active'",
                       (item["excel_file_id"], pid))
        if not excel or not Path(excel["file_path"]).exists():
            await self._fail(item, profile, job, "Excel ফাইল পাওয়া যায়নি বা মেলেনি", retry=False)
            return

        history.add("submission_started", f"Submission শুরু (চেষ্টা {item['attempt_count']})", pid, jid)
        sent = False
        outcome, reply = "other", ""
        try:
            async with self.tg.io_lock:
                client = await self.tg.get_client()
                bot = await self.tg.resolve(job["bot_chat_id"])
                async with client.conversation(bot, timeout=config.SUBMIT_WAIT_SECONDS,
                                               total_timeout=config.SUBMIT_WAIT_SECONDS) as conv:
                    await conv.send_file(excel["file_path"])
                    sent = True
                    try:
                        while True:
                            resp = await conv.get_response()
                            reply = (resp.raw_text or "")[:300]
                            outcome = classify_reply(reply, job["confirm_keyword"])
                            if outcome in ("confirmed", "failed"):
                                break
                            if not job["confirm_keyword"]:
                                break          # যাচাইয়ের উপায় নেই — অনিশ্চিত
                    except asyncio.TimeoutError:
                        pass
        except SessionNotReady as e:
            await self._fail(item, profile, job, f"Session সমস্যা: {e}", retry=True)
            return
        except Exception as e:
            name = type(e).__name__
            wait = getattr(e, "seconds", None)       # FloodWaitError
            if not sent:
                if wait:
                    self._reschedule(item, int(wait) + 1, f"Telegram সীমা ({wait} সেকেন্ড অপেক্ষা)")
                    return
                await self._fail(item, profile, job, f"পাঠানোর আগেই ত্রুটি ({name})", retry=True)
                return
            await self._uncertain(item, profile, job, f"পাঠানোর পর ত্রুটি ({name})")
            return

        if outcome == "confirmed":
            await self._success(item, profile, job)
        elif outcome == "failed":
            await self._fail(item, profile, job, f"Job Bot ব্যর্থ বার্তা দিয়েছে: {reply}", retry=False)
        else:
            why = ("এই Job-এর জন্য Confirmation শব্দ দেওয়া নেই" if not job["confirm_keyword"]
                   else "নির্ধারিত সময়ে Confirmation পাওয়া যায়নি")
            await self._uncertain(item, profile, job, f"{why}। শেষ উত্তর: {reply or '—'}")

    # ---------- ফলাফল ----------
    async def _success(self, item, profile, job):
        db.run("UPDATE job_queue SET status='completed', completed_at=?, last_error=NULL WHERE id=?",
               (db.now_utc(), item["id"]))
        history.add("submission_success", "Job Bot Confirmation দিয়েছে — সফল", item["profile_id"], item["job_id"])
        ok, msg = excel_manager.delete_after_success(item)
        await self.notify(profile["owner_user_id"],
                          f"✅ <b>{_e(job['name'])}</b> — Submission সফল ({_e(profile['name'])}).\n{_e(msg)}")

    async def _uncertain(self, item, profile, job, why):
        db.run("UPDATE job_queue SET status='uncertain', last_error=? WHERE id=?", (why[:500], item["id"]))
        history.add("submission_uncertain", why, item["profile_id"], item["job_id"])
        await self.notify(profile["owner_user_id"],
                          f"❓ <b>{_e(job['name'])}</b> — Submission সফল হয়েছে কিনা নিশ্চিত নয়।\n{_e(why)}\n"
                          "Excel মোছা হয়নি। /queue থেকে যাচাই করে সিদ্ধান্ত দিন।")

    async def _fail(self, item, profile, job, why, retry: bool):
        attempts = item["attempt_count"]
        if retry and attempts < config.MAX_ATTEMPTS:
            self._reschedule(item, config.RETRY_BACKOFF_SECONDS * attempts, why)
            return
        db.run("UPDATE job_queue SET status='failed', last_error=? WHERE id=?", (why[:500], item["id"]))
        history.add("submission_failed", why, item["profile_id"], item["job_id"])
        await self.notify(profile["owner_user_id"],
                          f"❌ <b>{_e(job['name'])}</b> — Submission ব্যর্থ।\n{_e(why)}\n/queue থেকে আবার চেষ্টা করতে পারেন।")

    def _reschedule(self, item, delay_seconds: int, why: str):
        nxt = (datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)).strftime("%Y-%m-%d %H:%M:%S")
        db.run("UPDATE job_queue SET status='pending', next_attempt_at=?, last_error=? WHERE id=?",
               (nxt, why[:500], item["id"]))
        history.add("retry", f"{why} — {delay_seconds} সেকেন্ড পরে আবার চেষ্টা", item["profile_id"], item["job_id"])
