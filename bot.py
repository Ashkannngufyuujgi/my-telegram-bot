import os
import json
import logging
import threading
import random
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
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_ID", "").split(",")]
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME")  # مثلاً @mindarchive

DATA_FILE = "data.json"


# ---------- ذخیره و بازیابی داده‌ها ----------
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "user_map": {}, "next_id": 1000, "blocked": [],
        "msg_count": {}, "msg_dates": {}, "msg_total": {}
    }

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

data = load_data()
data["user_map"] = {str(k): v for k, v in data["user_map"].items()}
data.setdefault("msg_count", {})
data.setdefault("msg_dates", {})
data.setdefault("msg_total", {})


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
    uid = str(uid)
    today = str(date.today())
    if data["msg_dates"].get(uid) != today:
        data["msg_dates"][uid] = today
        data["msg_count"][uid] = 0
    data["msg_count"][uid] = data["msg_count"].get(uid, 0) + 1
    data["msg_total"][uid] = data["msg_total"].get(uid, 0) + 1
    save_data()


# ---------- عضویت اجباری ----------
async def is_member(bot, uid: int) -> bool:
    if not CHANNEL_USERNAME:
        return True
    try:
        member = await bot.get_chat_member(CHANNEL_USERNAME, uid)
        return member.status in ("member", "administrator", "creator")
    except Exception:
        return False

def join_keyboard() -> InlineKeyboardMarkup:
    channel = CHANNEL_USERNAME.lstrip("@") if CHANNEL_USERNAME else ""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 عضویت در کانال", url=f"https://t.me/{channel}")],
        [InlineKeyboardButton("✅ عضو شدم، تأیید کن", callback_data="check_join")],
    ])

