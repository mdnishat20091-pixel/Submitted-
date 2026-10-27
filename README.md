# টেলিগ্রাম Job Manager বট (বাংলা)

বটের সব মেনু, বাটন ও বার্তা বাংলায়। মূল মেনুতে ঠিক চারটি অপশন:
**👤 Profile · ➕ Add Profile · 📱 Telegram Session · 📜 History**

## ১. প্রস্তুতি

1. **BOT_TOKEN** — Telegram-এ @BotFather থেকে বট বানিয়ে টোকেন নিন।
2. **OWNER_ID** — আপনার নিজের Telegram User ID (@userinfobot দিয়ে জানা যায়)।
3. **SECRET_KEY** — API Hash ও Session এনক্রিপ্টের চাবি। তৈরি করতে:
   `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
   ⚠️ এই চাবি হারালে সংরক্ষিত Session আর পড়া যাবে না (তখন আবার Connect করতে হবে)।
4. **API ID / API Hash** — my.telegram.org → API development tools (এগুলো বটে পরে Session Connect-এর সময় দেবেন, ফাইলে রাখতে হবে না)।

## ২. চালানো

**Replit-এ:** ZIP খুলে ফাইলগুলো আপলোড করুন → Secrets ট্যাবে `BOT_TOKEN`, `OWNER_ID`, `SECRET_KEY` বসান → Run।
**নিজের কম্পিউটার/সার্ভারে:**

```bash
pip install -r requirements.txt
cp .env.example .env     # তারপর .env-এ মান বসান
python main.py
```

> ডাটাবেস ও Excel থাকে `data/` ফোল্ডারে। Replit-এ এটি Restart-এর পরেও থাকে; তবে Autoscale ডেপ্লয়মেন্টে ডিস্ক স্থায়ী নয় — Reserved VM বা নিজস্ব সার্ভার ব্যবহার করুন। নিয়মিত `data/jobmanager.db` ব্যাকআপ রাখুন।

## ৩. ব্যবহারের ধারা

1. `/start` দিন → 📱 **Telegram Session** → 🔗 Connect (API ID → API Hash → ফোন → কোড)। কোড পাঠানোর সময় সংখ্যার মাঝে ড্যাশ দিন (`1-2-3-4-5`)। গোপন তথ্যের মেসেজ বট মুছে ফেলার চেষ্টা করে।
2. ➕ **Add Profile** → নাম → Job নির্বাচন/নতুন Job → Excel (.xlsx) → প্রয়োজনীয় কলাম → Rules → Check বিরতি → Preview → ✅ Save।
3. 👤 **Profile** খুলে **▶️ Start** দিন (নতুন Profile শুরুতে *Stopped* থাকে — ইচ্ছাকৃত নিরাপত্তা)।
4. Monitor প্রতি ১২০ সেকেন্ডে (পরিবর্তনযোগ্য) Job Bot-কে `/stor` পাঠিয়ে বোর্ড দেখে। Job **Open** হলে (এবং Excel থাকলে) Queue-তে একটি Item তৈরি হয়; Worker একসময়ে একটিই Submission করে।
5. Job Bot Confirmation দিলে ✅ সম্পন্ন; Excel মোছার আগে ফাইল ↔ Queue Item ↔ Profile মিলিয়ে দেখা হয়, অন্য কোনো অসম্পূর্ণ কাজ ব্যবহার করলে ফাইল রাখা হয়।

### কমান্ড
`/stor` `/status` `/jobs` `/openjob` `/closejob` `/pausejobs` `/resumejobs` `/rules` `/queue` `/report` `/stopjob` `/help` — এবং Owner-এর জন্য `/admins` `/addadmin ID [admin|viewer]` `/removeadmin ID`।

**ভূমিকা:** Owner (সবকিছু, Session সহ) · Admin (Profile/Job/Queue পরিচালনা) · viewer (শুধু দেখা)। প্রতিটি কমান্ড ও বাটনে ভূমিকা যাচাই হয়।

## ৪. যে ধারণাগুলোর ওপর বট দাঁড়িয়ে (গুরুত্বপূর্ণ)

আমি আপনার Job Bot-এর আসল উত্তর দেখিনি, তাই এগুলো আপনার বাস্তব Bot-এর সাথে মিলিয়ে নিন — প্রয়োজনে `config.py`-তে বদলান:

- **খোলা Job নেই/পূর্ণ:** উত্তরে `Belum ada Job yang dibuka oleh Admin` বা `semua Job sudah penuh` থাকলে অবস্থা *Unavailable* ধরা হয়। শুধু এই বার্তা দেখে সুনির্দিষ্ট কারণ নিশ্চিত করা যায় না — বট সেটা দাবিও করে না।
- **Job চেনা:** বোর্ডের উত্তরে (লেখা ও Inline বাটনের লেবেলে) External Job ID থাকলে সেটি, না থাকলে Job-এর নাম খোঁজা হয়। পাওয়া গেলে *Open* (লাইনে `penuh`/`full` থাকলে *Full*); উত্তর এলো কিন্তু Job নেই → *Closed*।
- **বন্ধ শনাক্ত:** Group-এর নতুন মেসেজে বা বোর্ডের লাইনে Job-এর নাম/Key-এর সাথে `CLOSE_KEYWORDS` (`/stopjob`, `ditutup`, `closed`…) থাকলে। Group-এর পুরোনো মেসেজ কখনো আবার ধরা হয় না।
- **Submission-এর সফলতা:** প্রতিটি Job-এ **Confirmation শব্দ** দিন (Job Bot সফলতায় যা লেখে, যেমন `berhasil`)। না দিলে বা সময়মতো না এলে Item **❓ অনিশ্চিত** হয় — স্বয়ংক্রিয়ভাবে আর পাঠানো হয় না, Excel মোছা হয় না; `/queue` থেকে আপনি সিদ্ধান্ত দেন।
- Job Bot স্পষ্ট ব্যর্থ বার্তা (`gagal`, `error`…) দিলে Item **Failed** হয় এবং স্বয়ংক্রিয় Retry হয় না (ডুপ্লিকেটের ঝুঁকি এড়াতে); পাঠানোর *আগেই* নেটওয়ার্ক ত্রুটি হলে সর্বোচ্চ ৩ বার নিরাপদ Retry হয়।
- বট রিস্টার্টের সময় *Processing* থাকা Item *অনিশ্চিত* হিসেবে চিহ্নিত হয়।
- History-তে Monitor Check তখনই লেখা হয় যখন ফলাফল বদলায় (প্রতি ২ মিনিটে একই লাইন লিখলে রেকর্ড ফুলে যেত); সর্বশেষ Check-এর সময়/ফলাফল Job স্ক্রিনে সবসময় আছে।

## ৫. সীমাবদ্ধতা

- দর্শক (viewer) সব Profile দেখতে পারে (Profile-ভিত্তিক আলাদা অনুমতি নেই)।
- এখানে বসা Telegram-অংশ (লগইন, `/stor`, ফাইল পাঠানো) লাইভ Telegram-এ চালিয়ে দেখা যায়নি; লজিক নকল Client দিয়ে টেস্ট করা হয়েছে। প্রথমে একটি পরীক্ষামূলক Job/Bot দিয়ে চালিয়ে নিন।
- ডাটাবেস মাইগ্রেশন শুধু-যোগ-করা (টেবিল/কলাম যোগ হয়, কিছু মোছা বা পুনর্গঠন হয় না)। তবুও আগের ডাটাবেসে চালানোর আগে ব্যাকআপ নিন।

## ৬. টেস্ট

```bash
python -m unittest discover -s tests -t . -v
```

## ৭. ফাইল-কাঠামো

`main.py` (প্রবেশ) · `config.py` · `db.py` (স্কিমা/মাইগ্রেশন) · `auth.py` · `monitor.py` · `queue_worker.py` · `excel_manager.py` · `tg_client.py` (Telethon) · `crypto.py` · `texts.py` (বাংলা লেবেল) · `ui.py` · `handlers/` (মেনু, উইজার্ড, Session, History, কমান্ড) · `tests/`
