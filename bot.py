import os
import json
import logging
import threading
import asyncio
import aiohttp
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
    return {"user_map": {}, "next_id": 1000, "blocked": [], "msg_count": {}, "msg_dates": {}, "msg_total": {}, "challenge_done": {}, "challenge_counts": {}, "feelings_jar": {}}

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

data = load_data()
data["user_map"] = {str(k): v for k, v in data["user_map"].items()}
data.setdefault("msg_count", {})
data.setdefault("msg_dates", {})
data.setdefault("msg_total", {})
data.setdefault("challenge_done", {})
data.setdefault("challenge_counts", {})
data.setdefault("feelings_jar", {})


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


def log_message_to_file(uid: int, code: int, content: str):
    try:
        with open("messages_log.txt", "a", encoding="utf-8") as f:
            f.write(f"[{date.today()}] uid={uid} code={code} | {content}\n")
    except Exception:
        logging.exception("خطا در ثبت لاگ پیام")


# ---------- گیمیفیکیشن ----------
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


# ---------- قیمت لحظه‌ای ----------

def fmt_toman(value: float) -> str:
    return f"{int(value):,}"

def fmt_usd(value: float) -> str:
    if value >= 1:
        return f"${value:,.2f}"
    elif value >= 0.01:
        return f"${value:.4f}"
    else:
        return f"${value:.6f}"

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

COIN_EMOJI = {
    "bitcoin": "₿", "ethereum": "Ξ", "tether": "💲",
    "binancecoin": "🔶", "solana": "◎", "xrp": "〽️",
    "usd-coin": "💵", "dogecoin": "🐶", "cardano": "🔵",
    "tron": "🔴", "avalanche-2": "🏔️", "shiba-inu": "🐕",
    "polkadot": "⚪", "chainlink": "🔗", "matic-network": "🟣",
}

async def fetch_irr_prices(session: aiohttp.ClientSession) -> dict:
    result = {}

    # اول چک می‌کنیم ادمین نرخ دستی تنظیم کرده یا نه
    manual_usd = os.getenv("USD_TOMAN")
    if manual_usd:
        try:
            result["usd"] = float(manual_usd)
            logging.info(f"USD rate from env: {result['usd']} toman")
        except ValueError:
            pass

    # اگه نرخ دستی نبود، از API های ایرانی بگیر (نرخ بازار آزاد)
    if not result.get("usd"):
        IRAN_APIS = [
            {
                "url": "https://brsapi.ir/FreeTsetmcBourseApi/Api_Free_Gold_Currency.json",
                "extractor": lambda j: float(
                    next((
                        item.get("price", 0)
                        for item in j.get("currency", [])
                        if str(item.get("symbol", "")).upper() in ("USD", "DOLLAR", "دلار")
                    ), 0)
                )
            },
            {
                "url": "https://brsapi.ir/FreeTsetmcBourseApi/Api_Free_Gold_Currency_v2.json",
                "extractor": lambda j: float((j.get("USD") or j.get("usd") or {}).get("price", 0))
            },
            {
                "url": "https://api.priceto.day/v1/latest/irr/usd",
                "extractor": lambda j: float(j.get("price", 0)) / 10  # IRR به تومان
            },
        ]
        for api in IRAN_APIS:
            try:
                async with session.get(
                    api["url"],
                    headers=BROWSER_HEADERS,
                    timeout=aiohttp.ClientTimeout(total=8)
                ) as resp:
                    if resp.status == 200:
                        j = await resp.json(content_type=None)
                        price = api["extractor"](j)
                        if price > 10000:  # sanity check
                            result["usd"] = price
                            logging.info(f"USD from {api['url']}: {price}")
                            break
                        else:
                            logging.warning(f"USD price too low from {api['url']}: {price} — raw: {str(j)[:300]}")
            except Exception as e:
                logging.warning(f"Iran USD API error ({api['url']}): {e}")

    # طلا از metals.live بر اساس نرخ بازار آزاد
    irr_per_usd = result.get("usd", 0)
    if irr_per_usd > 0:
        try:
            async with session.get(
                "https://api.metals.live/v1/spot",
                headers=BROWSER_HEADERS,
                timeout=aiohttp.ClientTimeout(total=8)
            ) as resp:
                if resp.status == 200:
                    metals = await resp.json(content_type=None)
                    gold_usd_oz = 0
                    for item in metals:
                        if isinstance(item, dict):
                            gold_usd_oz = float(item.get("gold") or 0)
                            if gold_usd_oz > 0:
                                break
                    if gold_usd_oz > 0:
                        gold_usd_gram = gold_usd_oz / 31.1035
                        gold18_usd = gold_usd_gram * 0.75
                        result["gold18"] = gold18_usd * irr_per_usd
                        result["mesghal"] = gold18_usd * 4.608 * irr_per_usd
        except Exception as e:
            logging.warning(f"metals.live error: {e}")

    return result


