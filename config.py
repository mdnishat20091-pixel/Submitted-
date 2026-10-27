"""সব সেটিং এক জায়গায়। Secret মান শুধু Environment/.env থেকে আসবে।"""
import os
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # python-dotenv না থাকলেও চলবে
    pass

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
DB_PATH = Path(os.getenv("DB_PATH", DATA_DIR / "jobmanager.db"))
EXCEL_DIR = DATA_DIR / "excel"
TMP_DIR = DATA_DIR / "tmp"

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0") or 0)
TZ = ZoneInfo(os.getenv("TIMEZONE", "Asia/Dhaka"))

# Monitor
DEFAULT_INTERVAL = 120            # সেকেন্ড (প্রতি ২ মিনিট)
INTERVAL_CHOICES = (60, 120, 300, 600)
MONITOR_TICK = 5                  # Monitor লুপ কত সেকেন্ডে জাগবে
BOARD_REPLY_TIMEOUT = 25          # /stor-এর উত্তরের জন্য অপেক্ষা
GROUP_SCAN_LIMIT = 20             # Group-এর সর্বশেষ কয়টি মেসেজ দেখবে

# Job Bot-এর /stor উত্তরে যে বার্তা এলে "খোলা Job নেই/পূর্ণ" ধরা হবে
NO_JOB_MARKERS = (
    "belum ada job yang dibuka oleh admin",
    "semua job sudah penuh",
)
FULL_WORDS = ("penuh", "full")
# Job বন্ধ হওয়ার ইঙ্গিত (Bot উত্তর বা Group মেসেজে, Job-এর নাম/Key-সহ লাইনে)
CLOSE_KEYWORDS = ("/stopjob", "stopjob", "ditutup", "job closed", "closed")
# Bot স্পষ্টভাবে ব্যর্থ বললে
ERROR_KEYWORDS = ("gagal", "error", "invalid", "ditolak", "salah", "failed")

# Queue / Submission
WORKER_TICK = 3
MAX_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 60        # attempt × এই মান
SUBMIT_WAIT_SECONDS = 90          # Confirmation-এর জন্য মোট অপেক্ষা
MAX_EXCEL_BYTES = 10 * 1024 * 1024

for _d in (DATA_DIR, EXCEL_DIR, TMP_DIR):
    _d.mkdir(parents=True, exist_ok=True)
