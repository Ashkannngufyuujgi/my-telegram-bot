import os
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

user_map = {}
next_id = 1000


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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global next_id
    uid = update.effective_user.id
    logging.info(f"دستور /start از کاربر {uid}")

    if uid not in user_map:
        user_map[uid] = next_id
        next_id += 1

    await update.message.reply_text("ربات فعال شد 👍 پیام شما ناشناس ارسال میشه")


async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global next_id
    uid = update.effective_user.id
    text = update.message.text
    logging.info(f"پیام از کاربر {uid}: {text}")

    if uid not in user_map:
        user_map[uid] = next_id
        next_id += 1

    code = user_map[uid]

    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=f"📩 پیام جدید\nکد کاربر: {code}\n\n{text}\n\nبرای پاسخ:\n/reply {code} جواب"
    )


async def reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    try:
        parts = update.message.text.split(maxsplit=2)

        if len(parts) < 3:
            await update.message.reply_text("فرمت درست: /reply کد جواب")
            return

        code = int(parts[1])
        msg = parts[2]

        target = None
        for uid, c in user_map.items():
            if c == code:
                target = uid
                break

        if target:
            await context.bot.send_message(target, f"📨 پاسخ:\n{msg}")
            await update.message.reply_text("ارسال شد ✔️")
        else:
            await update.message.reply_text("کاربر پیدا نشد")

    except Exception as e:
        logging.exception("خطا در دستور reply")
        await update.message.reply_text("خطا در دستور")


def main():
    logging.info(f"TOKEN موجود است: {bool(TOKEN)}")
    logging.info(f"ADMIN_ID: {ADMIN_ID}")

    threading.Thread(target=run_server, daemon=True).start()

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reply", reply))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))

    logging.info("شروع polling...")
    app.run_polling()


if __name__ == "__main__":
    main()