async def fetch_crypto_prices(session: aiohttp.ClientSession) -> list:
    try:
        async with session.get(
            "https://api.coingecko.com/api/v3/coins/markets",
            params={
                "vs_currency": "usd",
                "order": "market_cap_desc",
                "per_page": 10,
                "page": 1,
                "sparkline": "false",
                "price_change_percentage": "24h",
            },
            headers=BROWSER_HEADERS,
            timeout=aiohttp.ClientTimeout(total=12)
        ) as resp:
            if resp.status == 200:
                coins = await resp.json(content_type=None)
                if isinstance(coins, list) and len(coins) > 0:
                    return [
                        {
                            "id": c.get("id", ""),
                            "symbol": c.get("symbol", "").upper(),
                            "name": c.get("name", ""),
                            "price": float(c.get("current_price") or 0),
                            "change24h": float(c.get("price_change_percentage_24h") or 0),
                        }
                        for c in coins
                    ]
    except Exception as e:
        logging.warning(f"CoinGecko خطا: {e}")

    try:
        async with session.get(
            "https://api.coincap.io/v2/assets",
            params={"limit": 10},
            headers=BROWSER_HEADERS,
            timeout=aiohttp.ClientTimeout(total=12)
        ) as resp:
            if resp.status == 200:
                j = await resp.json(content_type=None)
                assets = j.get("data", [])
                return [
                    {
                        "id": a.get("id", ""),
                        "symbol": (a.get("symbol") or "").upper(),
                        "name": a.get("name", ""),
                        "price": float(a.get("priceUsd") or 0),
                        "change24h": float(a.get("changePercent24Hr") or 0),
                    }
                    for a in assets
                ]
    except Exception as e:
        logging.warning(f"CoinCap خطا: {e}")

    return []

