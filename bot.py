import os
import json
import logging
import threading
from datetime import date
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

DATA_FILE = "data.json"


# ---------- ذخیره و بازیابی داده‌ها ----------
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"user_map": {}, "next_id": 1000, "blocked": [], "msg_count": {}, "msg_dates": {}, "msg_total": {}}

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

data = load_data()
data["user_map"] = {str(k): v for k, v in data["user_map"].items()}
data.setdefault("msg_count", {})
data.setdefault("msg_dates", {})
data.setdefault("msg_total", {})  # NEW: تعداد کل پیام‌های ارسالی برای گیمیفیکیشن


def get_or_create_code(uid: int) -> int:
    uid = str(uid)
    if uid not in data["user_map"]:
        data["user_map"][uid] = data["next_id"]
        data["next_id"] += 1
        save_data()
    return data["user_map"][uid]


def find_uid_by_code(code: int):
    for uid, c in data["user_map"].items():
        if c == code:
            return int(uid)
    return None


def is_blocked(uid: int) -> bool:
    return uid in data["blocked"]


def increment_message_count(uid: int):
    """فقط برای آمار، بدون هیچ محدودیتی"""
    uid = str(uid)
    today = str(date.today())
    if data["msg_dates"].get(uid) != today:
        data["msg_dates"][uid] = today
        data["msg_count"][uid] = 0
    data["msg_count"][uid] = data["msg_count"].get(uid, 0) + 1
    # NEW: افزایش تعداد کل پیام‌ها برای گیمیفیکیشن
    data["msg_total"][uid] = data["msg_total"].get(uid, 0) + 1
    save_data()


def log_message_to_file(uid: int, code: int, content: str):
    try:
        with open("messages_log.txt", "a", encoding="utf-8") as f:
            f.write(f"[{date.today()}] uid={uid} code={code} | {content}\n")
    except Exception:
        logging.exception("خطا در ثبت لاگ پیام")


# ---------- NEW: گیمیفیکیشن - محاسبه رتبه بر اساس کل پیام‌ها ----------
RANKS = [
    (0,   "🌱 تازه‌وارد"),
    (5,   "💬 فعال"),
    (20,  "⭐ ستاره"),
    (50,  "🏆 افسانه‌ای"),
]

def get_rank(uid: int) -> str:
    total = data["msg_total"].get(str(uid), 0)
    rank = RANKS[0][1]
    for threshold, title in RANKS:
        if total >= threshold:
            rank = title
    return rank

def get_next_rank_info(uid: int) -> str:
    total = data["msg_total"].get(str(uid), 0)
    for threshold, title in RANKS:
        if total < threshold:
            return f"{threshold - total} پیام تا رتبه {title}"
    return "بالاترین رتبه رو داری! 🎉"


