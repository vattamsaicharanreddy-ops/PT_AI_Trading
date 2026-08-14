
# ============================================================
# PT-AI TRADING - TELEGRAM START WITH BANNER + ABOUT + FUNCTIONS
# When user clicks /start -> Shows banner + company info + functions
# ============================================================

CONFIG = {
    # --- Banner (Top image like your screenshot) ---
    "BANNER_FILE": "banner.jpg",  # Put banner.jpg in same folder
    "BANNER_URL": "",  # Or set URL: https://your-domain.com/banner.jpg
    "BANNER_CAPTION": (
        "🚀 AI-Powered Trading.\n"
        "Built for Trust.\n\n"
        "Intelligent. Transparent. Secure.\n"
        "Let AI work for you, 24/7."
    ),

    # --- About Company ---
    "COMPANY_NAME": "PT-AI Intelligent Trading System",
    "COMPANY_ABOUT": (
        "🤖 About PT-AI Trading:\n"
        "PT-AI is an advanced AI-powered automated crypto trading platform. "
        "Our intelligent algorithms analyze real-time market opportunities and execute trades automatically. "
        "No trading experience needed! Secure, reliable, and transparent.\n\n"
        "🔒 Bank-level security to protect your assets\n"
        "🧠 Advanced AI algorithms for consistent results\n"
        "📊 Real-time data and verifiable results\n"
        "🎧 Professional team always here for you"
    ),

    # --- Stats (like in screenshot bottom of banner) ---
    "STATS": {
        "USERS": "50K+ Active Users",
        "ASSETS": "$120M+ Assets Managed",
        "WIN_RATE": "72.6% Win Rate",
        "TRANSPARENT": "100% Transparent"
    },

    # --- Functions / Features (shown when /start clicked) ---
    "FUNCTIONS": [
        "⚡ Real-time market opportunity analysis",
        "🤖 AI-powered automated trade execution",
        "📈 Daily investment returns of up to 11.2% to 18% — the more tokens you have, the higher your returns!",
        "💰 Earn up to 16% commission from your 10-level referral network!",
        "🔒 Secure & Reliable - Bank-level security",
        "🧠 AI-Powered Strategies - Advanced algorithms",
        "📊 Transparent Performance - Real-time verifiable results",
        "🎧 24/7 Support - Professional team"
    ],

    # --- Tiers Info ---
    "TIERS_TEXT": (
        "💎 Profit Tiers:\n"
        "• $20+ → 7.6% /day\n"
        "• $120+ → 8.9% /day\n"
        "• $500+ → 9.6% /day\n"
        "• $1200+ → 10.9% /day\n"
        "• $2500+ → 11.8% /day\n"
        "• $6000+ → 13.6% /day\n"
        "• $15000+ → 14.9% /day\n\n"
        "⏰ AI active 30 days per tier upgrade"
    ),

    # --- Links ---
    "GROUP_USERNAME": "PT-Group",
    "CHANNEL_USERNAME": "PT-Channel",
    "SUPPORT_USERNAME": "PT-Support",
    "GROUP_LINK": "https://t.me/PTGroup",
    "CHANNEL_LINK": "https://t.me/PTChannel",
    "SUPPORT_LINK": "https://t.me/PTSupport",

    # --- Buttons ---
    "BUTTONS": {
        "ENTER_MINI_APP": "🚀 Enter Mini App",
        "INVITE": "👥 Invite friends",
        "GROUP": "💸 PT-Group",
        "CHANNEL": "📢 PT-Channel",
        "SUPPORT": "🆘 Support",
        "ABOUT": "🏢 About Company",
        "FUNCTIONS": "⚙️ Functions",
        "MENU": "📋 Menu"
    },

    "DIVIDER": "━━━━━━━━━━━━━━━━━━━━━",
    "FOOTER": "👇 Click the mini app below to open your control panel and start earning money."
}

import os, sqlite3, datetime
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
    print("❌ Bot token not set!")
    exit(1)

WEBAPP_URL = os.getenv("WEBAPP_URL", os.getenv("RENDER_EXTERNAL_URL", "https://your-app.onrender.com")).strip()
BOT_USERNAME = os.getenv("BOT_USERNAME", "YourBot")