async def fetch_prices() -> str:
    lines = []
    usd_buy = 0

    async with aiohttp.ClientSession() as session:
        irr, crypto = await asyncio.gather(
            fetch_irr_prices(session),
            fetch_crypto_prices(session),
            return_exceptions=True
        )

    if isinstance(irr, dict) and irr.get("usd"):
        usd_buy = irr["usd"]
        gold18 = irr.get("gold18", 0)
        mesghal = irr.get("mesghal", 0)

        lines.append("<b>💵 ارز و طلا</b> (تومان | دلار)\n")
        lines.append(f"🇺🇸 دلار آمریکا: <code>{fmt_toman(usd_buy)}</code> تومان")
        if gold18:
            lines.append(f"🥇 طلا ۱۸ عیار (هر گرم): <code>{fmt_toman(gold18)}</code> تومان | <code>{fmt_usd(gold18 / usd_buy)}</code>")
        if mesghal:
            lines.append(f"🪙 مثقال طلا: <code>{fmt_toman(mesghal)}</code> تومان | <code>{fmt_usd(mesghal / usd_buy)}</code>")
    else:
        lines.append("<b>💵 ارز و طلا</b>\n⚠️ در حال حاضر قیمت دریافت نشد. بعداً امتحان کن.")

    lines.append("")

    if isinstance(crypto, list) and len(crypto) > 0:
        lines.append("<b>🪙 ۱۰ ارز دیجیتال برتر</b> (دلار | تومان)\n")
        for coin in crypto:
            cid = coin["id"]
            symbol = coin["symbol"]
            name = coin["name"]
            price_usd = coin["price"]
            change_24h = coin["change24h"]
            arrow = "📈" if change_24h >= 0 else "📉"
            emoji = COIN_EMOJI.get(cid, "🔹")
            toman_str = f" | <code>{fmt_toman(int(price_usd * usd_buy))}</code> تومان" if usd_buy and price_usd * usd_buy > 0 else ""
            lines.append(
                f"{emoji} {name} ({symbol}): <code>{fmt_usd(price_usd)}</code>{toman_str} {arrow} {change_24h:+.1f}%"
            )
    else:
        lines.append("<b>🪙 ارز دیجیتال</b>\n⚠️ در حال حاضر قیمت دریافت نشد. بعداً امتحان کن.")

    lines.append(f"\n🕐 آخرین بروزرسانی: {date.today()}")
    return "\n".join(lines)


async def debugprice_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    results = []
    urls = [
        ("brsapi v1", "https://brsapi.ir/FreeTsetmcBourseApi/Api_Free_Gold_Currency.json", "json"),
        ("brsapi v2", "https://brsapi.ir/FreeTsetmcBourseApi/Api_Free_Gold_Currency_v2.json", "json"),
        ("priceto.day", "https://api.priceto.day/v1/latest/irr/usd", "json"),
    ]
    async with aiohttp.ClientSession() as session:
        for name, url, kind in urls:
            try:
                async with session.get(url, headers=BROWSER_HEADERS, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    body = await resp.text()
                    snippet = body[:400].replace("<", "&lt;").replace(">", "&gt;")
                    results.append(f"✅ {name} [{resp.status}]\n<code>{snippet}</code>")
            except Exception as e:
                results.append(f"❌ {name}: {e}")
    await update.message.reply_text("\n\n".join(results), parse_mode="HTML")


async def price_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    waiting_msg = await update.message.reply_text("⏳ در حال دریافت قیمت‌ها...")
    try:
        text = await fetch_prices()
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=MAIN_MENU)
    except Exception as e:
        logging.exception("خطا در price_cmd")
        await update.message.reply_text(
            f"⚠️ خطای دقیق:\n<code>{str(e)[:300]}</code>",
            parse_mode="HTML",
            reply_markup=MAIN_MENU
        )
    finally:
        try:
            await waiting_msg.delete()
        except Exception:
            pass


# ---------- فال روزانه ----------
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