# ---------- NEW: فال روزانه (بر اساس کد کاربر + تاریخ — هر نفر فال خودش رو داره) ----------
FAL_POOL = [
    ("🌸", "امروز یه اتفاق کوچیک قلبت رو گرم می‌کنه. چشماتو باز نگه‌دار."),
    ("🌙", "شب امشب برات رازی داره. افکارت رو بنویس، جواب توشونه."),
    ("⭐", "یه نفر بهت فکر می‌کنه که فکرشو نمی‌کنی. لبخند بزن."),
    ("🦋", "تغییری در راهه. نترس، بال‌هات قوی‌تر از اونیه که فکر می‌کنی."),
    ("🌊", "امروز جاری باش. با جریان زندگی بجنگ نه با خودت."),
    ("🌺", "یه فرصت دم دسته. فقط کافیه دستتو دراز کنی."),
    ("🔮", "چیزی که گمش کردی، دوباره پیدا می‌شه. صبور باش."),
    ("🌈", "بعد از این ابرا، رنگ‌های قشنگی در راهه. نزدیکه."),
    ("💫", "انرژیت امروز خاصه. هر کاری بخوای می‌تونی شروع کنی."),
    ("🍀", "شانس امروزت بیشتر از دیروزه. یه ریسک کوچیک بکن."),
    ("🌻", "آفتاب درونتو کسی نمی‌تونه خاموش کنه. درخشش."),
    ("🕊️", "آروم باش. جواب یه سوال قدیمی امروز بهت می‌رسه."),
    ("💎", "ارزشت رو دست کم نگیر. کسی هست که چشمش دنبالته."),
    ("🌿", "امروز به خودت مهربون باش. استراحت هم پیشرفته."),
    ("🎀", "یه خبر خوب در راهه. صبر کن، دیر نیست."),
    ("🌝", "امشب آرامش داری. ذهنتو خاموش کن و فقط نفس بکش."),
    ("🍓", "شیرینی‌ای در راهه که انتظارشو نداری. آماده باش."),
    ("🪷", "دلت یه چیزی می‌خواد که ازش فرار می‌کنی. وقتشه."),
    ("✨", "اتفاق‌های خوب به آدم‌های صبور می‌رسن. تو صبوری."),
    ("🌓", "نیمه‌ی تاریک روزت زود تموم می‌شه. نور داره میاد."),
]

def get_daily_fal(uid: int) -> tuple:
    today = str(date.today())
    seed = hash(f"{uid}_{today}") % len(FAL_POOL)
    return FAL_POOL[seed]


# ---------- NEW: تست شخصیت ----------
PERSONALITY_QUESTIONS = [
    {
        "q": "وقتی ناراحتی چیکار می‌کنی؟",
        "opts": [("تنها می‌شم و فکر می‌کنم 🌙", "i"), ("با یکی حرف می‌زنم 🌸", "e"),
                 ("گوش می‌دم به موزیک 🎵", "a"), ("سرم رو شلوغ می‌کنم 🔥", "f")]
    },
    {
        "q": "محیط ایده‌آلت کدومه؟",
        "opts": [("طبیعت و سکوت 🌿", "n"), ("کافه شلوغ ☕", "e"),
                 ("خونه و راحتی 🛋️", "i"), ("هر جایی که دوستام باشن 🌺", "s")]
    },
    {
        "q": "بیشتر به چی اهمیت می‌دی؟",
        "opts": [("احساسات ❤️", "f"), ("منطق 🧩", "t"),
                 ("خلاقیت 🎨", "a"), ("نظم و برنامه 📋", "j")]
    },
    {
        "q": "وقت آزاد داری چیکار می‌کنی؟",
        "opts": [("کتاب یا فیلم 📚", "i"), ("بیرون می‌رم با دوستام 🌸", "e"),
                 ("چیزی خلق می‌کنم 🎨", "a"), ("استراحت می‌کنم 🌙", "n")]
    },
    {
        "q": "دوست داری چطور شناخته بشی؟",
        "opts": [("مرموز و جذاب 🌙", "m"), ("مهربون و گرم ❤️", "f"),
                 ("باهوش و خلاق ✨", "a"), ("شاد و پرانرژی 🌟", "e")]
    },
]