GROUP_LINK = os.getenv("GROUP_LINK", CONFIG["GROUP_LINK"])
CHANNEL_LINK = os.getenv("CHANNEL_LINK", CONFIG["CHANNEL_LINK"])
SUPPORT_LINK = os.getenv("SUPPORT_LINK", CONFIG["SUPPORT_LINK"])
GROUP_USERNAME = os.getenv("GROUP_USERNAME", CONFIG["GROUP_USERNAME"])
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", CONFIG["CHANNEL_USERNAME"])
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", CONFIG["SUPPORT_USERNAME"])
BANNER_URL = os.getenv("BANNER_URL", CONFIG["BANNER_URL"])
BANNER_FILE = os.getenv("BANNER_FILE", CONFIG["BANNER_FILE"])

conn = sqlite3.connect("bot.db", check_same_thread=False, isolation_level=None)
conn.execute("""CREATE TABLE IF NOT EXISTS users (
 user_id INTEGER PRIMARY KEY, username TEXT, balance REAL DEFAULT 0, withdrawable REAL DEFAULT 0,
 profit REAL DEFAULT 0, profit_per_hour REAL DEFAULT 0, daily_percent REAL DEFAULT 0,
 ai_start TEXT, ai_end TEXT, last_claim TEXT, last_auto_claim TEXT,
 total_deposit REAL DEFAULT 0, total_withdraw REAL DEFAULT 0,
 current_tier INTEGER DEFAULT 7, referred_by INTEGER, referral_earnings REAL DEFAULT 0,
 created_at TEXT, last_withdraw_date TEXT, is_banned INTEGER DEFAULT 0
)""")
conn.commit()

