import os
import logging
import requests
import uuid
from io import BytesIO
from datetime import datetime, timedelta

from telegram import (
    Update,
    InlineQueryResultArticle,
    InputTextMessageContent,
)
from telegram.ext import (
    Updater,
    CommandHandler,
    CallbackContext,
    InlineQueryHandler,
)

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# ---------------- CONFIG ----------------
# Put your token and API key here (already filled from your input)
TELEGRAM_TOKEN = "8364435423:AAHChh6rPlIPZyNbQhADyhU4AvVx-M4iU-Y"
CRYPTOPANIC_API = "32c081fac3f505448ff4890f076ee44a48405a91"

# OWNER_CHAT_ID: where auto-news will be sent by default.
# Set this to your Telegram numeric chat id or a channel id (like @yourchannel).
# If left as None, auto-news will not send automatically but command /news still works.
OWNER_CHAT_ID = None  # e.g. -1001234567890 or "@mychannel"

# Auto-news interval in seconds (default 3600 = 1 hour)
AUTO_NEWS_INTERVAL = 3600

# ---------------- LOGGING ----------------
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------------- COIN MAPPING ----------------
COIN_MAP = {
    "BTC": "bitcoin",
    "BITCOIN": "bitcoin",
    "ETH": "ethereum",
    "ETHEREUM": "ethereum",
    "DOGE": "dogecoin",
    "DOGECOIN": "dogecoin",
    "BNB": "binancecoin",
    "SOL": "solana",
    "XRP": "ripple",
    "ADA": "cardano",
    "DOT": "polkadot",
    "MATIC": "matic-network",
    "LTC": "litecoin",
    "BCH": "bitcoin-cash",
}

TOP_COINS = ["bitcoin", "ethereum", "binancecoin", "solana", "dogecoin"]

# ---------------- HELPERS ----------------
def coin_id_from_query(q: str):
    q = q.strip().lower()
    if q == "": 
        return None
    # direct id match
    if q in COIN_MAP.values():
        return q
    # symbol or name
    up = q.upper()
    if up in COIN_MAP:
        return COIN_MAP[up]
    # try simple heuristics: replace spaces
    q2 = q.replace(" ", "-")
    return q2

def get_price_by_id(coin_id: str):
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=usd"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        if coin_id in data and "usd" in data[coin_id]:
            return data[coin_id]["usd"]
        return None
    except Exception as e:
        logger.exception("Error fetching price")
        return None

def fetch_crypto_news(limit=5):
    try:
        url = f"https://cryptopanic.com/api/v1/posts/?auth_token={CRYPTOPANIC_API}&public=true&kind=news"
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            logger.warning("CryptoPanic returned status %s", r.status_code)
            return None, f"API error (status {r.status_code})"
        data = r.json()
        results = data.get("results", [])
        if not results:
            return [], None
        items = []
        for post in results[:limit]:
            title = post.get("title", "No title")
            link = post.get("url", "")
            provider = post.get("source", {}).get("title", "")
            published_at = post.get("published_at", "")
            items.append({"title": title, "url": link, "source": provider, "time": published_at})
        return items, None
    except Exception as e:
        logger.exception("Error fetching news")
        return None, str(e)

def fetch_market_chart(coin_id: str, days=7):
    try:
        url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart?vs_currency=usd&days={days}"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.exception("Error fetching market chart")
        return None

def make_price_chart(coin_id: str, days=7):
    data = fetch_market_chart(coin_id, days)
    if not data or "prices" not in data:
        return None
    prices = data["prices"]  # [[timestamp, price], ...]
    timestamps = [datetime.fromtimestamp(p[0] / 1000.0) for p in prices]
    vals = [p[1] for p in prices]
    plt.figure(figsize=(8,3))
    plt.plot(timestamps, vals)
    plt.title(f"{coin_id} price (last {days} days)")
    plt.xlabel("Date")
    plt.ylabel("Price (USD)")
    plt.tight_layout()
    buf = BytesIO()
    plt.savefig(buf, format="png")
    plt.close()
    buf.seek(0)
    return buf

# ---------------- COMMAND HANDLERS ----------------
def start(update: Update, context: CallbackContext):
    msg = (
        "👋 Welcome to Cryptopallab!\n\n"
        "📌 Commands:\n"
        "/price <coin> - get current price (symbol or name)\n"
        "/top - top 5 coins prices\n"
        "/news - latest crypto news\n"
        "/chart <coin> - 7 day price chart\n"
        "/help - this message\n\n"
        "Inline: type @YourBotUsername <coin> in any chat to get quick price."
    )
    update.message.reply_text(msg)