PERSONALITY_RESULTS = {
    "i": ("🌙 روح شبانه", "عمیقی، رازآلودی و دنیای درونت خیلی غنیه. هر چیزی رو حس می‌کنی، فقط نشونش نمی‌دی.", "🐺 گرگ"),
    "e": ("🌸 روح اجتماعی", "انرژیت مسری‌ه! هر جا می‌ری گرما می‌بری. آدم‌ها دورت جمع می‌شن بدون اینکه بدونن چرا.", "🦋 پروانه"),
    "a": ("🎨 روح هنری", "دنیا رو متفاوت می‌بینی. خلاقیتت یه هدیه‌ست که خیلی‌ها ندارن.", "🦚 طاووس"),
    "f": ("❤️ روح احساساتی", "قلبت بزرگه و عمیق دوست می‌داری. این یه قدرته، نه ضعف.", "🌺 گل سرخ"),
    "n": ("🌿 روح آزاد", "به آزادی و آرامش نیاز داری. طبیعت روحته و کمتر کسی تو رو درک می‌کنه.", "🦌 آهو"),
    "m": ("🌑 روح مرموز", "لایه‌های زیادی داری که کمتر کسی بهشون می‌رسه. این جذابیتته.", "🐈‍⬛ گربه سیاه"),
    "s": ("☀️ روح شاد", "انرژی مثبتت همه چیز رو روشن می‌کنه. دنیا با تو رنگی‌تره.", "🌻 آفتابگردان"),
    "t": ("🧩 روح تحلیلگر", "ذهنت همیشه کار می‌کنه. عمیق فکر می‌کنی و کمتر کسی به پات می‌رسه.", "🦉 جغد"),
    "j": ("📋 روح منظم", "قابل اعتمادی و پایه‌ای. هر جمعی به یه نفر مثل تو نیاز داره.", "🐝 زنبور"),
}

def get_personality_result(answers: list) -> tuple:
    from collections import Counter
    count = Counter(answers)
    top = count.most_common(1)[0][0]
    return PERSONALITY_RESULTS.get(top, PERSONALITY_RESULTS["f"])

def personality_keyboard(q_index: int) -> InlineKeyboardMarkup:
    q = PERSONALITY_QUESTIONS[q_index]
    rows = [[InlineKeyboardButton(opt, callback_data=f"pq_{q_index}_{val}")]
            for opt, val in q["opts"]]
    return InlineKeyboardMarkup(rows)


# ---------- NEW: برچسب احساسی - ایموجی‌های قابل انتخاب ----------
EMOTION_EMOJIS = ["😊", "😢", "😡", "😍", "😂", "🤔", "😱", "🙏"]

def emotion_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(e, callback_data=f"emotion_{e}")
        for e in EMOTION_EMOJIS
    ]
    # دو ردیف ۴تایی + یه ردیف دکمه رد کردن
    skip_button = InlineKeyboardButton("⏭ رد کردن", callback_data="emotion_skip")
    rows = [buttons[:4], buttons[4:], [skip_button]]
    return InlineKeyboardMarkup(rows)


# ---------- سرور ساده برای زنده نگه‌داشتن سرویس روی Render ----------
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        pass

def run_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()


# ---------- منوی دکمه‌ای پایین صفحه ----------
MAIN_MENU = ReplyKeyboardMarkup(
    [["📝 پیام جدید", "ℹ️ راهنما"], ["📊 آمار من", "🔮 فال امروز"], ["🧠 تست شخصیت"]],
    resize_keyboard=True
)

HELP_TEXT = (
    "📋 راهنمای استفاده از ربات:\n\n"
    "• هر پیامی (متن، عکس، ویس، ویدیو، استیکر یا فایل) بفرستی، کاملاً ناشناس برای ادمین ارسال می‌شه.\n"
    "• هیچ‌وقت آیدی یا اسمت برای ادمین نمایش داده نمی‌شه، فقط یه کد عددی.\n"
    "• قبل از ارسال نهایی، یه حس انتخاب می‌کنی، بعد تأیید می‌کنی.\n"
    "• اگه ادمین جواب بده، همینجا برات پیام میاد.\n"
    "• با ارسال پیام بیشتر، رتبه‌ات بالاتر می‌ره! 🏆"
)


# ---------- دستورات کاربر ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    get_or_create_code(uid)
    await update.message.reply_text(
        "🎉 به ربات پیام ناشناس خوش اومدی!\n\n"
        "🔒 کاملاً ناشناس: هیچ‌وقت آیدی یا اسمت برای ادمین نمایش داده نمی‌شه، فقط یه کد عددی که خودش هم قابل ردیابی به تو نیست.\n\n"
        "هر پیامی (متن، عکس، ویس، ویدیو یا استیکر) بفرستی، به‌صورت ناشناس برای ادمین ارسال می‌شه.",
        reply_markup=MAIN_MENU
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, reply_markup=MAIN_MENU)


