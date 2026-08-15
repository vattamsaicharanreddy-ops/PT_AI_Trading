
import datetime
import os
from urllib.parse import quote

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.ext import ContextTypes

from database import USE_POSTGRES, get_conn, put_conn, init_db

init_db()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN or "PASTE" in BOT_TOKEN:
    if os.path.exists("bot_token.txt", encoding="utf-8"):
        with open("bot_token.txt", encoding="utf-8") as token_file:
            BOT_TOKEN = token_file.read().strip()

WEBAPP_URL = os.getenv("WEBAPP_URL", os.getenv("RENDER_EXTERNAL_URL", "https://your-app.onrender.com")).rstrip("/")
BOT_USERNAME = os.getenv("BOT_USERNAME", "PT_Minebot").lstrip("@")
GROUP_LINK = os.getenv("GROUP_LINK", "https://t.me/PT_AI_Trading_Group")
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "https://t.me/PT_AI_Trading")
SUPPORT_LINK = os.getenv("SUPPORT_LINK", "https://t.me/PT_AI_Support")

# Banner - try local file first, then URL
BANNER_FILE = os.getenv("BANNER_FILE", "banner.jpg")
BANNER_URL = os.getenv("BANNER_URL", "")  # You can set https://your-domain.com/banner.jpg

CONFIG = {
    "COMPANY_NAME": "PT-AI Intelligent Trading System",
    "TAGLINE": "🚀 AI-Powered Trading. Built for Trust.",
    "BANNER_CAPTION": (
        "🚀 <b>AI-Powered Trading. Built for Trust.</b>\n"
        "Intelligent. Transparent. Secure.\n"
        "Let AI work for you, 24/7.\n\n"
        "💎 50K+ Active Users | $120M+ Managed | 72.6% Win Rate"
    ),
    "ABOUT_FULL": (
        "🏢 <b>About PT-AI Trading</b>\n\n"
        "PT-AI is an advanced <b>AI-powered automated crypto trading platform</b> trusted by 50,000+ users worldwide.\n\n"
        "Our intelligent algorithms analyze real-time market opportunities across Binance, OKX & Bybit and execute trades automatically - <b>No trading experience needed!</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🔒 <b>Bank-Level Security</b>\n"
        "• Military-grade encryption & 2FA\n"
        "• Self-custody wallets - Your keys, your crypto\n"
        "• Cold storage for 95% of funds\n\n"
        "🧠 <b>Advanced AI Algorithms</b>\n"
        "• 72.6% Win Rate verified on blockchain\n"
        "• Machine learning trained on 5 years data\n"
        "• Real-time sentiment & technical analysis\n\n"
        "📊 <b>Transparent Performance</b>\n"
        "• Live trading feed - See every trade\n"
        "• Real-time verifiable results on-chain\n"
        "• No hidden fees - What you see is what you get\n\n"
        "🎧 <b>24/7 Professional Support</b>\n"
        "• Dedicated account managers\n"
        "• <10 min response time\n"
        "• Multilingual support team\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🌍 <b>Our Mission:</b>\n"
        "To make AI-powered crypto trading accessible to everyone. Let AI work for you while you sleep.\n\n"
        "🏆 <b>Achievements:</b>\n"
        "👥 50,000+ Active Traders\n"
        "💰 $120M+ Assets Under Management\n"
        "📈 72.6% Average Win Rate\n"
        "⭐ 4.9/5 Rating (10K+ reviews)\n"
        "🔒 100% Transparent & Audited"
    ),
    "FUNCTIONS_FULL": (
        "⚙️ <b>PT-AI Trading Functions</b>\n\n"
        "Our AI System Provides:\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ <b>1. Real-Time Market Analysis</b>\n"
        "Scans 500+ trading pairs every second across top exchanges. Identifies opportunities with 94% accuracy.\n\n"
        "🤖 <b>2. AI Automated Execution</b>\n"
        "No manual trading! AI enters & exits trades automatically. Long/Short with up to 100x leverage based on risk management.\n\n"
        "📈 <b>3. Daily Returns Up to 14.9%</b>\n"
        "The more you invest, the higher your daily return:\n"
        "• $20+ → 7.6% /day\n"
        "• $120+ → 8.9% /day\n"
        "• $500+ → 9.6% /day\n"
        "• $1200+ → 10.9% /day\n"
        "• $2500+ → 11.8% /day\n"
        "• $6000+ → 13.6% /day\n"
        "• $15000+ → 14.9% /day\n"
        "⏰ AI active 30 days per tier upgrade\n\n"
        "💰 <b>4. 10-Level Referral System - Earn 16%</b>\n"
        "• Level 1 (Direct): 7%\n"
        "• Level 2-10: 1% each\n"
        "• Instant credit to withdrawable wallet\n"
        "• Example: Friend deposits $1000 → You get $70 instantly!\n\n"
        "🔒 <b>5. Secure & Reliable</b>\n"
        "• Self-custody - You own your funds\n"
        "• Instant withdrawals (Min $10, once/day)\n"
        "• Auto-approved for first 6 days\n\n"
        "🧠 <b>6. AI Strategies</b>\n"
        "• Scalping, Arbitrage, Trend Following\n"
        "• Risk management with stop-loss\n"
        "• Portfolio diversification\n\n"
        "📊 <b>7. Transparent Dashboard</b>\n"
        "• Live profit tracking\n"
        "• Real-time trade feed\n"
        "• Deposit/Withdrawal history\n"
        "• Referral earnings tracker\n\n"
        "🎧 <b>8. 24/7 Support</b>\n"
        "• Live chat in Mini App\n"
        "• Telegram support @PT_AI_Support\n"
        "• Community @PT_AI_Trading_Group\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 <b>How it Works:</b>\n"
        "1️⃣ Deposit USDT (Min $20) via TRC20/BEP20/ERC20\n"
        "2️⃣ AI analyzes real-time market opportunities\n"
        "3️⃣ AI executes trades automatically 24/7\n"
        "4️⃣ Earn daily profit 7.6% to 14.9%\n"
        "5️⃣ Profit auto-credited every 24h\n"
        "6️⃣ Withdraw anytime (Min $10)\n\n"
        "🔥 <b>No experience needed! Fully automated.</b>"
    ),
    "STATS": "👥 50K+ Users | 💰 $120M+ Managed | 🏆 72.6% Win Rate | 🔒 100% Transparent",
    "WELCOME": (
        "🎉 <b>Welcome to PT-AI Intelligent Trading System!</b>\n\n"
        "Your AI trading system is ready. 🚀\n\n"
        "⚡ Real-time market opportunity analysis\n"
        "🤖 AI-powered automated trade execution\n"
        "📈 Daily returns up to 14.9% - More tokens = Higher returns!\n"
        "💰 Earn up to 16% from 10-level referrals!\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "💎 <b>Profit Tiers:</b>\n"
        "• $20+ → 7.6% /day\n"
        "• $120+ → 8.9% /day\n"
        "• $500+ → 9.6% /day\n"
        "• $1200+ → 10.9% /day\n"
        "• $2500+ → 11.8% /day\n"
        "• $6000+ → 13.6% /day\n"
        "• $15000+ → 14.9% /day\n\n"
        "⏰ AI active 30 days per upgrade\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "👇 <b>Click the Mini App below to start earning!</b>"
    )
}

