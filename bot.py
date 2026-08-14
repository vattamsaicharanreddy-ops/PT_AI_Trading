
# ============================================================
# PT-AI TRADING - TELEGRAM START WITH BANNER + ABOUT + FUNCTIONS
# When user clicks /start -> Shows banner + company info + functions
# ============================================================

CONFIG = {
    # --- Banner (Top image like your screenshot) ---
    "BANNER_FILE": "banner.jpg",  # Put banner.jpg in same folder
    "BANNER_URL": "",  # Or set URL: https://your-domain.com/banner.jpg
    "BANNER_CAPTION": (
        "ðŸš€ AI-Powered Trading.\n"
        "Built for Trust.\n\n"
        "Intelligent. Transparent. Secure.\n"
        "Let AI work for you, 24/7."
    ),

    # --- About Company ---
    "COMPANY_NAME": "PT-AI Intelligent Trading System",
    "COMPANY_ABOUT": (
        "ðŸ¤– About PT-AI Trading:\n"
        "PT-AI is an advanced AI-powered automated crypto trading platform. "
        "Our intelligent algorithms analyze real-time market opportunities and execute trades automatically. "
        "No trading experience needed! Secure, reliable, and transparent.\n\n"
        "ðŸ”’ Bank-level security to protect your assets\n"
        "ðŸ§  Advanced AI algorithms for consistent results\n"
        "ðŸ“Š Real-time data and verifiable results\n"
        "ðŸŽ§ Professional team always here for you"
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
        "âš¡ Real-time market opportunity analysis",
        "ðŸ¤– AI-powered automated trade execution",
        "ðŸ“ˆ Daily investment returns of up to 11.2% to 18% â€” the more tokens you have, the higher your returns!",
        "ðŸ’° Earn up to 16% commission from your 10-level referral network!",
        "ðŸ”’ Secure & Reliable - Bank-level security",
        "ðŸ§  AI-Powered Strategies - Advanced algorithms",
        "ðŸ“Š Transparent Performance - Real-time verifiable results",
        "ðŸŽ§ 24/7 Support - Professional team"
    ],

    # --- Tiers Info ---
    "TIERS_TEXT": (
        "ðŸ’Ž Profit Tiers:\n"
        "â€¢ $20+ â†’ 7.6% /day\n"
        "â€¢ $120+ â†’ 8.9% /day\n"
        "â€¢ $500+ â†’ 9.6% /day\n"
        "â€¢ $1200+ â†’ 10.9% /day\n"
        "â€¢ $2500+ â†’ 11.8% /day\n"
        "â€¢ $6000+ â†’ 13.6% /day\n"
        "â€¢ $15000+ â†’ 14.9% /day\n\n"
        "â° AI active 30 days per tier upgrade"
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
        "ENTER_MINI_APP": "ðŸš€ Enter Mini App",
        "INVITE": "ðŸ‘¥ Invite friends",
        "GROUP": "ðŸ’¸ PT-Group",
        "CHANNEL": "ðŸ“¢ PT-Channel",
        "SUPPORT": "ðŸ†˜ Support",
        "ABOUT": "ðŸ¢ About Company",
        "FUNCTIONS": "âš™ï¸ Functions",
        "MENU": "ðŸ“‹ Menu"
    },

    "DIVIDER": "â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”",
    "FOOTER": "ðŸ‘‡ Click the mini app below to open your control panel and start earning money."
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
    print("âŒ Bot token not set!")
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
    funcs = "\n".join([f"â€¢ {f}" for f in CONFIG["FUNCTIONS"][:4]])
    stats = CONFIG["STATS"]
    text = f"""ðŸŽ‰ Welcome to the {CONFIG["COMPANY_NAME"]}!

Your AI trading system is ready.

{funcs}

{CONFIG["DIVIDER"]}

ðŸ¢ About Company:
{CONFIG["COMPANY_ABOUT"]}

{CONFIG["DIVIDER"]}

ðŸ“Š Our Stats:
ðŸ‘¥ {stats["USERS"]} | ðŸ’° {stats["ASSETS"]}
ðŸ† {stats["WIN_RATE"]} | ðŸ”’ {stats["TRANSPARENT"]}

{CONFIG["DIVIDER"]}

{CONFIG["TIERS_TEXT"]}

{CONFIG["DIVIDER"]}

ðŸ’¸ Withdrawal and AI-powered real-time trading group: {GROUP_USERNAME}
ðŸ“¢ Official latest news channel: {CHANNEL_USERNAME}
ðŸ“Š Customer Support: {SUPPORT_USERNAME}

{CONFIG["FOOTER"]}
"""
    return text

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
        conn.execute("INSERT INTO users (user_id, username, referred_by, created_at, last_claim, last_auto_claim, current_tier) VALUES (?,?,?,?,?,?,?)",
                     (uid, username, ref, now, now, now, 7))
        conn.commit()
        if ref:
            try:
                await context.bot.send_message(chat_id=ref, text=f"ðŸŽ‰ New referral! User {uid} ({username}) joined via your link. Earn 7% when they deposit!")
            except: pass

    # 1. First send Banner Image (like in your screenshot)
    try:
        if os.path.exists(BANNER_FILE):
            with open(BANNER_FILE, 'rb') as photo:
                await update.message.reply_photo(
                    photo=photo,
                    caption=CONFIG["BANNER_CAPTION"] + f"\n\nðŸ‘¥ {CONFIG['STATS']['USERS']} | ðŸ’° {CONFIG['STATS']['ASSETS']} | ðŸ† {CONFIG['STATS']['WIN_RATE']} | ðŸ”’ {CONFIG['STATS']['TRANSPARENT']}"
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
        about_text = f"""ðŸ¢ About {CONFIG["COMPANY_NAME"]}

{CONFIG["COMPANY_ABOUT"]}

ðŸ“Š Our Performance:
ðŸ‘¥ {CONFIG["STATS"]["USERS"]}
ðŸ’° {CONFIG["STATS"]["ASSETS"]}
ðŸ† {CONFIG["STATS"]["WIN_RATE"]}
ðŸ”’ {CONFIG["STATS"]["TRANSPARENT"]}

ðŸ” Security:
â€¢ Bank-level security to protect your assets
â€¢ Encrypted & 2FA protection
â€¢ Your security is our priority

ðŸŒ Mission:
To make AI-powered crypto trading accessible to everyone, no experience needed. Let AI work for you, 24/7.

ðŸ’¬ Join our community:
{CONFIG["GROUP_USERNAME"]} - Trading & Withdrawal Group
{CONFIG["CHANNEL_USERNAME"]} - Latest News
{CONFIG["SUPPORT_USERNAME"]} - Customer Support
"""
        keyboard = [
            [InlineKeyboardButton(CONFIG["BUTTONS"]["ENTER_MINI_APP"], web_app=WebAppInfo(url=f"{WEBAPP_URL}?tg_id={uid}&username={username}"))],
            [InlineKeyboardButton("ðŸ”™ Back", callback_data="back_start")]
        ]
        await query.message.reply_text(about_text, reply_markup=InlineKeyboardMarkup(keyboard), disable_web_page_preview=True)

    elif query.data == "functions":
        funcs_text = "\n\n".join([f"{i+1}. {f}" for i, f in enumerate(CONFIG["FUNCTIONS"])])
        functions_text = f"""âš™ï¸ PT-AI Trading Functions

Our AI System Provides:

{funcs_text}

{CONFIG["DIVIDER"]}

{CONFIG["TIERS_TEXT"]}

{CONFIG["DIVIDER"]}

ðŸ’¡ How it Works:
1. Deposit USDT (Min $20)
2. AI analyzes real-time market opportunities
3. AI executes trades automatically
4. Earn daily profit 7.6% to 14.9%
5. Profit auto-credited every 24h to withdrawable wallet
6. Withdraw anytime (Min $10, once per day)

ðŸ”’ No trading experience needed! Fully automated.
"""
        keyboard = [
            [InlineKeyboardButton(CONFIG["BUTTONS"]["ENTER_MINI_APP"], web_app=WebAppInfo(url=f"{WEBAPP_URL}?tg_id={uid}&username={username}"))],
            [InlineKeyboardButton("ðŸ”™ Back", callback_data="back_start")]
        ]
        await query.message.reply_text(functions_text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "invite":
        ref_link = f"https://t.me/{BOT_USERNAME}?start={uid}"
        invite_text = f"""ðŸ‘¥ Your 10-Level Referral Link:

ðŸ”— {ref_link}

ðŸ’° Commission:
â€¢ Level 1 (Direct): 7%
â€¢ Level 2-10: 1% each
â€¢ Total: Up to 16%!

ðŸ“ˆ How to earn:
1. Share your link
2. Friends deposit & start AI trading
3. You earn instantly to withdrawable wallet
4. Withdraw anytime

ðŸš€ Share now!

Your link: {ref_link}"""
        keyboard = [
            [InlineKeyboardButton("ðŸ“¤ Share Link", url=f"https://t.me/share/url?url={ref_link}&text=Join PT-AI Trading - AI up to 18% daily!")],
            [InlineKeyboardButton(CONFIG["BUTTONS"]["ENTER_MINI_APP"], web_app=WebAppInfo(url=f"{WEBAPP_URL}?tg_id={uid}&username={username}"))],
            [InlineKeyboardButton("ðŸ”™ Back", callback_data="back_start")]
        ]
        await query.message.reply_text(invite_text, reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == "menu":
        row = conn.execute("SELECT balance, withdrawable, daily_percent, profit FROM users WHERE user_id=?", (uid,)).fetchone()
        bal = row[0] if row else 0
        wd = row[1] if row else 0
        pct = row[2] if row and len(row)>2 and row[2] else 0
        prof = row[3] if row and len(row)>3 and row[3] else 0
        menu_text = f"""ðŸ“‹ PT-AI Trading Menu

ðŸ‘¤ {username} (ID: {uid})
ðŸ’¼ Trading: ${bal:.2f} @ {pct:.1f}%/day
ðŸ’° Profit: ${prof:.2f}
ðŸ’¸ Wallet: ${wd:.2f}

Choose action:"""
        keyboard = [
            [InlineKeyboardButton(CONFIG["BUTTONS"]["ENTER_MINI_APP"], web_app=WebAppInfo(url=f"{WEBAPP_URL}?tg_id={uid}&username={username}"))],
            [InlineKeyboardButton(CONFIG["BUTTONS"]["INVITE"], callback_data="invite")],
            [InlineKeyboardButton(CONFIG["BUTTONS"]["ABOUT"], callback_data="about")],
            [InlineKeyboardButton("ðŸ”™ Back", callback_data="back_start")]
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
    print("âœ… PT-AI Bot with Banner + About + Functions")
    print(f"ðŸ¤– Bot: @{BOT_USERNAME}")
    print(f"ðŸŒ WebApp: {WEBAPP_URL}")
    print(f"ðŸ“¸ Banner: {BANNER_FILE} (put banner.jpg in folder)")
    print(f"ðŸ¢ About: {CONFIG['COMPANY_NAME']}")
    print(f"âš™ï¸ Functions: {len(CONFIG['FUNCTIONS'])} features")
    print(f"")
    print(f"To customize, edit CONFIG at top of bot.py")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    print(f"ðŸš€ Bot polling started - Test /start in Telegram!")
    app.run_polling()

if __name__ == "__main__":
    main()