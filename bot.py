import os
import json
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
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

# ---------- ذخیره و بازیابی داده‌ها (پایدار، با فایل JSON) ----------
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"user_map": {}, "next_id": 1000, "blocked": []}

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

data = load_data()
data["user_map"] = {str(k): v for k, v in data["user_map"].items()}


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


# ---------- دستورات کاربر ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    get_or_create_code(uid)
    await update.message.reply_text(
        "ربات فعال شد 👍\n"
        "هر پیامی (متن، عکس، ویس، ویدیو یا استیکر) بفرستی، به‌صورت ناشناس برای ادمین ارسال می‌شه."
    )


async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if is_blocked(uid):
        await update.message.reply_text("⛔️ شما توسط ادمین مسدود شده‌اید.")
        return

    code = get_or_create_code(uid)
    caption_prefix = f"📩 پیام جدید\nکد کاربر: {code}\n\n"

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("✏️ پاسخ", callback_data=f"reply_{code}")]]
    )

    msg = update.message

    try:
        if msg.text:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=caption_prefix + msg.text,
                reply_markup=keyboard
            )
        elif msg.photo:
            await context.bot.send_photo(
                chat_id=ADMIN_ID,
                photo=msg.photo[-1].file_id,
                caption=caption_prefix + (msg.caption or ""),
                reply_markup=keyboard
            )
        elif msg.voice:
            await context.bot.send_voice(
                chat_id=ADMIN_ID,
                voice=msg.voice.file_id,
                caption=caption_prefix,
                reply_markup=keyboard
            )
        elif msg.video:
            await context.bot.send_video(
                chat_id=ADMIN_ID,
                video=msg.video.file_id,
                caption=caption_prefix + (msg.caption or ""),
                reply_markup=keyboard
            )
        elif msg.sticker:
            await context.bot.send_sticker(chat_id=ADMIN_ID, sticker=msg.sticker.file_id)
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=caption_prefix + "(استیکر بالا 👆)",
                reply_markup=keyboard
            )
        elif msg.document:
            await context.bot.send_document(
                chat_id=ADMIN_ID,
                document=msg.document.file_id,
                caption=caption_prefix + (msg.caption or ""),
                reply_markup=keyboard
            )
        else:
            await update.message.reply_text("این نوع پیام پشتیبانی نمی‌شه.")
            return

        await update.message.reply_text("✅ پیام شما ارسال شد.")

    except Exception:
        logging.exception("خطا در ارسال پیام به ادمین")
        await update.message.reply_text("خطا در ارسال پیام.")


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
    """اگه ادمین بعد از زدن دکمه پاسخ، یه پیام متنی بفرسته، همون رو به کاربر مربوطه می‌فرسته."""
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
    await update.message.reply_text(
        f"📊 آمار بات:\nکل کاربران: {total}\nمسدودشده‌ها: {blocked}"
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
        await handle_msg(update, context)


def main():
    threading.Thread(target=run_server, daemon=True).start()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reply", reply_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("block", block_cmd))
    app.add_handler(CommandHandler("unblock", unblock_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))

    app.add_handler(CallbackQueryHandler(reply_button_handler, pattern=r"^reply_\d+$"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    app.add_handler(MessageHandler(
        filters.PHOTO | filters.VOICE | filters.VIDEO | filters.Sticker.ALL | filters.Document.ALL,
        handle_msg
    ))

    logging.info("شروع polling...")
    app.run_polling()


if __name__ == "__main__":
    main()
