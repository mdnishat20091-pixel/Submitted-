"""Job Monitor: নির্ধারিত বিরতিতে Job Bot-এর /stor ও Group যাচাই করে Job-এর অবস্থা বের করে।
Job 'Open' হলে (এবং Excel থাকলে) Queue-তে একটিমাত্র Item তৈরি হয় — বারবার Check হলেও ডুপ্লিকেট নয়।"""
import asyncio
import logging
from datetime import datetime, timezone

import config
import db
import excel_manager
import history
from tg_client import SessionNotReady

log = logging.getLogger("monitor")


# ---------- বিশুদ্ধ (Telegram-নিরপেক্ষ) বিশ্লেষণ ----------
def _needle(job) -> str:
    return (job["external_job_key"] or job["name"] or "").strip().lower()


def parse_board(text: str, job) -> tuple[str, str]:
    """Job Bot-এর /stor উত্তর থেকে (অবস্থা, বিবরণ)।"""
    low = (text or "").lower()
    if not low.strip():
        return "unknown", "Bot-এর উত্তর খালি ছিল"
    if any(m in low for m in config.NO_JOB_MARKERS):
        return "unavailable", ("বোর্ডে খোলা Job নেই বা সব Job পূর্ণ — "
                               "শুধু এই বার্তা দেখে সুনির্দিষ্ট কারণ নিশ্চিত করা যায় না")
    needle = _needle(job)
    lines = [ln for ln in low.splitlines() if needle and needle in ln]
    if not lines:
        return "closed", "বোর্ডের তালিকায় এই Job নেই"
    if any(k in ln for ln in lines for k in config.CLOSE_KEYWORDS):
        return "closed", "বোর্ডে Job বন্ধ বলে দেখানো হয়েছে"
    if any(k in ln for ln in lines for k in config.FULL_WORDS):
        return "full", "বোর্ডে Job পূর্ণ বলে দেখানো হয়েছে"
    return "open", "বোর্ডে Job খোলা আছে"


def group_close_event(messages: list[tuple[int, str]], job, after_id: int | None) -> bool:
    """after_id-এর পরের Group মেসেজে এই Job বন্ধের ইঙ্গিত আছে কি।"""
    needle = _needle(job)
    for msg_id, text in messages:
        if after_id is not None and msg_id <= after_id:
            continue
        low = (text or "").lower()
        if needle and needle in low and any(k in low for k in config.CLOSE_KEYWORDS):
            return True
    return False


