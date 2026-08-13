
import os, sqlite3, datetime, urllib.parse
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN or "PASTE" in BOT_TOKEN:
    if os.path.exists("bot_token.txt"):
        with open("bot_token.txt") as f:
            BOT_TOKEN = f.read().strip()
    if (not BOT_TOKEN or "PASTE" in BOT_TOKEN) and os.path.exists(".env"):
        with open(".env") as f:
            for line in f:
                if "BOT_TOKEN" in line:
                    BOT_TOKEN = line.split("=")[1].strip().strip('"').strip("'")
                    break

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
conn.execute("""CREATE TABLE IF NOT EXISTS referral_logs (
 id INTEGER PRIMARY KEY AUTOINCREMENT, from_user INTEGER, to_user INTEGER, level INTEGER, deposit_amount REAL, bonus_amount REAL, bonus_percent REAL, created_at TEXT
)""")
conn.commit()

for sql in [
    "ALTER TABLE users ADD COLUMN created_at TEXT",
    "ALTER TABLE users ADD COLUMN last_withdraw_date TEXT",
    "ALTER TABLE users ADD COLUMN referred_by INTEGER",
    "ALTER TABLE users ADD COLUMN referral_earnings REAL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0",
    "ALTER TABLE referral_logs ADD COLUMN bonus_percent REAL"
]:
    try: conn.execute(sql)
    except: pass
conn.commit()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name or f"user_{uid}"
    full_name = update.effective_user.full_name or username
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
        conn.execute("INSERT INTO users (user_id, username, referred_by, created_at, last_claim, last_auto_claim, current_tier) VALUES (?,?,?,?,?,?,?)", (uid, username, ref, now, now, now, 7))
        conn.commit()
        if ref:
            ref_exists = conn.execute("SELECT user_id FROM users WHERE user_id=?", (ref,)).fetchone()
            if ref_exists:
                await update.message.reply_text(f"Invited by user {ref}! Your friend will earn 7% when you deposit.")

    # IMPORTANT: Pass real Telegram ID in WebApp URL - fixes 123456789 issue
    webapp_url_with_id = f"{WEBAPP_URL}?tg_id={uid}&username={urllib.parse.quote(username)}"
    if ref:
        webapp_url_with_id += f"&ref={ref}"

    keyboard = [
        [InlineKeyboardButton("Open PT_AI Trading App", web_app=WebAppInfo(url=webapp_url_with_id))],
        [InlineKeyboardButton("My Referral Link", callback_data="ref")],
        [InlineKeyboardButton("How Referral Works", callback_data="how")]
    ]
    
    row = conn.execute("SELECT balance, withdrawable, daily_percent, referral_earnings FROM users WHERE user_id=?", (uid,)).fetchone()
    bal = row[0] if row else 0
    wd = row[1] if row else 0
    pct = row[2] if row and row[2] else 0
    ref_earn = row[3] if row and len(row)>3 else 0
    ref_link = f"https://t.me/{BOT_USERNAME}?start={uid}"
    direct_count = conn.execute("SELECT COUNT(*) FROM users WHERE referred_by=?", (uid,)).fetchone()[0] or 0

    await update.message.reply_text(
        f"Welcome to PT_AI Trading, {full_name}!\n"
        f"ID: {uid}\n\n"
        f"Trading: ${bal:.2f} @ {pct:.1f}%/day\n"
        f"Withdrawable: ${wd:.2f}\n"
        f"Referral Earned: ${ref_earn:.2f}\n"
        f"Direct Referrals: {direct_count}\n\n"
        f"Referral: L1 7% L2-10 1% -> Withdrawable instantly!\n\n"
        f"Your link: {ref_link}\n\n"
        f"Deposit >= $20 to start AI (30 days).",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def ref_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = update.effective_user.id
    ref_link = f"https://t.me/{BOT_USERNAME}?start={uid}"
    if q.data == "ref":
        direct = conn.execute("SELECT user_id, username, total_deposit FROM users WHERE referred_by=?", (uid,)).fetchall()
        total_earn = conn.execute("SELECT COALESCE(SUM(bonus_amount),0) FROM referral_logs WHERE to_user=?", (uid,)).fetchone()[0] or 0
        text = f"Your Referral Stats:\n\nLink: {ref_link}\nDirect: {len(direct)}\nEarned: ${total_earn:.2f} -> Withdrawable\n\nBonus: L1 7%, L2-L10 1% each\nBonus added instantly!\n"
        if direct:
            text += "\nYour Referrals:\n"
            for d in direct[:10]:
                text += f"• {d[1] or d[0]} - ${d[2]:.2f}\n"
        await q.message.reply_text(text)
    elif q.data == "how":
        await q.message.reply_text(f"How Referral Works:\n1. Share: {ref_link}\n2. Friend deposits $100\n3. You get 7% = $7 to withdrawable\n4. L2-L10: 1% each\nAll bonuses -> Withdrawable!")

def main():
    print(f"Bot starting {BOT_TOKEN[:10]}... WebApp: {WEBAPP_URL}")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(ref_callback, pattern="^(ref|how)$"))
    app.run_polling()

if __name__ == "__main__":
    main()