async def check_membership(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    uid = update.effective_user.id
    if uid in ADMIN_IDS:
        return True
    if not await is_member(context.bot, uid):
        await update.message.reply_text(
            "🔒 برای ورود به آرشیو ذهن باید اول عضو کانال بشی 👇\n\n"
            "بعد از عضویت دکمه «✅ عضو شدم» رو بزن.",
            reply_markup=join_keyboard()
        )
        return False
    return True

async def check_join_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    if await is_member(context.bot, uid):
        await query.message.edit_text(
            "✅ عضویتت تأیید شد.\n\nبه آرشیو ذهن خوش اومدی 🖤"
        )
        get_or_create_code(uid)
        await context.bot.send_message(uid,
            "𝐌𝐢𝐧𝐝 𝐀𝐫𝐜𝐡𝐢𝐯𝐞⟆⸙\n\nبه آرشیو ذهن خوش اومدی 🖤\nاینجا یه جای آرومه برای فکر کردن، حس کردن، و نوشتن...",
            reply_markup=MAIN_MENU
        )
    else:
        await query.answer("❌ هنوز عضو کانال نشدی!", show_alert=True)


# ---------- محتوا ----------

MEDITATION_TEXTS = [
    "🧘‍♂️ چشماتو ببند...\n\nنفس عمیق بکش.\nهوا رو حس کن که میاد تو...\nو آروم بیرون میره.\n\nهر فکری که اومد، بذارش بره.\nتو فقط اینجایی. همین لحظه کافیه. 🌙",
    "🧘‍♀️ یه لحظه وایسا...\n\nچقدر وقته که به جای حس کردن، فقط فکر می‌کنی؟\n\nامشب فقط باش. نه برنامه، نه نگرانی.\nفقط تو و این لحظه‌ی ساکت. 🌿",
    "🧘‍♂️ آروم بگیر...\n\nذهن خسته نیاز به سکوت داره، نه جواب.\nامشب از خودت نخواه چیزی بفهمی.\nفقط نفس بکش و بذار باشی. 💆‍♂️",
    "🧘‍♀️ لحظه‌ای که توشی...\n\nنه گذشته‌ای که سنگینیه،\nنه آینده‌ای که نگرانشی.\nفقط همین نفس. همین لحظه. همین تو.\n\nاین کافیه. 🌙",
    "🧘‍♂️ امشب به خودت اجازه بده...\n\nاجازه بده خسته باشی.\nاجازه بده ندونی.\nاجازه بده فقط باشی، بدون اینکه کاری بکنی.\n\nاستراحت هم یه جور پیشرفته. 🌿",
    "🧘‍♀️ ذهنت رو خاموش کن...\n\nمثل یه صفحه‌ی سیاه که همه‌چیز روش پاک میشه.\nفکرها میان و میرن.\nتو فقط تماشا کن. قضاوت نکن.\n\nآروم باش. 💆‍♀️",
    "🧘‍♂️ یه سوال برای امشب...\n\nآخرین باری که واقعاً آروم بودی کِی بود؟\n\nشاید وقتشه دوباره پیداش کنی.\nنه تو گوشی، نه تو سروصدا.\nتو سکوت درونت. 🌙",
    "🧘‍♀️ نفس اول...\n\nعمیق بکش.\nبذار ریه‌هات پر بشن.\nحالا آروم بده بره.\n\nهر بار که نفس می‌کشی، یه بار از نو شروع می‌کنی. 🌿",
]

PROGRAMMING_FACTS = [
    "👨🏻‍💻 فکت برنامه‌نویسی:\n\nوقتی یه برنامه‌نویس بهتون میگه «تو شماره یک منی» خر ذوق نشید!\nتو برنامه‌نویسی شمارش از 0 شروع میشه.\nپس شما الویت دومشید 😂",
    "👨🏻‍💻 فکت برنامه‌نویسی:\n\n۹۰٪ از وقت یه برنامه‌نویس صرف پیدا کردن باگ میشه.\n۹٪ ایجاد باگ‌های جدید.\n۱٪ واقعاً کد نوشتن 🫠",
    "👨🏻‍💻 فکت برنامه‌نویسی:\n\nبرنامه‌نویسا دو جور خوابن:\n۱. قبل از دیباگ: نمی‌تونن بخوابن\n۲. بعد از دیباگ: نمی‌تونن بیدار بمونن 😂",
    "👨🏻‍💻 فکت برنامه‌نویسی:\n\nاگه کدت رو به یه دوست توضیح بدی و نصفه راه مشکل رو خودت پیدا کنی،\nبهش میگن Rubber Duck Debugging.\nیعنی بعضی وقتا یه اردک لاستیکی بهتر از Stack Overflow کمک می‌کنه 🦆",
    "👨🏻‍💻 فکت برنامه‌نویسی:\n\nاولین باگ تاریخ رو سال ۱۹۴۷ گریس هاپر پیدا کرد.\nیه حشره واقعی افتاده بود تو کامپیوتر و خرابش کرده بود.\nاز اون به بعد به خطاهای نرم‌افزاری «Bug» گفتن 🐛",
    "👨🏻‍💻 فکت برنامه‌نویسی:\n\nبرنامه‌نویسا به جای «نمی‌دونم» میگن:\n«باید بیشتر بررسی کنم» 😂\nاما هر دو یه معنی دارن.",
    "👨🏻‍💻 فکت برنامه‌نویسی:\n\nمتغیر نام‌گذاری کردن سخت‌ترین کار برنامه‌نوییه.\nیه تحقیق نشون داده ۴۰٪ از وقت کدنویسی صرف انتخاب اسم میشه.\nکه البته اسمش هم اشتباهه 😅",
    "👨🏻‍💻 فکت برنامه‌نویسی:\n\nدو نوع برنامه‌نویس داریم:\nاونایی که بکاپ می‌گیرن.\nاونایی که هنوز فاجعه‌ای ندیدن و بکاپ نمی‌گیرن 🙂",
]

QUOTES = [
    "🖤\n\nقرار بود شکفته بشم،\nشکافته شدم.",
    "🌙\n\nنه شیر شتر ماست میشه،\nنه چوب کج صاف میشه،\nو نه ذات خراب درست میشه.\nآنکه یکبار از مرامش نیش خوردی را نبخش...\n\n«پوست اندازی چه تغییری دهد در ذات مار.»",
    "🖤\n\nمن اضطراب اجتماعی ندارم،\nمن نفرت اجتماعی دارم.",
    "🌿\n\nآدم کسی رو نداشته باشه خیلی بهتره\nتا اینکه داشته باشه\nو منتظر توجه از طرفش باشه.",
    "🌙\n\nخستگی دیروز هنوز تو تنمه.\nبعضی چیزا یه شب نمیره.",
    "🖤\n\nبعضی آدما رو باید مثل کتاب‌های قدیمی بذاری رو قفسه.\nاحترامشون رو داری،\nامّا دیگه نمی‌خونیشون.",
    "🌙\n\nتنهایی وقتی دردناکه\nکه کنار یکی باشی\nو بازم تنها باشی.",
    "🖤\n\nبعضی وقتا سکوت\nنه از بی‌حرفیه،\nاز پر بودنه.",
    "🌿\n\nآدم باید یاد بگیره\nبعضی چیزارو نپرسه.\nجواباشون سنگین‌تر از سکوتن.",
    "🌙\n\nهرکی زود فراموش می‌کنه\nیا خیلی قوی‌ه\nیا خیلی تمرین کرده.",
]

SEND_CONFIRMATIONS = [
    "🌊 پیامت مثل یه بطری تو دریا فرستاده شد...",
    "🖤 رازت تو تاریکی گم شد...",
    "🌙 شب نگهش می‌داره...",
    "🌿 باد برد، دریا می‌دونه...",
    "💫 ستاره‌ای شد و رفت...",
    "🔮 جادو شد و فرستاده شد!",
    "🌌 پیامت تو کهکشان گم شد...",
    "🦋 پروانه‌ات پر زد!",
    "🕯️ شمعت روشنه، رازت رفت...",
    "⚡ مثل برق رفت!",
]


# ---------- منوی اصلی ----------
MAIN_MENU = ReplyKeyboardMarkup(
    [
        ["🧘‍♂️ مدیتیشن", "👨🏻‍💻 فکت برنامه‌نویسی"],
        ["🖤 جملات", "✉️ پیام ناشناس"],
    ],
    resize_keyboard=True
)

WELCOME_TEXT = (
    "𝐌𝐢𝐧𝐝 𝐀𝐫𝐜𝐡𝐢𝐯𝐞⟆⸙\n\n"
    "به آرشیو ذهن خوش اومدی 🖤\n\n"
    "اینجا یه جای آرومه\nبرای فکر کردن، حس کردن، و نوشتن...\n\n"
    "از منو پایین شروع کن 👇"
)


# ---------- دستورات اصلی ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ADMIN_IDS and not await is_member(context.bot, uid):
        await update.message.reply_text(
            "𝐌𝐢𝐧𝐝 𝐀𝐫𝐜𝐡𝐢𝐯𝐞⟆⸙\n\n"
            "🔒 برای ورود به آرشیو ذهن باید اول عضو کانال بشی 👇\n\n"
            "بعد از عضویت دکمه «✅ عضو شدم» رو بزن.",
            reply_markup=join_keyboard()
        )
        return
    get_or_create_code(uid)
    await update.message.reply_text(WELCOME_TEXT, reply_markup=MAIN_MENU)


async def handle_incoming(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text or ""

    # --- منو ---
    if text == "🧘‍♂️ مدیتیشن":
        msg = random.choice(MEDITATION_TEXTS)
        await update.message.reply_text(msg, reply_markup=MAIN_MENU)
        return

    if text == "👨🏻‍💻 فکت برنامه‌نویسی":
        msg = random.choice(PROGRAMMING_FACTS)
        await update.message.reply_text(msg, reply_markup=MAIN_MENU)
        return

    if text == "🖤 جملات":
        msg = random.choice(QUOTES)
        await update.message.reply_text(msg, reply_markup=MAIN_MENU)
        return

    if text == "✉️ پیام ناشناس":
        if not await check_membership(update, context):
            return
        if is_blocked(uid):
            await update.message.reply_text("⛔️ دسترسی شما محدود شده.", reply_markup=MAIN_MENU)
            return
        await update.message.reply_text(
            "✉️ پیام ناشناست رو بنویس 👇\n\n"
            "هیچ‌کس نمی‌فهمه کی فرستاده 🖤",
            reply_markup=MAIN_MENU
        )
        context.user_data["awaiting_anon_message"] = True
        return

    # --- پیام ناشناس ---
    if context.user_data.get("awaiting_anon_message"):
        if not await check_membership(update, context):
            return
        if is_blocked(uid):
            await update.message.reply_text("⛔️ دسترسی شما محدود شده.", reply_markup=MAIN_MENU)
            return
        context.user_data["pending_message"] = update.message.message_id
        context.user_data["awaiting_anon_message"] = False
        confirm_keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ ارسال کن", callback_data="confirm_send"),
            InlineKeyboardButton("❌ لغو", callback_data="cancel_send"),
        ]])
        await update.message.reply_text(
            "مطمئنی می‌خوای این پیام رو ناشناس بفرستی؟",
            reply_markup=confirm_keyboard
        )
        return


