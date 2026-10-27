"""প্রতিটি গুরুত্বপূর্ণ ঘটনা job_history-তে লেখা হয় (কখনো মোছা হয় না)।"""
import db


def add(event_type: str, message: str, profile_id=None, job_id=None):
    db.run(
        "INSERT INTO job_history(profile_id, job_id, event_type, message, created_at) VALUES(?,?,?,?,?)",
        (profile_id, job_id, event_type, (message or "")[:1000], db.now_utc()),
    )