class Monitor:
    def __init__(self, tg, notify):
        self.tg = tg
        self.notify = notify          # async (user_id, text)
        self._warned: set[tuple[int, int]] = set()

    async def run(self):
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Monitor tick ব্যর্থ")
            await asyncio.sleep(config.MONITOR_TICK)

    async def tick(self):
        rows = db.all(
            "SELECT pj.profile_id, pj.job_id, pj.check_interval_seconds, pj.last_check_at "
            "FROM profile_jobs pj JOIN profiles p ON p.id=pj.profile_id JOIN jobs j ON j.id=pj.job_id "
            "WHERE pj.enabled=1 AND p.status='active' AND j.status='active' ORDER BY pj.profile_id, pj.job_id")
        now = datetime.now(timezone.utc)
        for r in rows:
            last = r["last_check_at"]
            if last:
                elapsed = (now - datetime.strptime(last, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)).total_seconds()
                if elapsed < (r["check_interval_seconds"] or config.DEFAULT_INTERVAL):
                    continue
            await self.check(r["profile_id"], r["job_id"])

    # ---------- একটি Job Check ----------
    async def _fetch_board(self, client, bot) -> str | None:
        async with client.conversation(bot, timeout=config.BOARD_REPLY_TIMEOUT,
                                       total_timeout=config.BOARD_REPLY_TIMEOUT + 5) as conv:
            await conv.send_message("/stor")
            try:
                resp = await conv.get_response()
            except asyncio.TimeoutError:
                return None
            parts = [resp.raw_text or ""]
            for row in (resp.buttons or []):
                for b in row:
                    parts.append(b.text or "")
            return "\n".join(parts)

    async def _scan_group(self, client, group_ref, job, pj):
        """(বন্ধের ইভেন্ট আছে কি, নতুন সর্বোচ্চ Message ID)"""
        group = await self.tg.resolve(group_ref)
        msgs = await client.get_messages(group, limit=config.GROUP_SCAN_LIMIT)
        items = [(m.id, m.raw_text or "") for m in msgs]
        if not items:
            return False, pj["last_group_msg_id"]
        max_id = max(i for i, _ in items)
        if pj["last_group_msg_id"] is None:
            return False, max_id                  # প্রথমবার: পুরোনো মেসেজ ধরা হবে না
        return group_close_event(items, job, pj["last_group_msg_id"]), max_id

    async def check(self, profile_id: int, job_id: int) -> dict:
        """একটি Profile-Job যাচাই করে ফলাফল ফেরত দেয়: {state, detail, ok}"""
        pj = db.one("SELECT * FROM profile_jobs WHERE profile_id=? AND job_id=?", (profile_id, job_id))
        job = db.one("SELECT * FROM jobs WHERE id=?", (job_id,))
        profile = db.one("SELECT * FROM profiles WHERE id=?", (profile_id,))
        if not (pj and job and profile):
            return {"state": "unknown", "detail": "Profile/Job পাওয়া যায়নি", "ok": False}

        state, detail, ok, new_group_id = "unknown", "", True, pj["last_group_msg_id"]
        try:
            async with self.tg.io_lock:
                client = await self.tg.get_client()
                bot = await self.tg.resolve(job["bot_chat_id"])
                board = await self._fetch_board(client, bot)
                closed_by_group = False
                if job["group_chat_id"]:
                    try:
                        closed_by_group, new_group_id = await self._scan_group(
                            client, job["group_chat_id"], job, pj)
                    except SessionNotReady:
                        raise
                    except Exception as e:
                        log.warning("Group যাচাই ব্যর্থ: %s", type(e).__name__)
            if board is None:
                state, detail = "unknown", "Job Bot নির্ধারিত সময়ে উত্তর দেয়নি"
            else:
                state, detail = parse_board(board, job)
            if closed_by_group and state != "open":
                state, detail = "closed", "Group-এ Job বন্ধের ঘোষণা পাওয়া গেছে"
        except SessionNotReady as e:
            ok, detail = False, f"Session সমস্যা: {e}"
        except Exception as e:
            ok, detail = False, f"Check ব্যর্থ ({type(e).__name__})"
            log.warning("Check ব্যর্থ: %s", type(e).__name__)

        return await self._apply(pj, job, profile, state, detail, ok, new_group_id)

    async def _apply(self, pj, job, profile, state, detail, ok, new_group_id) -> dict:
        pid, jid = pj["profile_id"], pj["job_id"]
        prev = pj["monitor_state"]
        # অনিশ্চিত/ব্যর্থ ফলাফলে আগের নির্ভরযোগ্য অবস্থা অপরিবর্তিত থাকে
        effective = state if (ok and state != "unknown") else prev
        handled = pj["open_episode_handled"]
        if effective != "open":
            handled = 0                      # নতুন Open এলে আবার সুযোগ

        db.run("UPDATE profile_jobs SET last_check_at=?, last_result=?, monitor_state=?, "
               "last_group_msg_id=?, open_episode_handled=? WHERE profile_id=? AND job_id=?",
               (db.now_utc(), detail, effective, new_group_id, handled, pid, jid))

        if effective != prev:
            history.add("monitor_state", f"{prev} → {effective}: {detail}", pid, jid)
            await self.notify(profile["owner_user_id"],
                              f"🔔 <b>{_e(job['name'])}</b> — অবস্থা বদলেছে: {prev} → <b>{effective}</b>")
        elif detail != pj["last_result"]:
            history.add("monitor_check" if ok else "error", detail, pid, jid)

        if effective == "open" and handled == 0 and profile["status"] == "active":
            await self._maybe_enqueue(profile, job)
        return {"state": effective, "detail": detail, "ok": ok}

    async def _maybe_enqueue(self, profile, job):
        pid, jid = profile["id"], job["id"]
        excel = excel_manager.get_active(pid)
        if not excel:
            if (pid, jid) not in self._warned:
                self._warned.add((pid, jid))
                history.add("error", "Job খোলা, কিন্তু Profile-এ কোনো Excel নেই — Queue তৈরি হয়নি", pid, jid)
                await self.notify(profile["owner_user_id"],
                                  f"⚠️ <b>{_e(job['name'])}</b> খোলা, কিন্তু <b>{_e(profile['name'])}</b>-এ "
                                  "Excel নেই। Excel আপলোড করলে স্বয়ংক্রিয়ভাবে Queue-তে যাবে।")
            return
        self._warned.discard((pid, jid))
        try:
            with db.tx() as conn:
                conn.execute("INSERT INTO job_queue(profile_id, job_id, excel_file_id, status, created_at) "
                             "VALUES(?,?,?, 'pending', ?)", (pid, jid, excel["id"], db.now_utc()))
                conn.execute("UPDATE profile_jobs SET open_episode_handled=1 WHERE profile_id=? AND job_id=?",
                             (pid, jid))
        except Exception:
            # ইউনিক ইনডেক্সে আটকালে আগে থেকেই সক্রিয় Item আছে — ডুপ্লিকেট হয়নি
            db.run("UPDATE profile_jobs SET open_episode_handled=1 WHERE profile_id=? AND job_id=?", (pid, jid))
            return
        history.add("queue_added", "Job খোলা — Queue-তে যুক্ত হয়েছে", pid, jid)
        await self.notify(profile["owner_user_id"],
                          f"📋 <b>{_e(job['name'])}</b> খোলা — <b>{_e(profile['name'])}</b> Queue-তে যুক্ত হয়েছে।")


def _e(v) -> str:
    import html
    return html.escape(str(v))