# ---------- چالش روزانه ----------
CHALLENGE_POOL = [
    ("🌸", "امروز به یه نفر که مدتیه باهاش حرف نزدی پیام بده."),
    ("☀️", "صبح از پنجره به آسمون نگاه کن و یه چیز قشنگ توش پیدا کن."),
    ("📖", "یه صفحه از یه کتاب بخون، حتی اگه حوصله نداشتی."),
    ("🎵", "یه آهنگ که دوست داری با صدای بلند گوش بده."),
    ("💌", "یه چیز مثبت درباره خودت روی کاغذ بنویس."),
    ("🌿", "۱۰ دقیقه از گوشی دور باش و فقط نفس بکش."),
    ("🍵", "یه چیز گرم بنوش و آروم بشین، بدون گوشی."),
    ("🌙", "امشب قبل از خواب ۳ تا چیزی که امروز ازشون ممنونی بنویس."),
    ("💃", "یه موزیک شاد بذار و ۲ دقیقه برقص، حتی اگه تنها باشی."),
    ("🎨", "یه چیزی بکش، حتی اگه نقاشی بلد نیستی. هر چیزی."),
    ("🌺", "به یه نفر بگو که دوستش داری یا بهش اهمیت می‌دی."),
    ("🧘", "۵ دقیقه چشماتو ببند و به هیچی فکر نکن."),
    ("📸", "از یه چیز قشنگ اطرافت عکس بگیر."),
    ("🍫", "امروز یه چیز کوچیک به خودت هدیه بده."),
    ("🚶", "۱۰ دقیقه پیاده‌روی کن، حتی توی خونه."),
    ("⭐", "یه آرزو بکن و باور کن که ممکنه."),
    ("🦋", "یه عادت بد امروز رو نکن، فقط یه روز."),
    ("🌊", "یه لیوان آب بنوش و به بدنت مهربون باش."),
    ("💫", "یه چیزی که مدتیه ازش فرار می‌کنی رو امروز شروع کن."),
    ("🎀", "یه لباس یا چیزی که خوشحالت می‌کنه بپوش."),
    ("🌻", "به یه نفر لبخند بزن، حتی غریبه."),
    ("🔮", "یه چیز جدید امتحان کن، هر چیزی."),
    ("🍀", "سه تا چیز خوب که امروز داری رو بشمار."),
    ("🕊️", "یه نفر رو ببخش، حتی توی ذهنت."),
    ("🌈", "یه رنگ شاد بپوش یا دورت بذار."),
    ("💎", "به خودت نگاه کن توی آینه و یه چیز قشنگ ببین."),
    ("🌝", "زودتر از همیشه بخواب امشب."),
    ("🍓", "یه میوه یا چیز سالم بخور با حوصله."),
    ("🪷", "یه موزیک آروم گوش بده و فقط حس کن."),
    ("✨", "امروز یه نفر رو تحسین کن و بهش بگو."),
]

def get_daily_challenge(uid: int) -> tuple:
    today = str(date.today())
    seed = hash(f"ch_{uid}_{today}") % len(CHALLENGE_POOL)
    return CHALLENGE_POOL[seed]

def has_done_challenge_today(uid: int) -> bool:
    return data["challenge_done"].get(str(uid)) == str(date.today())

def mark_challenge_done(uid: int):
    uid_str = str(uid)
    data["challenge_done"][uid_str] = str(date.today())
    data["challenge_counts"][uid_str] = data["challenge_counts"].get(uid_str, 0) + 1
    save_data()

def get_challenge_count(uid: int) -> int:
    return data["challenge_counts"].get(str(uid), 0)


# ---------- تست شخصیت ----------
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


# ---------- شیشه احساسات ----------
FEELING_EMOJIS = ["😊", "😢", "😡", "😍", "😰", "😴", "🥳", "🫠", "💪", "🥺"]

FEELING_LABELS = {
    "😊": "شاد", "😢": "غمگین", "😡": "عصبانی", "😍": "عاشق",
    "😰": "نگران", "😴": "خسته", "🥳": "هیجان‌زده", "🫠": "بی‌حال",
    "💪": "قوی", "🥺": "دلتنگ"
}

def feelings_jar_keyboard() -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(e, callback_data=f"jar_{e}") for e in FEELING_EMOJIS]
    rows = [buttons[:5], buttons[5:]]
    return InlineKeyboardMarkup(rows)

def add_feeling(uid: int, emoji: str):
    uid_str = str(uid)
    if uid_str not in data["feelings_jar"]:
        data["feelings_jar"][uid_str] = []
    data["feelings_jar"][uid_str].append({"date": str(date.today()), "emoji": emoji})
    data["feelings_jar"][uid_str] = data["feelings_jar"][uid_str][-30:]
    save_data()