def placeholder():
    return "%s" if USE_POSTGRES else "?"

def ensure_user(user_id: int, username: str, referred_by=None):
    conn = get_conn()
    try:
        cur = conn.cursor()
        ph = placeholder()
        cur.execute(f"SELECT user_id FROM users WHERE user_id={ph}", (user_id,))
        if not cur.fetchone():
            referrer = None
            try:
                candidate = int(referred_by) if referred_by else None
                if candidate and candidate != user_id:
                    cur.execute(f"SELECT user_id FROM users WHERE user_id={ph}", (candidate,))
                    referrer = candidate if cur.fetchone() else None
            except:
                pass
            now = datetime.datetime.utcnow().isoformat()
            cur.execute(
                f"INSERT INTO users (user_id,username,referred_by,created_at,last_claim,last_auto_claim,current_tier) "
                f"VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph})",
                (user_id, username, referrer, now, now, now, 7),
            )
            conn.commit()
        cur.close()
    finally:
        put_conn(conn)

def main_keyboard(user_id: int, username: str):
    app_url = f"{WEBAPP_URL}?tg_id={user_id}&username={quote(username)}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Enter Mini App", web_app=WebAppInfo(url=app_url))],
        [InlineKeyboardButton("👥 Invite Friends", callback_data="invite"),
         InlineKeyboardButton("🏢 About Company", callback_data="about")],
        [InlineKeyboardButton("⚙️ Functions", callback_data="functions"),
         InlineKeyboardButton("📋 Menu", callback_data="menu")],
        [InlineKeyboardButton("💸 PT Group", url=GROUP_LINK),
         InlineKeyboardButton("📢 PT Channel", url=CHANNEL_LINK)],
        [InlineKeyboardButton("🆘 Support", url=SUPPORT_LINK)],
    ])

