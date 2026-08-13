
import os, sqlite3, datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler

# Try to get token from multiple sources
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN or "PASTE" in BOT_TOKEN:
    # try reading from bot_token.txt
    if os.path.exists("bot_token.txt"):
        with open("bot_token.txt") as f:
            BOT_TOKEN = f.read().strip()
    # try reading from .env
    if (not BOT_TOKEN or "PASTE" in BOT_TOKEN) and os.path.exists(".env"):
        with open(".env") as f:
            for line in f:
                if "BOT_TOKEN" in line:
                    BOT_TOKEN = line.split("=")[1].strip().strip('"').strip("'")
                    break

if not BOT_TOKEN or "PASTE" in BOT_TOKEN:
    print("❌ ERROR: Bot token not set!")
    print("1. Go to @BotFather on Telegram")
    print("2. Send /mybots -> your bot -> API Token")
    print("3. Copy token")
    print("4. Create file bot_token.txt in this folder and paste token inside")
    print("   OR set env: $env:BOT_TOKEN='your_token'")
    exit(1)

WEBAPP_URL = os.getenv("WEBAPP_URL", os.getenv("RENDER_EXTERNAL_URL", "https://your-app.onrender.com"))
BOT_USERNAME = os.getenv("BOT_USERNAME", "YourBot")

# Remove existing https:// from WEBAPP_URL if user pasted full url with https
WEBAPP_URL = WEBAPP_URL.strip()

conn = sqlite3.connect("bot.db", check_same_thread=False, isolation_level=None)
conn.execute("""CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, balance REAL DEFAULT 0, withdrawable REAL DEFAULT 0, profit REAL DEFAULT 0, profit_per_hour REAL DEFAULT 0, daily_percent REAL DEFAULT 0, ai_start TEXT, ai_end TEXT, last_claim TEXT, last_auto_claim TEXT, total_deposit REAL DEFAULT 0, total_withdraw REAL DEFAULT 0, current_tier INTEGER DEFAULT 7, referred_by INTEGER, referral_earnings REAL DEFAULT 0)""")
conn.commit()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name or f"user_{uid}"
    args = context.args
    ref = None
    if args:
        try:
            ref = int(args[0])
            if ref == uid:
                ref = None
        except:
            ref = None

    exists = conn.execute("SELECT user_id FROM users WHERE user_id=?", (uid,)).fetchone()
    if not exists:
        now = datetime.datetime.utcnow().isoformat()
        conn.execute("INSERT INTO users (user_id, username, referred_by, last_claim, last_auto_claim) VALUES (?,?,?,?,?)", (uid, username, ref, now, now))
        conn.commit()
        if ref:
            await update.message.reply_text(f"🎉 Invited by user {ref}! Deposit to activate AI.")

    keyboard = [[InlineKeyboardButton("🚀 Open PT_AI Trading", web_app=WebAppInfo(url=WEBAPP_URL))],
                [InlineKeyboardButton("👥 My Referral Link", callback_data="ref")]]
    
    row = conn.execute("SELECT balance, withdrawable, daily_percent FROM users WHERE user_id=?", (uid,)).fetchone()
    bal = row[0] if row else 0
    wd = row[1] if row else 0
    pct = row[2] if row and row[2] else 0
    ref_link = f"https://t.me/{BOT_USERNAME}?start={uid}"

    await update.message.reply_text(
        f"💎 Welcome to PT_AI Trading, {username}!\n\n"
        f"💰 Trading: ${bal:.2f} @ {pct:.1f}%/day\n"
        f"💸 Withdrawable: ${wd:.2f}\n"
        f"👥 Referral: L1 7% • L2-10 1%\n\n"
        f"🔗 Your link: {ref_link}\n\n"
        f"Deposit ≥$20 to start AI (30 days). Tier upgrade resets timer.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def ref_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ref_link = f"https://t.me/{BOT_USERNAME}?start={uid}"
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(f"👥 Your 10-level referral link:\n{ref_link}\n\nL1: 7% L2-10: 1% each")

def main():
    print(f"✅ Bot starting with token {BOT_TOKEN[:10]}...")
    print(f"🌐 WebApp URL: {WEBAPP_URL}")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(ref_callback, pattern="ref"))
    app.run_polling()

if __name__ == "__main__":
    main()