async def mystats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    uid_str = str(uid)
    code = get_or_create_code(uid)
    today = str(date.today())
    sent_today = data["msg_count"].get(uid_str, 0) if data["msg_dates"].get(uid_str) == today else 0
    # NEW: اطلاعات گیمیفیکیشن
    total_sent = data["msg_total"].get(uid_str, 0)
    rank = get_rank(uid)
    next_rank = get_next_rank_info(uid)
    await update.message.reply_text(
        f"📊 آمار شما:\n"
        f"کد شما: {code}\n"
        f"پیام‌های امروز: {sent_today}\n"
        f"کل پیام‌های ارسالی: {total_sent}\n\n"
        f"🏅 رتبه فعلی: {rank}\n"
        f"⬆️ {next_rank}",
        reply_markup=MAIN_MENU
    )


# ---------- جریان ارسال پیام با تأیید قبل از ارسال ----------
async def handle_incoming(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """هر پیام کاربر عادی اول میاد اینجا و قبل از فوروارد، تأیید گرفته می‌شه."""
    uid = update.effective_user.id
    text = update.message.text or ""

    # دکمه‌های منو
    if text == "ℹ️ راهنما":
        await help_cmd(update, context)
        return
    if text == "📊 آمار من":
        await mystats_cmd(update, context)
        return
    if text == "📝 پیام جدید":
        await update.message.reply_text("بفرما، پیامت رو بنویس یا بفرست 👇", reply_markup=MAIN_MENU)
        return
    if text == "🔮 فال امروز":
        await fal_cmd(update, context)
        return
    if text == "🧠 تست شخصیت":
        await personality_start(update, context)
        return

    if is_blocked(uid):
        await update.message.reply_text("⛔️ شما توسط ادمین مسدود شده‌اید.", reply_markup=MAIN_MENU)
        return

    # پیام رو موقت ذخیره می‌کنیم
    context.user_data["pending_message"] = update.message.message_id
    # NEW: ریست ایموجی قبلی
    context.user_data["selected_emotion"] = None

    # NEW: اول انتخاب احساس
    await update.message.reply_text(
        "یه حس برای پیامت انتخاب کن 👇",
        reply_markup=emotion_keyboard()
    )


async def confirm_send_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "cancel_send":
        context.user_data["pending_message"] = None
        context.user_data["selected_emotion"] = None
        await query.message.edit_text("❌ پیام لغو شد.")
        return

    msg_id = context.user_data.get("pending_message")
    if not msg_id:
        await query.message.edit_text("پیامی برای ارسال پیدا نشد.")
        return

    await deliver_to_admin(update, context, msg_id)
    context.user_data["pending_message"] = None
    context.user_data["selected_emotion"] = None
    await query.message.edit_text("✅ پیام شما با موفقیت ارسال شد.")


# NEW: هندلر انتخاب ایموجی احساسی
async def emotion_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    value = query.data.replace("emotion_", "")

    if value == "skip":
        context.user_data["selected_emotion"] = None
        preview = "مطمئنی می‌خوای این پیام رو به‌صورت ناشناس بفرستی؟"
    else:
        context.user_data["selected_emotion"] = value
        preview = f"حست: {value}\n\nمطمئنی می‌خوای این پیام رو به‌صورت ناشناس بفرستی؟"

    confirm_keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ ارسال کن", callback_data="confirm_send"),
        InlineKeyboardButton("❌ لغو", callback_data="cancel_send"),
    ]])

    await query.message.edit_text(preview, reply_markup=confirm_keyboard)


