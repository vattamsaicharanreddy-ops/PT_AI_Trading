
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import ContextTypes

# FIXED: Use persistent DB
from database import get_conn, put_conn, USE_POSTGRES, init_db

init_db()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN or "PASTE" in BOT_TOKEN:
    if os.path.exists("bot_token.txt"):
        with open("bot_token.txt") as f:
            BOT_TOKEN = f.read().strip()

WEBAPP_URL = os.getenv("WEBAPP_URL", os.getenv("RENDER_EXTERNAL_URL", "https://your-app.onrender.com")).strip()
BOT_USERNAME = os.getenv("BOT_USERNAME", "YourBot")

GROUP_LINK = "https://t.me/PT_AI_Trading_Group"
CHANNEL_LINK = "https://t.me/PT_AI_Trading"
SUPPORT_LINK = "https://t.me/PT_AI_Support"

CONFIG = {
    "COMPANY_NAME": "PT-AI Intelligent Trading System",
    "STATS": {"USERS": "50K+ Active Users","ASSETS": "$120M+ Assets Managed","WIN_RATE": "72.6% Win Rate","TRANSPARENT": "100% Transparent"},
    "BUTTONS": {"ENTER_MINI_APP": "🚀 Enter Mini App","INVITE": "👥 Invite friends","GROUP": "💸 PT-Group","CHANNEL": "📢 PT-Channel","SUPPORT": "🆘 Support","ABOUT": "🏢 About Company","FUNCTIONS": "⚙️ Functions","MENU": "📋 Menu"},
    "DIVIDER": "━━━━━━━━━━━━━━━━━━━━━",
    "FOOTER": "👇 Click the mini app below to open your control panel and start earning money."
}

def build_start_message():
    return f"🎉 Welcome to {CONFIG['COMPANY_NAME']}! Your AI trading system is ready."

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name or f"user_{uid}"
    args = context.args
    referred_by = args[0] if args else None
    
    # FIXED: Save to Postgres, not bot.db file
    conn = get_conn()
    try:
        cur = conn.cursor()
        ph = "%s" if USE_POSTGRES else "?"
        cur.execute(f"SELECT user_id FROM users WHERE user_id={ph}", (uid,))
        if not cur.fetchone():
            import datetime
            now = datetime.datetime.utcnow().isoformat()
            ref = None
            if referred_by:
                try:
                    ref_id = int(referred_by)
                    if ref_id != uid:
                        cur.execute(f"SELECT 1 FROM users WHERE user_id={ph}", (ref_id,))
                        if cur.fetchone(): ref = ref_id
                except: pass
            cur.execute(f"INSERT INTO users (user_id, username, referred_by, created_at, last_claim, last_auto_claim, current_tier) VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph})",
                       (uid, username, ref, now, now, now, 7))
            conn.commit()
            print(f"✅ New user saved to {'POSTGRES' if USE_POSTGRES else 'SQLITE'}: {uid}")
        cur.close()
    finally:
        put_conn(conn)

    keyboard = [
        [InlineKeyboardButton(CONFIG["BUTTONS"]["ENTER_MINI_APP"], web_app=WebAppInfo(url=f"{WEBAPP_URL}?tg_id={uid}&username={username}"))],
        [InlineKeyboardButton(CONFIG["BUTTONS"]["INVITE"], callback_data="invite")],
    ]
    await update.message.reply_text(build_start_message(), reply_markup=InlineKeyboardMarkup(keyboard))

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    # ... keep your original callback logic, but any DB access use get_conn() pattern
    if query.data == "menu":
        conn = get_conn()
        try:
            cur = conn.cursor()
            ph = "%s" if USE_POSTGRES else "?"
            cur.execute(f"SELECT balance, withdrawable FROM users WHERE user_id={ph}", (query.from_user.id,))
            row = cur.fetchone()
            cur.close()
        finally:
            put_conn(conn)