async def confirm_send_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "cancel_send":
        context.user_data["pending_message"] = None
        await query.message.edit_text("❌ پیام لغو شد.")
        return

    msg_id = context.user_data.get("pending_message")
    if not msg_id:
        await query.message.edit_text("پیامی پیدا نشد.")
        return

    await deliver_to_admins(update, context, msg_id)
    context.user_data["pending_message"] = None
    await query.message.edit_text(f"✅ {random.choice(SEND_CONFIRMATIONS)}")


async def deliver_to_admins(update: Update, context: ContextTypes.DEFAULT_TYPE, msg_id: int):
    query = update.callback_query
    uid = query.from_user.id
    chat_id = query.message.chat_id
    code = get_or_create_code(uid)

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✏️ پاسخ", callback_data=f"reply_{code}"),
        InlineKeyboardButton("👁 خوندم", callback_data=f"read_{code}_{uid}"),
    ]])

    for admin_id in ADMIN_IDS:
        try:
            await context.bot.copy_message(
                chat_id=admin_id,
                from_chat_id=chat_id,
                message_id=msg_id
            )
            await context.bot.send_message(
                chat_id=admin_id,
                text=f"📩 پیام ناشناس\nکد کاربر: {code}\n(پیام بالا 👆)",
                reply_markup=keyboard
            )
        except Exception:
            logging.exception(f"خطا در ارسال پیام به ادمین {admin_id}")

    increment_message_count(uid)