def help_cmd(update: Update, context: CallbackContext):
    start(update, context)

def price_cmd(update: Update, context: CallbackContext):
    if len(context.args) == 0:
        update.message.reply_text("Usage: /price BTC or /price bitcoin")
        return
    q = " ".join(context.args)
    coin_id = coin_id_from_query(q)
    if not coin_id:
        update.message.reply_text("Invalid coin query.")
        return
    price = get_price_by_id(coin_id)
    if price is None:
        update.message.reply_text("❌ Price not available or coin not found.")
        return
    update.message.reply_text(f"💰 {q.upper()} price: ${price}")

def top_cmd(update: Update, context: CallbackContext):
    texts = []
    for cid in TOP_COINS:
        price = get_price_by_id(cid)
        if price is None:
            texts.append(f"{cid}: n/a")
        else:
            texts.append(f"{cid}: ${price}")
    update.message.reply_text("📈 Top coins:\n" + "\n".join(texts))

def news_cmd(update: Update, context: CallbackContext):
    items, err = fetch_crypto_news(limit=5)
    if items is None and err:
        update.message.reply_text(f"❌ Error fetching news: {err}")
        return
    if not items:
        update.message.reply_text("❌ No news found!")
        return
    parts = []
    for it in items:
        parts.append(f"🔗 {it['title']}\n{it['url']}")
    update.message.reply_text("📰 Latest Crypto News:\n\n" + "\n\n".join(parts), disable_web_page_preview=True)

def chart_cmd(update: Update, context: CallbackContext):
    if len(context.args) == 0:
        update.message.reply_text("Usage: /chart BTC or /chart bitcoin")
        return
    q = " ".join(context.args)
    coin_id = coin_id_from_query(q)
    if not coin_id:
        update.message.reply_text("Invalid coin query.")
        return
    buf = make_price_chart(coin_id, days=7)
    if not buf:
        update.message.reply_text("❌ Could not fetch chart data.")
        return
    update.message.reply_photo(photo=buf, filename=f"{coin_id}_7d.png")

# ---------------- INLINE HANDLER ----------------
def inline_query(update: Update, context: CallbackContext):
    query = update.inline_query.query
    if not query:
        return
    coin_id = coin_id_from_query(query)
    if not coin_id:
        return
    price = get_price_by_id(coin_id)
    if price is None:
        text = f"{query}: price not available"
    else:
        text = f"{query.upper()} price: ${price}"
    results = [
        InlineQueryResultArticle(
            id=str(uuid.uuid4()),
            title=f"{query.upper()} price",
            input_message_content=InputTextMessageContent(text)
        )
    ]
    update.inline_query.answer(results[:10])

# ---------------- AUTO NEWS JOB ----------------
def hourly_news_job(context: CallbackContext):
    if not OWNER_CHAT_ID:
        logger.info("OWNER_CHAT_ID not set; skipping auto news send")
        return
    items, err = fetch_crypto_news(limit=5)
    if items is None and err:
        context.bot.send_message(chat_id=OWNER_CHAT_ID, text=f"❌ Error fetching news: {err}")
        return
    if not items:
        context.bot.send_message(chat_id=OWNER_CHAT_ID, text="❌ No news found!")
        return
    parts = []
    for it in items:
        parts.append(f"🔗 {it['title']}\n{it['url']}")
    context.bot.send_message(chat_id=OWNER_CHAT_ID, text="📰 Auto News Update:\n\n" + "\n\n".join(parts), disable_web_page_preview=True)

# ---------------- MAIN ----------------
def main():
    updater = Updater(TELEGRAM_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help_cmd))
    dp.add_handler(CommandHandler("price", price_cmd))
    dp.add_handler(CommandHandler("top", top_cmd))
    dp.add_handler(CommandHandler("news", news_cmd))
    dp.add_handler(CommandHandler("chart", chart_cmd))
    dp.add_handler(InlineQueryHandler(inline_query))

    # JobQueue for hourly news
    if AUTO_NEWS_INTERVAL and AUTO_NEWS_INTERVAL > 0:
        job_queue = updater.job_queue
        # first run after AUTO_NEWS_INTERVAL seconds, then repeat
        job_queue.run_repeating(hourly_news_job, interval=AUTO_NEWS_INTERVAL, first=10)

    updater.start_polling()
    logger.info("Bot started")
    updater.idle()

if __name__ == "__main__":
    main()
