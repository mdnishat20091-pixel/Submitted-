"""সব ব্যবহারকারী-দৃশ্যমান বাংলা লেখা ও লেবেল।"""
import html
from datetime import datetime, timezone

import config

PROFILE_STATUS = {
    "active": "🟢 Active — চালু",
    "paused": "⏸️ Paused — সাময়িক বিরতি",
    "stopped": "🔴 Stopped — বন্ধ",
}
JOB_STATUS = {
    "active": "🟢 Active — চালু",
    "paused": "⏸️ Paused — বিরতি",
    "closed": "🔴 Closed — বন্ধ",
}
JOB_ICON = {"active": "🟢", "paused": "⏸️", "closed": "🔴"}
QUEUE_STATUS = {
    "pending": "⏳ Pending — অপেক্ষমাণ",
    "processing": "🔄 Processing — কাজ চলছে",
    "completed": "✅ Completed — কাজ সম্পন্ন",
    "failed": "❌ Failed — ব্যর্থ",
    "uncertain": "❓ Uncertain — ফলাফল অনিশ্চিত",
}
MONITOR_STATE = {
    "open": "🟢 Open — খোলা",
    "closed": "🔴 Closed — বন্ধ",
    "full": "🟠 Full — পূর্ণ",
    "unavailable": "⚪ Unavailable — অনুপলব্ধ",
    "unknown": "❔ অজানা",
}
EVENT_LABEL = {
    "profile_created": "Profile তৈরি",
    "profile_status": "Profile অবস্থা বদল",
    "job_created": "নতুন Job যোগ",
    "job_linked": "Profile-এ Job যুক্ত",
    "job_status": "Job অবস্থা বদল",
    "monitor_check": "Monitor Check",
    "monitor_state": "Job অবস্থা পরিবর্তন",
    "queue_added": "Queue-তে যুক্ত",
    "submission_started": "Submission শুরু",
    "submission_success": "Submission সফল",
    "submission_failed": "Submission ব্যর্থ",
    "submission_uncertain": "Submission অনিশ্চিত",
    "retry": "Retry",
    "excel_uploaded": "Excel আপলোড",
    "excel_deleted": "Excel মোছা হয়েছে",
    "session_connected": "Session সংযুক্ত",
    "session_disconnected": "Session বিচ্ছিন্ন",
    "session_error": "Session ত্রুটি",
    "error": "ত্রুটি",
    "admin_action": "Admin কাজ",
}

NO_ACCESS = ("⛔ আপনি এই বট ব্যবহারের অনুমতিপ্রাপ্ত নন।\n"
             "আপনার Telegram User ID: <code>{uid}</code>\n"
             "অনুমতির জন্য বটের Owner-কে এই ID দিন।")
NEED_ADMIN = "⛔ এই কাজ শুধু Admin/Owner করতে পারবেন।"
NEED_OWNER = "⛔ এই কাজ শুধু Owner করতে পারবেন।"
GENERIC_ERROR = "⚠️ কিছু একটা ভুল হয়েছে। অনুগ্রহ করে আবার চেষ্টা করুন।"
CANCELLED = "❌ বাতিল করা হয়েছে। কোনো তথ্য সংরক্ষণ করা হয়নি।"


def h(value) -> str:
    """HTML escape (ব্যবহারকারীর দেওয়া লেখা দেখানোর আগে)।"""
    return html.escape(str(value if value is not None else ""))


def parse_ts(ts: str | None):
    if not ts:
        return None
    return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def fmt_time(ts: str | None) -> str:
    dt = parse_ts(ts)
    if not dt:
        return "—"
    return dt.astimezone(config.TZ).strftime("%d-%m-%Y %H:%M")


def job_label(job) -> str:
    """Job-এর ইউনিক ID, নাম, External Key (থাকলে) ও Status।"""
    ext = f" ({job['external_job_key']})" if job["external_job_key"] else ""
    return f"#{job['id']} {job['name']}{ext} {JOB_ICON.get(job['status'], '')}"
