import os
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# گرفتن اطلاعات از Environment Variables
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

user_map = {}
next_id = 1000


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global next_id
    uid = update.effective_user.id

    if uid not in user_map:
        user_map[uid] = next_id
        next_id += 1

    await update.message.reply_text("ربات فعال شد 👍 پیام شما ناشناس ارسال میشه")


async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global next_id
    uid = update.effective_user.id
    text = update.message.text

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

    except:
        await update.message.reply_text("خطا در دستور")


app = Application.builder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("reply", reply))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_msg))

app.run_polling()
