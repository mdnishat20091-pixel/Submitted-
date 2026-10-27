"""Telethon (ব্যবহারকারী Account Session) পরিচালনা।
Job Bot ও Group-এর সাথে যোগাযোগ শুধু এই Session দিয়ে হয়।
API Hash ও Session String এনক্রিপ্ট করে DB-তে থাকে; লগে কখনো ছাপা হয় না।"""
import asyncio
import re

import crypto
import db
import history


class SessionNotReady(Exception):
    """Session সংযুক্ত নেই বা মেয়াদ শেষ।"""


class NeedPassword(Exception):
    """Two-step verification পাসওয়ার্ড লাগবে।"""


def normalize_ref(text: str) -> str | None:
    """@username, t.me লিংক বা সংখ্যার Chat ID → মান। ভুল হলে None।"""
    t = (text or "").strip()
    t = re.sub(r"^https?://t\.me/", "", t)
    if re.fullmatch(r"-?\d{5,}", t):
        return t
    t = t.lstrip("@")
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,31}", t):
        return "@" + t
    return None


def mask_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    return ("•" * max(len(digits) - 3, 0)) + digits[-3:]


class TgManager:
    def __init__(self):
        self.client = None
        self.io_lock = asyncio.Lock()   # Bot/Group-এর সাথে একসময়ে একটিই কথোপকথন

    # ---------- সংযোগ ----------
    def current_row(self):
        return db.one("SELECT * FROM telegram_sessions WHERE status='connected' ORDER BY id DESC LIMIT 1")

    def has_session(self) -> bool:
        return self.current_row() is not None

    async def get_client(self):
        from telethon import TelegramClient
        from telethon.sessions import StringSession

        if self.client is not None and self.client.is_connected():
            return self.client
        row = self.current_row()
        if not row:
            raise SessionNotReady("কোনো Telegram Session সংযুক্ত নেই।")
        client = TelegramClient(StringSession(crypto.decrypt(row["session_enc"])),
                                int(crypto.decrypt(row["api_id_enc"])),
                                crypto.decrypt(row["api_hash_enc"]))
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            db.run("UPDATE telegram_sessions SET status='error', last_error=?, updated_at=? WHERE id=?",
                   ("Session আর বৈধ নেই (লগআউট বা মেয়াদোত্তীর্ণ)", db.now_utc(), row["id"]))
            history.add("session_error", "Session আর বৈধ নেই — আবার Connect করুন")
            raise SessionNotReady("Session আর বৈধ নেই। আবার Connect করুন।")
        self.client = client
        return client

    async def drop_client(self):
        if self.client is not None:
            try:
                await self.client.disconnect()
            except Exception:
                pass
            self.client = None

    async def resolve(self, ref: str):
        """Bot/Group-এর Entity। সংখ্যার ID হলে প্রয়োজনে Dialog লোড করে আবার চেষ্টা।"""
        client = await self.get_client()
        key = int(ref) if re.fullmatch(r"-?\d+", ref) else ref
        try:
            return await client.get_entity(key)
        except ValueError:
            await client.get_dialogs()
            return await client.get_entity(key)

    async def check_ref(self, ref: str):
        """(True/False/None, বার্তা) — None মানে যাচাই করা যায়নি (Session নেই)।"""
        if not self.has_session():
            return None, "Session সংযুক্ত নেই বলে যাচাই করা যায়নি"
        try:
            await self.resolve(ref)
            return True, "পাওয়া গেছে"
        except SessionNotReady as e:
            return None, str(e)
        except Exception:
            return False, "Telegram-এ খুঁজে পাওয়া যায়নি"

    # ---------- লগইন ----------
    async def begin_login(self, api_id: int, api_hash: str, phone: str):
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        client = TelegramClient(StringSession(), api_id, api_hash)
        await client.connect()
        try:
            sent = await client.send_code_request(phone)
        except Exception:
            await client.disconnect()
            raise
        return client, sent.phone_code_hash

    async def finish_login(self, client, phone, code, code_hash, password=None) -> str:
        from telethon.errors import SessionPasswordNeededError
        if password is None:
            try:
                await client.sign_in(phone=phone, code=code, phone_code_hash=code_hash)
            except SessionPasswordNeededError:
                raise NeedPassword()
        else:
            await client.sign_in(password=password)
        return client.session.save()

    def save_session(self, owner_id, phone, api_id, api_hash, session_string):
        db.run("UPDATE telegram_sessions SET status='disconnected', session_enc=NULL, updated_at=? "
               "WHERE status IN ('connected','error')", (db.now_utc(),))
        db.run(
            "INSERT INTO telegram_sessions(owner_user_id, phone_hint, api_id_enc, api_hash_enc, session_enc,"
            " status, created_at, updated_at) VALUES(?,?,?,?,?, 'connected', ?, ?)",
            (owner_id, mask_phone(phone), crypto.encrypt(str(api_id)), crypto.encrypt(api_hash),
             crypto.encrypt(session_string), db.now_utc(), db.now_utc()))

    async def disconnect(self):
        """স্থানীয়ভাবে সংযোগ বিচ্ছিন্ন ও সংরক্ষিত Session মুছে ফেলে।
        (Telegram-এর দিকে Session বৈধ থাকে — পুরোপুরি বাতিলে Revoke ব্যবহার করুন।)"""
        await self.drop_client()
        db.run("UPDATE telegram_sessions SET status='disconnected', session_enc=NULL, api_hash_enc=NULL,"
               " updated_at=? WHERE status IN ('connected','error')", (db.now_utc(),))
        history.add("session_disconnected", "Session বিচ্ছিন্ন করা হয়েছে")

    async def revoke(self):
        """Telegram-এর দিক থেকেও Session লগআউট (বাতিল) করে।"""
        try:
            client = await self.get_client()
            await client.log_out()
        except Exception:
            pass
        await self.drop_client()
        db.run("UPDATE telegram_sessions SET status='revoked', session_enc=NULL, api_hash_enc=NULL,"
               " updated_at=? WHERE status IN ('connected','error')", (db.now_utc(),))
        history.add("session_disconnected", "Session Revoke (বাতিল) করা হয়েছে")