def build_jar_summary(uid: int) -> str:
    uid_str = str(uid)
    entries = data["feelings_jar"].get(uid_str, [])
    if not entries:
        return "شیشه‌ات خالیه! هنوز هیچ احساسی ثبت نکردی. 🫙"

    from collections import Counter
    counts = Counter(e["emoji"] for e in entries)
    total = len(entries)
    top_emoji, top_count = counts.most_common(1)[0]
    top_label = FEELING_LABELS.get(top_emoji, "")

    lines = [f"🫙 شیشه احساسات تو ({total} روز ثبت‌شده):\n"]
    for emoji, count in counts.most_common():
        label = FEELING_LABELS.get(emoji, "")
        bar = "█" * count
        lines.append(f"{emoji} {label}: {bar} ({count})")

    lines.append(f"\n💬 بیشتر از همه {top_emoji} {top_label} بودی.")
    return "\n".join(lines)

def build_jar_summary_by_code(code: int) -> str:
    uid = find_uid_by_code(code)
    if not uid:
        return "کاربر پیدا نشد."
    return build_jar_summary(uid)


# ---------- برچسب احساسی ----------
EMOTION_EMOJIS = ["😊", "😢", "😡", "😍", "😂", "🤔", "😱", "🙏"]

def emotion_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(e, callback_data=f"emotion_{e}")
        for e in EMOTION_EMOJIS
    ]
    skip_button = InlineKeyboardButton("⏭ رد کردن", callback_data="emotion_skip")
    rows = [buttons[:4], buttons[4:], [skip_button]]
    return InlineKeyboardMarkup(rows)


# ---------- HTTP server برای Render ----------
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


# ---------- منوی پایین صفحه ----------
MAIN_MENU = ReplyKeyboardMarkup(
    [
        ["📝 پیام جدید", "ℹ️ راهنما"],
        ["📊 آمار من", "🔮 فال امروز"],
        ["🧠 تست شخصیت", "🎯 چالش امروز"],
        ["🫙 شیشه احساسات", "💹 قیمت لحظه‌ای"],
    ],
    resize_keyboard=True
)

HELP_TEXT = (
    "📋 راهنمای استفاده از ربات:\n\n"
    "• هر پیامی (متن، عکس، ویس، ویدیو، استیکر یا فایل) بفرستی، کاملاً ناشناس برای ادمین ارسال می‌شه.\n"
    "• هیچ‌وقت آیدی یا اسمت برای ادمین نمایش داده نمی‌شه، فقط یه کد عددی.\n"
    "• قبل از ارسال نهایی، یه حس انتخاب می‌کنی، بعد تأیید می‌کنی.\n"
    "• اگه ادمین جواب بده، همینجا برات پیام میاد.\n"
    "• با ارسال پیام بیشتر، رتبه‌ات بالاتر می‌ره! 🏆\n"
    "• با 💹 قیمت لحظه‌ای طلا، دلار و ارز دیجیتال رو ببین."
)