def back_keyboard(user_id: int, username: str):
    app_url = f"{WEBAPP_URL}?tg_id={user_id}&username={quote(username)}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Enter Mini App", web_app=WebAppInfo(url=app_url))],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_start")]
    ])

async def send_banner(update, user_id, username):
    # Try to send banner image if exists
    caption = CONFIG["BANNER_CAPTION"]
    keyboard = main_keyboard(user_id, username)
    
    # Check if banner file exists locally
    if os.path.exists(BANNER_FILE):
        try:
            with open(BANNER_FILE, 'rb') as photo:
                await update.message.reply_photo(
                    photo=photo,
                    caption=caption,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
                return True
        except Exception as e:
            print(f"Banner file send failed: {e}")
    
    # Try banner URL if set
    if BANNER_URL:
        try:
            await update.message.reply_photo(
                photo=BANNER_URL,
                caption=caption,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
            return True
        except Exception as e:
            print(f"Banner URL send failed: {e}")
    
    return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return
    user = update.effective_user
    username = user.username or user.first_name or f"user_{user.id}"
    referred_by = context.args[0] if context.args else None
    ensure_user(user.id, username, referred_by)
    
    # Try banner first
    banner_sent = await send_banner(update, user.id, username)
    
    if not banner_sent:
        # Fallback to text with full welcome
        await update.message.reply_text(
            CONFIG["WELCOME"],
            reply_markup=main_keyboard(user.id, username),
            parse_mode="HTML"
        )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.from_user:
        return
    await query.answer()
    user = query.from_user
    username = user.username or user.first_name or f"user_{user.id}"
    ensure_user(user.id, username)

    if query.data == "invite":
        link = f"https://t.me/{BOT_USERNAME}?start={user.id}"
        text = (
            "👥 <b>Your 10-Level Referral Link</b>\n\n"
            f"🔗 <code>{link}</code>\n\n"
            "💰 <b>Commission Structure:</b>\n"
            "• Level 1 (Direct): <b>7%</b>\n"
            "• Level 2-10: <b>1% each</b>\n"
            "• Total: <b>Up to 16%!</b>\n\n"
            "📈 <b>How to Earn:</b>\n"
            "1️⃣ Share your link\n"
            "2️⃣ Friends deposit & start AI trading\n"
            "3️⃣ You earn instantly to withdrawable wallet\n"
            "4️⃣ Withdraw anytime (Min $10)\n\n"
            "🚀 <b>Example:</b>\n"
            "Friend deposits $1000 → You get $70 instantly!\n"
            "Friend deposits $5000 → You get $350 instantly!\n\n"
            "💸 Share now and start earning!"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 Share Link", url=f"https://t.me/share/url?url={link}&text=Join PT-AI Trading - AI up to 14.9% daily!")],
            [InlineKeyboardButton("🚀 Enter Mini App", web_app=WebAppInfo(url=f"{WEBAPP_URL}?tg_id={user.id}&username={quote(username)}"))],
            [InlineKeyboardButton("🔙 Back", callback_data="back_start")]
        ])
        await query.message.reply_text(text, reply_markup=kb, parse_mode="HTML")

    elif query.data == "about":
        # ATTRACTIVE ABOUT WITH FULL INFO
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 Start Trading Now", web_app=WebAppInfo(url=f"{WEBAPP_URL}?tg_id={user.id}&username={quote(username)}"))],
            [InlineKeyboardButton("💸 Join PT Group", url=GROUP_LINK),
             InlineKeyboardButton("📢 PT Channel", url=CHANNEL_LINK)],
            [InlineKeyboardButton("🔙 Back", callback_data="back_start")]
        ])
        # Try to send with banner if available
        if os.path.exists(BANNER_FILE):
            try:
                with open(BANNER_FILE, 'rb') as photo:
                    await query.message.reply_photo(
                        photo=photo,
                        caption=CONFIG["ABOUT_FULL"],
                        reply_markup=kb,
                        parse_mode="HTML"
                    )
                    return
            except: pass
        
        await query.message.reply_text(CONFIG["ABOUT_FULL"], reply_markup=kb, parse_mode="HTML")

    elif query.data == "functions":
        # ATTRACTIVE FUNCTIONS WITH FULL INFO
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 Enter Mini App & Start Earning", web_app=WebAppInfo(url=f"{WEBAPP_URL}?tg_id={user.id}&username={quote(username)}"))],
            [InlineKeyboardButton("👥 Get Referral Link", callback_data="invite")],
            [InlineKeyboardButton("🔙 Back", callback_data="back_start")]
        ])
        if os.path.exists(BANNER_FILE):
            try:
                with open(BANNER_FILE, 'rb') as photo:
                    await query.message.reply_photo(
                        photo=photo,
                        caption=CONFIG["FUNCTIONS_FULL"],
                        reply_markup=kb,
                        parse_mode="HTML"
                    )
                    return
            except: pass
            
        await query.message.reply_text(CONFIG["FUNCTIONS_FULL"], reply_markup=kb, parse_mode="HTML")

    elif query.data == "menu":
        conn = get_conn()
        try:
            cur = conn.cursor()
            ph = placeholder()
            cur.execute(f"SELECT balance,withdrawable,profit,daily_percent FROM users WHERE user_id={ph}", (user.id,))
            row = cur.fetchone()
            cur.close()
        finally:
            put_conn(conn)
        if isinstance(row, dict):
            balance = row.get("balance", 0)
            wallet = row.get("withdrawable", 0)
            profit = row.get("profit", 0)
            pct = row.get("daily_percent", 7.6)
        else:
            balance, wallet, profit = (row[0], row[1], row[2]) if row and len(row)>=3 else (0,0,0)
            pct = row[3] if row and len(row)>3 else 7.6
        
        menu_text = (
            f"📋 <b>PT-AI Trading Menu</b>\n\n"
            f"👤 {username} (ID: <code>{user.id}</code>)\n"
            f"💼 Trading: <b>${float(balance or 0):.2f}</b> @ {float(pct or 0):.1f}%/day\n"
            f"💰 Profit: <b>${float(profit or 0):.2f}</b>\n"
            f"💸 Wallet: <b>${float(wallet or 0):.2f}</b>\n\n"
            f"{CONFIG['STATS']}\n\n"
            f"Choose action:"
        )
        await query.message.reply_text(menu_text, reply_markup=main_keyboard(user.id, username), parse_mode="HTML")

    elif query.data == "back_start":
        # Send welcome again with banner
        banner_sent = False
        if os.path.exists(BANNER_FILE):
            try:
                with open(BANNER_FILE, 'rb') as photo:
                    await query.message.reply_photo(
                        photo=photo,
                        caption=CONFIG["WELCOME"],
                        reply_markup=main_keyboard(user.id, username),
                        parse_mode="HTML"
                    )
                    banner_sent = True
            except: pass
        
        if not banner_sent:
            await query.message.reply_text(
                CONFIG["WELCOME"],
                reply_markup=main_keyboard(user.id, username),
                parse_mode="HTML"
            )
