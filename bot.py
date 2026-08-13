
import os, sqlite3, datetime, urllib.parse
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN or "PASTE" in BOT_TOKEN:
    if os.path.exists("bot_token.txt"):
        with open("bot_token.txt") as f:
            BOT_TOKEN = f.read().strip()

if not BOT_TOKEN or "PASTE" in BOT_TOKEN:
    print("ERROR: Bot token not set!")
    exit(1)

WEBAPP_URL = os.getenv("WEBAPP_URL", os.getenv("RENDER_EXTERNAL_URL", "https://your-app.onrender.com"))
BOT_USERNAME = os.getenv("BOT_USERNAME", "YourBot")
WEBAPP_URL = WEBAPP_URL.strip().rstrip('/')

conn = sqlite3.connect("bot.db", check_same_thread=False, isolation_level=None)
conn.execute("""CREATE TABLE IF NOT EXISTS users (
 user_id INTEGER PRIMARY KEY, username TEXT, balance REAL DEFAULT 0, withdrawable REAL DEFAULT 0, profit REAL DEFAULT 0, profit_per_hour REAL DEFAULT 0, daily_percent REAL DEFAULT 0, ai_start TEXT, ai_end TEXT, last_claim TEXT, last_auto_claim TEXT, total_deposit REAL DEFAULT 0, total_withdraw REAL DEFAULT 0, current_tier INTEGER DEFAULT 7, referred_by INTEGER, referral_earnings REAL DEFAULT 0, created_at TEXT, last_withdraw_date TEXT, is_banned INTEGER DEFAULT 0
)""")
conn.commit()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name or f"user_{uid}"
    args = context.args
    ref = None
    if args:
        try:
            ref = int(args[0])
            if ref == uid: ref = None
        except: ref = None
    exists = conn.execute("SELECT user_id FROM users WHERE user_id=?", (uid,)).fetchone()
    if not exists:
        now = datetime.datetime.utcnow().isoformat()
        conn.execute("INSERT INTO users (user_id, username, referred_by, created_at, last_claim, last_auto_claim, current_tier) VALUES (?,?,?,?,?,?,?)", (uid, username, ref, now, now, now, 7))
        conn.commit()
    webapp_url_with_id = f"{WEBAPP_URL}?tg_id={uid}&username={urllib.parse.quote(username)}"
    if ref: webapp_url_with_id += f"&ref={ref}"
    keyboard = [[InlineKeyboardButton("Open PT_AI Trading App", web_app=WebAppInfo(url=webapp_url_with_id))]]
    row = conn.execute("SELECT balance, withdrawable, daily_percent FROM users WHERE user_id=?", (uid,)).fetchone()
    bal = row[0] if row else 0
    wd = row[1] if row else 0
    pct = row[2] if row and row[2] else 0
    ref_link = f"https://t.me/{BOT_USERNAME}?start={uid}"
    await update.message.reply_text(f"Welcome to PT_AI Trading, {username}!\nID: {uid} (Real Telegram ID)\n\nTrading: ${bal:.2f} @ {pct:.1f}%/day\nWithdrawable: ${wd:.2f}\n\nReferral: L1 7% L2-10 1% -> Withdrawable after verified deposit!\nMin deposit 20 USDT auto verified\n\nYour link: {ref_link}", reply_markup=InlineKeyboardMarkup(keyboard))

def main():
    print(f"Bot starting {BOT_TOKEN[:10]}... WebApp: {WEBAPP_URL}")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.run_polling()

if __name__ == "__main__":
    main()