# ---------- هندلر مدیا (پیام ناشناس) ----------
async def media_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if not context.user_data.get("awaiting_anon_message"):
        await update.message.reply_text(
            "برای ارسال پیام ناشناس از منو «✉️ پیام ناشناس» رو بزن 👇",
            reply_markup=MAIN_MENU
        )
        return

    if not await check_membership(update, context):
        return

    if is_blocked(uid):
        await update.message.reply_text("⛔️ دسترسی شما محدود شده.", reply_markup=MAIN_MENU)
        return

    context.user_data["pending_message"] = update.message.message_id
    context.user_data["awaiting_anon_message"] = False

    confirm_keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ ارسال کن", callback_data="confirm_send"),
        InlineKeyboardButton("❌ لغو", callback_data="cancel_send"),
    ]])
    await update.message.reply_text(
        "مطمئنی می‌خوای این پیام رو ناشناس بفرستی؟",
        reply_markup=confirm_keyboard
    )


# ---------- هندلر خوندم ----------
async def read_receipt_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("✅ علامت‌گذاری شد!")
    if query.from_user.id not in ADMIN_IDS:
        return
    parts = query.data.split("_")
    uid = int(parts[2])
    try:
        await context.bot.send_message(uid, "👁 ادمین‌ها پیامتو خوندن.")
        await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✏️ پاسخ", callback_data=f"reply_{parts[1]}"),
            InlineKeyboardButton("✅ خونده شد", callback_data="noop"),
        ]]))
    except Exception:
        logging.exception("خطا در read receipt")


async def noop_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()


# ---------- دستورات ادمین ----------
async def reply_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id not in ADMIN_IDS:
        return
    code = query.data.split("_")[1]
    context.user_data["awaiting_reply_to"] = int(code)
    await query.message.reply_text(f"✏️ پاسخت رو برای کد {code} بفرست.")