# NEW: فال روزانه
async def fal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    emoji, text = get_daily_fal(uid)
    await update.message.reply_text(
        f"{emoji} فال امروز تو:\n\n{text}\n\n✨ فردا برگرد برای فال جدید!",
        reply_markup=MAIN_MENU
    )


# NEW: شروع تست شخصیت
async def personality_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["pq_answers"] = []
    await update.message.reply_text(
        "🧠 تست شخصیت شروع شد!\n۵ سوال داریم، صادقانه انتخاب کن 💫\n\n"
        f"سوال ۱ از ۵:\n{PERSONALITY_QUESTIONS[0]['q']}",
        reply_markup=personality_keyboard(0)
    )


# NEW: هندلر جواب‌های تست شخصیت
async def personality_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, q_index_str, val = query.data.split("_", 2)
    q_index = int(q_index_str)

    answers = context.user_data.get("pq_answers", [])
    answers.append(val)
    context.user_data["pq_answers"] = answers

    next_q = q_index + 1

    if next_q < len(PERSONALITY_QUESTIONS):
        await query.message.edit_text(
            f"سوال {next_q + 1} از {len(PERSONALITY_QUESTIONS)}:\n{PERSONALITY_QUESTIONS[next_q]['q']}",
            reply_markup=personality_keyboard(next_q)
        )
    else:
        title, desc, animal = get_personality_result(answers)
        context.user_data["pq_answers"] = []
        await query.message.edit_text(
            f"✨ نتیجه تست شخصیت تو:\n\n"
            f"🏷️ {title}\n"
            f"🐾 روح حیوانیت: {animal}\n\n"
            f"💬 {desc}\n\n"
            f"می‌تونی دوباره امتحان کنی یا پیام ناشناس بفرستی 💌"
        )


async def deliver_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, msg_id: int):
    query = update.callback_query
    uid = query.from_user.id
    chat_id = query.message.chat_id
    code = get_or_create_code(uid)

    # NEW: ایموجی احساسی رو اضافه می‌کنیم
    emotion = context.user_data.get("selected_emotion", "")
    emotion_text = f"حس کاربر: {emotion}\n" if emotion else ""

    caption_prefix = f"📩 پیام جدید\nکد کاربر: {code}\n{emotion_text}\n"
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("✏️ پاسخ", callback_data=f"reply_{code}")]]
    )

    try:
        await context.bot.copy_message(
            chat_id=ADMIN_ID,
            from_chat_id=chat_id,
            message_id=msg_id
        )
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=caption_prefix + "(پیام بالا 👆)",
            reply_markup=keyboard
        )
        increment_message_count(uid)
        log_message_to_file(uid, code, "پیام/مدیا ارسال شد")
    except Exception:
        logging.exception("خطا در ارسال پیام به ادمین")


# ---------- دستورات ادمین ----------
async def reply_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        parts = update.message.text.split(maxsplit=2)
        if len(parts) < 3:
            await update.message.reply_text("فرمت درست: /reply کد پیام")
            return
        code = int(parts[1])
        text = parts[2]
        uid = find_uid_by_code(code)
        if uid:
            await context.bot.send_message(uid, f"📨 پاسخ ادمین:\n{text}")
            await update.message.reply_text("ارسال شد ✔️")
        else:
            await update.message.reply_text("کاربر پیدا نشد")
    except Exception:
        logging.exception("خطا در دستور reply")
        await update.message.reply_text("خطا در دستور")


async def reply_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        return
    code = query.data.split("_")[1]
    context.user_data["awaiting_reply_to"] = int(code)
    await query.message.reply_text(
        f"✏️ پاسخ خودت رو برای کد {code} بفرست (فقط متن، به‌عنوان پیام بعدی)."
    )