def build_start_message():
    funcs = "\n".join([f"• {f}" for f in CONFIG["FUNCTIONS"][:4]])
    stats = CONFIG["STATS"]
    text = f"""🎉 Welcome to the {CONFIG["COMPANY_NAME"]}!

Your AI trading system is ready.

{funcs}

{CONFIG["DIVIDER"]}

🏢 About Company:
{CONFIG["COMPANY_ABOUT"]}

{CONFIG["DIVIDER"]}

📊 Our Stats:
👥 {stats["USERS"]} | 💰 {stats["ASSETS"]}
🏆 {stats["WIN_RATE"]} | 🔒 {stats["TRANSPARENT"]}

{CONFIG["DIVIDER"]}

{CONFIG["TIERS_TEXT"]}

{CONFIG["DIVIDER"]}

💸 Withdrawal and AI-powered real-time trading group: {GROUP_USERNAME}
📢 Official latest news channel: {CHANNEL_USERNAME}
📊 Customer Support: {SUPPORT_USERNAME}

{CONFIG["FOOTER"]}
"""
    return text

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    username = update.effective_user.username or update.effective_user.first_name or f"user_{uid}"
    # BAN CHECK - Block on /start loading page only, prevent bot load
    try:
        ban_row = conn.execute("SELECT is_banned FROM users WHERE user_id=?", (uid,)).fetchone()
        if ban_row and ban_row[0]==1:
            ban_text = (
                "🚫 ACCOUNT SUSPENDED\n\n"
                "Your account has been suspended for violating Telegram policies and community guidelines.\n\n"
                "❌ Reason: Policy Violation\n"
                "🔒 Bot access revoked on start. Cannot load bot.\n\n"
                f"Support: {CONFIG['SUPPORT_USERNAME']}\n{SUPPORT_LINK}"
            )
            await update.message.reply_text(ban_text)
            return
    except Exception as e:
        print(f"Ban check error: {e}")

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
        conn.execute("INSERT INTO users (user_id, username, referred_by, created_at, last_claim, last_auto_claim, current_tier) VALUES (?,?,?,?,?,?,?)",
                     (uid, username, ref, now, now, now, 7))
        conn.commit()
        if ref:
            try:
                await context.bot.send_message(chat_id=ref, text=f"🎉 New referral! User {uid} ({username}) joined via your link. Earn 7% when they deposit!")
            except: pass

    # 1. First send Banner Image (like in your screenshot)
    try:
        if os.path.exists(BANNER_FILE):
            with open(BANNER_FILE, 'rb') as photo:
                await update.message.reply_photo(
                    photo=photo,
                    caption=CONFIG["BANNER_CAPTION"] + f"\n\n👥 {CONFIG['STATS']['USERS']} | 💰 {CONFIG['STATS']['ASSETS']} | 🏆 {CONFIG['STATS']['WIN_RATE']} | 🔒 {CONFIG['STATS']['TRANSPARENT']}"
                )
        elif BANNER_URL:
            await update.message.reply_photo(photo=BANNER_URL, caption=CONFIG["BANNER_CAPTION"])
    except Exception as e:
        print(f"Banner optional: {e}")

    # 2. Then send Main Welcome with Functions + About + Banner info
    welcome_text = build_start_message()

    keyboard = [
        [InlineKeyboardButton(CONFIG["BUTTONS"]["ENTER_MINI_APP"], web_app=WebAppInfo(url=f"{WEBAPP_URL}?tg_id={uid}&username={username}"))],
        [InlineKeyboardButton(CONFIG["BUTTONS"]["INVITE"], callback_data="invite")],
        [
            InlineKeyboardButton(CONFIG["BUTTONS"]["ABOUT"], callback_data="about"),
            InlineKeyboardButton(CONFIG["BUTTONS"]["FUNCTIONS"], callback_data="functions")
        ],
        [
            InlineKeyboardButton(CONFIG["BUTTONS"]["GROUP"], url=GROUP_LINK),
            InlineKeyboardButton(CONFIG["BUTTONS"]["CHANNEL"], url=CHANNEL_LINK)
        ],
        [
            InlineKeyboardButton(CONFIG["BUTTONS"]["SUPPORT"], url=SUPPORT_LINK),
            InlineKeyboardButton(CONFIG["BUTTONS"]["MENU"], callback_data="menu")
        ]
    ]

    await update.message.reply_text(
        welcome_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        disable_web_page_preview=True
    )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    username = query.from_user.username or query.from_user.first_name or f"user_{uid}"
    await query.answer()

    if query.data == "about":
        about_text = f"""🏢 About {CONFIG["COMPANY_NAME"]}

{CONFIG["COMPANY_ABOUT"]}

📊 Our Performance:
👥 {CONFIG["STATS"]["USERS"]}
💰 {CONFIG["STATS"]["ASSETS"]}
🏆 {CONFIG["STATS"]["WIN_RATE"]}
🔒 {CONFIG["STATS"]["TRANSPARENT"]}

🔐 Security:
• Bank-level security to protect your assets
• Encrypted & 2FA protection
• Your security is our priority

🌍 Mission:
To make AI-powered crypto trading accessible to everyone, no experience needed. Let AI work for you, 24/7.

💬 Join our community:
{CONFIG["GROUP_USERNAME"]} - Trading & Withdrawal Group
{CONFIG["CHANNEL_USERNAME"]} - Latest News
{CONFIG["SUPPORT_USERNAME"]} - Customer Support
"""
        keyboard = [
            [InlineKeyboardButton(CONFIG["BUTTONS"]["ENTER_MINI_APP"], web_app=WebAppInfo(url=f"{WEBAPP_URL}?tg_id={uid}&username={username}"))],
            [InlineKeyboardButton("🔙 Back", callback_data="back_start")]
        ]
        await query.message.reply_text(about_text, reply_markup=InlineKeyboardMarkup(keyboard), disable_web_page_preview=True)

    elif query.data == "functions":
        funcs_text = "\n\n".join([f"{i+1}. {f}" for i, f in enumerate(CONFIG["FUNCTIONS"])])
        functions_text = f"""⚙️ PT-AI Trading Functions

Our AI System Provides:

{funcs_text}

{CONFIG["DIVIDER"]}

{CONFIG["TIERS_TEXT"]}

{CONFIG["DIVIDER"]}

💡 How it Works:
1. Deposit USDT (Min $20)
2. AI analyzes real-time market opportunities
3. AI executes trades automatically
4. Earn daily profit 7.6% to 14.9%
5. Profit auto-credited every 24h to withdrawable wallet
6. Withdraw anytime (Min $10, once per day)

🔒 No trading experience needed! Fully automated.
"""
        keyboard = [
            [InlineKeyboardButton(CONFIG["BUTTONS"]["ENTER_MINI_APP"], web_app=WebAppInfo(url=f"{WEBAPP_URL}?tg_id={uid}&username={username}"))],
            [InlineKeyboardButton("🔙 Back", callback_data="back_start")]
        ]
        await query.message.reply_text(functions_text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "invite":
        ref_link = f"https://t.me/{BOT_USERNAME}?start={uid}"
        invite_text = f"""👥 Your 10-Level Referral Link:

🔗 {ref_link}

💰 Commission:
• Level 1 (Direct): 7%
• Level 2-10: 1% each
• Total: Up to 16%!

📈 How to earn:
1. Share your link
2. Friends deposit & start AI trading
3. You earn instantly to withdrawable wallet
4. Withdraw anytime

🚀 Share now!

Your link: {ref_link}"""
        keyboard = [
            [InlineKeyboardButton("📤 Share Link", url=f"https://t.me/share/url?url={ref_link}&text=Join PT-AI Trading - AI up to 18% daily!")],
            [InlineKeyboardButton(CONFIG["BUTTONS"]["ENTER_MINI_APP"], web_app=WebAppInfo(url=f"{WEBAPP_URL}?tg_id={uid}&username={username}"))],
            [InlineKeyboardButton("🔙 Back", callback_data="back_start")]
        ]
        await query.message.reply_text(invite_text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "menu":
        row = conn.execute("SELECT balance, withdrawable, daily_percent, profit FROM users WHERE user_id=?", (uid,)).fetchone()
        bal = row[0] if row else 0
        wd = row[1] if row else 0
        pct = row[2] if row and len(row)>2 and row[2] else 0
        prof = row[3] if row and len(row)>3 and row[3] else 0
        menu_text = f"""📋 PT-AI Trading Menu

👤 {username} (ID: {uid})
💼 Trading: ${bal:.2f} @ {pct:.1f}%/day
💰 Profit: ${prof:.2f}
💸 Wallet: ${wd:.2f}

Choose action:"""
        keyboard = [
            [InlineKeyboardButton(CONFIG["BUTTONS"]["ENTER_MINI_APP"], web_app=WebAppInfo(url=f"{WEBAPP_URL}?tg_id={uid}&username={username}"))],
            [InlineKeyboardButton(CONFIG["BUTTONS"]["INVITE"], callback_data="invite")],
            [InlineKeyboardButton(CONFIG["BUTTONS"]["ABOUT"], callback_data="about")],
            [InlineKeyboardButton("🔙 Back", callback_data="back_start")]
        ]
        await query.message.reply_text(menu_text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "back_start":
        welcome_text = build_start_message()
        keyboard = [
            [InlineKeyboardButton(CONFIG["BUTTONS"]["ENTER_MINI_APP"], web_app=WebAppInfo(url=f"{WEBAPP_URL}?tg_id={uid}&username={username}"))],
            [InlineKeyboardButton(CONFIG["BUTTONS"]["INVITE"], callback_data="invite")],
            [
                InlineKeyboardButton(CONFIG["BUTTONS"]["ABOUT"], callback_data="about"),
                InlineKeyboardButton(CONFIG["BUTTONS"]["FUNCTIONS"], callback_data="functions")
            ],
            [
                InlineKeyboardButton(CONFIG["BUTTONS"]["GROUP"], url=GROUP_LINK),
                InlineKeyboardButton(CONFIG["BUTTONS"]["CHANNEL"], url=CHANNEL_LINK)
            ],
            [
                InlineKeyboardButton(CONFIG["BUTTONS"]["SUPPORT"], url=SUPPORT_LINK),
                InlineKeyboardButton(CONFIG["BUTTONS"]["MENU"], callback_data="menu")
            ]
        ]
        await query.message.reply_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), disable_web_page_preview=True)

def main():
    print("✅ PT-AI Bot with Banner + About + Functions")
    print(f"🤖 Bot: @{BOT_USERNAME}")
    print(f"🌐 WebApp: {WEBAPP_URL}")
    print(f"📸 Banner: {BANNER_FILE} (put banner.jpg in folder)")
    print(f"🏢 About: {CONFIG['COMPANY_NAME']}")
    print(f"⚙️ Functions: {len(CONFIG['FUNCTIONS'])} features")
    print(f"")
    print(f"To customize, edit CONFIG at top of bot.py")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    print(f"🚀 Bot polling started - Test /start in Telegram!")
    app.run_polling()

if __name__ == "__main__":
    main()