async def admin_text_router(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    if update.effective_user.id not in ADMIN_IDS:
        return False
    code = context.user_data.get("awaiting_reply_to")
    if code is None:
        return False
    uid = find_uid_by_code(code)
    if uid:
        await context.bot.send_message(uid, f"📨 پاسخ ادمین‌ها:\n{update.message.text}")
        await update.message.reply_text("ارسال شد ✔️")
    else:
        await update.message.reply_text("کاربر پیدا نشد.")
    context.user_data["awaiting_reply_to"] = None
    return True


async def reply_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    try:
        parts = update.message.text.split(maxsplit=2)
        if len(parts) < 3:
            await update.message.reply_text("فرمت: /reply کد پیام")
            return
        code = int(parts[1])
        uid = find_uid_by_code(code)
        if uid:
            await context.bot.send_message(uid, f"📨 پاسخ ادمین‌ها:\n{parts[2]}")
            await update.message.reply_text("ارسال شد ✔️")
        else:
            await update.message.reply_text("کاربر پیدا نشد.")
    except Exception:
        await update.message.reply_text("خطا در دستور.")


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    total = len(data["user_map"])
    blocked = len(data["blocked"])
    today = str(date.today())
    today_total = sum(
        data["msg_count"].get(uid, 0)
        for uid, d in data["msg_dates"].items() if d == today
    )
    await update.message.reply_text(
        f"📊 آمار:\nکل کاربران: {total}\nمسدود: {blocked}\nپیام‌های امروز: {today_total}"
    )


async def block_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    try:
        code = int(context.args[0])
        uid = find_uid_by_code(code)
        if not uid:
            await update.message.reply_text("کاربر پیدا نشد.")
            return
        if uid not in data["blocked"]:
            data["blocked"].append(uid)
            save_data()
        await update.message.reply_text(f"کد {code} مسدود شد.")
    except (IndexError, ValueError):
        await update.message.reply_text("فرمت: /block کد")


async def unblock_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    try:
        code = int(context.args[0])
        uid = find_uid_by_code(code)
        if uid and uid in data["blocked"]:
            data["blocked"].remove(uid)
            save_data()
            await update.message.reply_text(f"کد {code} رفع مسدودیت شد.")
        else:
            await update.message.reply_text("کاربر مسدود نبود یا پیدا نشد.")
    except (IndexError, ValueError):
        await update.message.reply_text("فرمت: /unblock کد")


async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    text = update.message.text.partition(" ")[2]
    if not text:
        await update.message.reply_text("فرمت: /broadcast متن")
        return
    sent, failed = 0, 0
    for uid in data["user_map"]:
        if int(uid) in data["blocked"]:
            continue
        try:
            await context.bot.send_message(int(uid), f"📢 {text}")
            sent += 1
        except Exception:
            failed += 1
    await update.message.reply_text(f"ارسال به {sent} نفر. ناموفق: {failed}")


# ---------- HTTP server برای Render ----------
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Mind Archive Bot is running")
    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()
    def log_message(self, format, *args):
        pass

def run_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()


# ---------- روتر اصلی ----------
async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    handled = await admin_text_router(update, context)
    if not handled:
        await handle_incoming(update, context)


def main():
    threading.Thread(target=run_server, daemon=True).start()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reply", reply_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("block", block_cmd))
    app.add_handler(CommandHandler("unblock", unblock_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))

    app.add_handler(CallbackQueryHandler(check_join_handler, pattern=r"^check_join$"))
    app.add_handler(CallbackQueryHandler(reply_button_handler, pattern=r"^reply_\d+$"))
    app.add_handler(CallbackQueryHandler(read_receipt_handler, pattern=r"^read_\d+_\d+$"))
    app.add_handler(CallbackQueryHandler(noop_handler, pattern=r"^noop$"))
    app.add_handler(CallbackQueryHandler(confirm_send_handler, pattern=r"^(confirm_send|cancel_send)$"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    app.add_handler(MessageHandler(
        filters.PHOTO | filters.VOICE | filters.VIDEO | filters.Sticker.ALL | filters.Document.ALL,
        media_router
    ))

    logging.info("Mind Archive Bot started...")
    app.run_polling()


if __name__ == "__main__":
    main()