async def admin_text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return False
    code = context.user_data.get("awaiting_reply_to")
    if code is None:
        return False
    uid = find_uid_by_code(code)
    if uid:
        await context.bot.send_message(uid, f"📨 پاسخ ادمین:\n{update.message.text}")
        await update.message.reply_text("ارسال شد ✔️")
    else:
        await update.message.reply_text("کاربر پیدا نشد")
    context.user_data["awaiting_reply_to"] = None
    return True


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    total = len(data["user_map"])
    blocked = len(data["blocked"])
    today = str(date.today())
    today_total = sum(data["msg_count"].get(uid, 0) for uid, d in data["msg_dates"].items() if d == today)
    await update.message.reply_text(
        f"📊 آمار بات:\nکل کاربران: {total}\nمسدودشده‌ها: {blocked}\nپیام‌های امروز: {today_total}"
    )


async def block_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        code = int(context.args[0])
        uid = find_uid_by_code(code)
        if not uid:
            await update.message.reply_text("کاربر پیدا نشد")
            return
        if uid not in data["blocked"]:
            data["blocked"].append(uid)
            save_data()
        await update.message.reply_text(f"کاربر با کد {code} مسدود شد.")
    except (IndexError, ValueError):
        await update.message.reply_text("فرمت درست: /block کد")


async def unblock_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        code = int(context.args[0])
        uid = find_uid_by_code(code)
        if uid and uid in data["blocked"]:
            data["blocked"].remove(uid)
            save_data()
            await update.message.reply_text(f"کاربر با کد {code} رفع مسدودیت شد.")
        else:
            await update.message.reply_text("کاربر مسدود نبود یا پیدا نشد.")
    except (IndexError, ValueError):
        await update.message.reply_text("فرمت درست: /unblock کد")


async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    text = update.message.text.partition(" ")[2]
    if not text:
        await update.message.reply_text("فرمت درست: /broadcast متن پیام")
        return
    sent, failed = 0, 0
    for uid in data["user_map"]:
        if int(uid) in data["blocked"]:
            continue
        try:
            await context.bot.send_message(int(uid), f"📢 پیام همگانی:\n{text}")
            sent += 1
        except Exception:
            failed += 1
    await update.message.reply_text(f"ارسال شد به {sent} نفر. ناموفق: {failed}")


# ---------- روتر اصلی پیام‌های متنی ----------
async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    handled = await admin_text_router(update, context)
    if not handled:
        await handle_incoming(update, context)


# ---------- روتر پیام‌های مدیا (عکس، ویس، ویدیو، استیکر، فایل) ----------
async def media_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if is_blocked(uid):
        await update.message.reply_text("⛔️ شما توسط ادمین مسدود شده‌اید.", reply_markup=MAIN_MENU)
        return

    context.user_data["pending_message"] = update.message.message_id
    # NEW: ریست ایموجی قبلی
    context.user_data["selected_emotion"] = None

    # NEW: اول انتخاب احساس
    await update.message.reply_text(
        "یه حس برای پیامت انتخاب کن 👇",
        reply_markup=emotion_keyboard()
    )


def main():
    threading.Thread(target=run_server, daemon=True).start()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("reply", reply_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("block", block_cmd))
    app.add_handler(CommandHandler("unblock", unblock_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))

    app.add_handler(CallbackQueryHandler(reply_button_handler, pattern=r"^reply_\d+$"))
    app.add_handler(CallbackQueryHandler(confirm_send_handler, pattern=r"^(confirm_send|cancel_send)$"))
    # NEW: هندلر انتخاب ایموجی
    app.add_handler(CallbackQueryHandler(emotion_handler, pattern=r"^emotion_.+$"))
    # NEW: هندلر تست شخصیت
    app.add_handler(CallbackQueryHandler(personality_answer_handler, pattern=r"^pq_\d+_.+$"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    app.add_handler(MessageHandler(
        filters.PHOTO | filters.VOICE | filters.VIDEO | filters.Sticker.ALL | filters.Document.ALL,
        media_router
    ))

    logging.info("شروع polling...")
    app.run_polling()


if __name__ == "__main__":
    main()