# ---------- دستورات کاربر ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    get_or_create_code(uid)
    await update.message.reply_text(
        "🎉 به ربات پیام ناشناس خوش اومدی!\n\n"
        "🔒 کاملاً ناشناس: هیچ‌وقت آیدی یا اسمت برای ادمین نمایش داده نمی‌شه.\n\n"
        "هر پیامی بفرستی، به‌صورت ناشناس برای ادمین ارسال می‌شه.",
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
    total_sent = data["msg_total"].get(uid_str, 0)
    rank = get_rank(uid)
    next_rank = get_next_rank_info(uid)
    await update.message.reply_text(
        f"📊 آمار شما:\n"
        f"کد شما: {code}\n"
        f"پیام‌های امروز: {sent_today}\n"
        f"کل پیام‌های ارسالی: {total_sent}\n\n"
        f"🏅 رتبه فعلی: {rank}\n"
        f"⬆️ {next_rank}\n\n"
        f"🎯 چالش‌های انجام‌شده: {get_challenge_count(uid)} تا",
        reply_markup=MAIN_MENU
    )


# ---------- جریان ارسال پیام با تأیید ----------
async def handle_incoming(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    text = update.message.text or ""

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
    if text == "🎯 چالش امروز":
        await challenge_cmd(update, context)
        return
    if text == "🫙 شیشه احساسات":
        await feelings_jar_cmd(update, context)
        return
    if text == "💹 قیمت لحظه‌ای":
        await price_cmd(update, context)
        return

    if is_blocked(uid):
        await update.message.reply_text("⛔️ شما توسط ادمین مسدود شده‌اید.", reply_markup=MAIN_MENU)
        return

    context.user_data["pending_message"] = update.message.message_id
    context.user_data["selected_emotion"] = None

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


async def fal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    emoji, text = get_daily_fal(uid)
    await update.message.reply_text(
        f"{emoji} فال امروز تو:\n\n{text}\n\n✨ فردا برگرد برای فال جدید!",
        reply_markup=MAIN_MENU
    )


async def personality_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["pq_answers"] = []
    await update.message.reply_text(
        "🧠 تست شخصیت شروع شد!\n۵ سوال داریم، صادقانه انتخاب کن 💫\n\n"
        f"سوال ۱ از ۵:\n{PERSONALITY_QUESTIONS[0]['q']}",
        reply_markup=personality_keyboard(0)
    )


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


async def challenge_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    emoji, text = get_daily_challenge(uid)
    count = get_challenge_count(uid)
    done_today = has_done_challenge_today(uid)

    if done_today:
        await update.message.reply_text(
            f"✅ چالش امروزت رو انجام دادی! خوووبی 🎉\n\n"
            f"🎯 کل چالش‌های انجام‌شده: {count}\n\n"
            f"فردا برگرد برای چالش جدید 💪",
            reply_markup=MAIN_MENU
        )
        return

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ انجامش دادم!", callback_data="challenge_done"),
        InlineKeyboardButton("🔄 بعداً", callback_data="challenge_later"),
    ]])
    await update.message.reply_text(
        f"{emoji} چالش امروز تو:\n\n{text}\n\n"
        f"🎯 چالش‌های قبلی: {count} تا\n\n"
        "وقتی انجامش دادی بگو 👇",
        reply_markup=keyboard
    )


async def challenge_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id

    if query.data == "challenge_done":
        if has_done_challenge_today(uid):
            await query.message.edit_text("قبلاً ثبت شده بود! ✅")
            return
        mark_challenge_done(uid)
        count = get_challenge_count(uid)
        await query.message.edit_text(
            f"🎉 آفرین! چالش امروزت ثبت شد.\n\n"
            f"🏅 کل چالش‌های انجام‌شده: {count} تا\n\n"
            f"{'🔥 داری می‌درخشی!' if count >= 10 else '💪 همینطور ادامه بده!'}"
        )
    elif query.data == "challenge_later":
        await query.message.edit_text(
            "باشه! یادت نره امروز انجامش بدی 😊\n"
            "هر وقت آماده شدی دوباره بزن روی 🎯 چالش امروز"
        )


async def feelings_jar_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    uid_str = str(uid)
    entries = data["feelings_jar"].get(uid_str, [])
    today = str(date.today())
    already_today = any(e["date"] == today for e in entries)

    summary = build_jar_summary(uid)

    if already_today:
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("📊 خلاصه احساساتم", callback_data="jar_summary"),
        ]])
        await update.message.reply_text(
            f"{summary}\n\n✅ امروز قبلاً احساست رو ثبت کردی.\nفردا برگرد 🫙",
            reply_markup=keyboard
        )
    else:
        await update.message.reply_text(
            f"{summary}\n\n امروز چه حسی داری؟ 👇",
            reply_markup=feelings_jar_keyboard()
        )


async def feelings_jar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id

    if query.data == "jar_summary":
        summary = build_jar_summary(uid)
        await query.message.edit_text(summary)
        return

    emoji = query.data.replace("jar_", "")
    if emoji not in FEELING_EMOJIS:
        return

    today = str(date.today())
    uid_str = str(uid)
    entries = data["feelings_jar"].get(uid_str, [])
    if any(e["date"] == today for e in entries):
        await query.message.edit_text("امروز قبلاً ثبت کردی! 🫙 فردا برگرد.")
        return

    add_feeling(uid, emoji)
    label = FEELING_LABELS.get(emoji, "")
    await query.message.edit_text(
        f"{emoji} احساس «{label}» برای امروز ثبت شد!\n\n"
        f"هر روز که بیای و احساستو ثبت کنی، شیشه‌ات پر‌تر می‌شه 🫙"
    )


async def jar_admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        code = int(context.args[0])
        summary = build_jar_summary_by_code(code)
        await update.message.reply_text(f"🫙 شیشه احساسات کد {code}:\n\n{summary}")
    except (IndexError, ValueError):
        if not data["feelings_jar"]:
            await update.message.reply_text("هنوز هیچ کسی احساسی ثبت نکرده.")
            return
        lines = ["🫙 کاربرایی که احساس ثبت کردن:\n"]
        for uid_str, entries in data["feelings_jar"].items():
            if not entries:
                continue
            code = data["user_map"].get(uid_str, "؟")
            lines.append(f"کد {code} — {len(entries)} ثبت")
        lines.append("\nبرای دیدن جزئیات: /jar کد")
        await update.message.reply_text("\n".join(lines))


async def setusd_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        rate = float(context.args[0].replace(",", ""))
        if rate < 10000:
            await update.message.reply_text("❌ عدد خیلی کمه. مثال: /setusd 95000")
            return
        os.environ["USD_TOMAN"] = str(rate)
        await update.message.reply_text(f"✅ نرخ دلار تنظیم شد: {int(rate):,} تومان")
    except (IndexError, ValueError):
        current = os.getenv("USD_TOMAN", "تنظیم نشده")
        await update.message.reply_text(
            f"نرخ فعلی: {current}\n\nبرای تنظیم: /setusd عدد\nمثال: /setusd 95000"
        )


async def deliver_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, msg_id: int):
    query = update.callback_query
    uid = query.from_user.id
    chat_id = query.message.chat_id
    code = get_or_create_code(uid)

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


# ---------- روتر اصلی ----------
async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    handled = await admin_text_router(update, context)
    if not handled:
        await handle_incoming(update, context)


async def media_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id

    if is_blocked(uid):
        await update.message.reply_text("⛔️ شما توسط ادمین مسدود شده‌اید.", reply_markup=MAIN_MENU)
        return

    context.user_data["pending_message"] = update.message.message_id
    context.user_data["selected_emotion"] = None

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
    app.add_handler(CommandHandler("jar", jar_admin_cmd))
    app.add_handler(CommandHandler("setusd", setusd_cmd))
    app.add_handler(CommandHandler("price", price_cmd))
    app.add_handler(CommandHandler("debugprice", debugprice_cmd))

    app.add_handler(CallbackQueryHandler(reply_button_handler, pattern=r"^reply_\d+$"))
    app.add_handler(CallbackQueryHandler(confirm_send_handler, pattern=r"^(confirm_send|cancel_send)$"))
    app.add_handler(CallbackQueryHandler(emotion_handler, pattern=r"^emotion_.+$"))
    app.add_handler(CallbackQueryHandler(personality_answer_handler, pattern=r"^pq_\d+_.+$"))
    app.add_handler(CallbackQueryHandler(challenge_callback_handler, pattern=r"^challenge_(done|later)$"))
    app.add_handler(CallbackQueryHandler(feelings_jar_callback, pattern=r"^jar_.+$"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    app.add_handler(MessageHandler(
        filters.PHOTO | filters.VOICE | filters.VIDEO | filters.Sticker.ALL | filters.Document.ALL,
        media_router
    ))

    logging.info("شروع polling...")
    app.run_polling()


if __name__ == "__main__":
    main()
