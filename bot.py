import datetime
import os
from urllib.parse import quote

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.ext import ContextTypes

from database import USE_POSTGRES, get_conn, put_conn, init_db

init_db()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN or "PASTE" in BOT_TOKEN:
    if os.path.exists("bot_token.txt"):
        with open("bot_token.txt", encoding="utf-8") as token_file:
            BOT_TOKEN = token_file.read().strip()

WEBAPP_URL = os.getenv("WEBAPP_URL", os.getenv("RENDER_EXTERNAL_URL", "https://your-app.onrender.com")).rstrip("/")
BOT_USERNAME = os.getenv("BOT_USERNAME", "YourBot").lstrip("@")
GROUP_LINK = os.getenv("GROUP_LINK", "https://t.me/PT_AI_Trading_Group")
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "https://t.me/PT_AI_Trading")
SUPPORT_LINK = os.getenv("SUPPORT_LINK", "https://t.me/PT_AI_Support")

COMPANY_DESCRIPTION = (
    "PT-AI Intelligent Trading System\n\n"
    "Use the Mini App to view your trading dashboard, deposits, withdrawals, "
    "referrals, and account history."
)


def placeholder():
    return "%s" if USE_POSTGRES else "?"


def ensure_user(user_id: int, username: str, referred_by=None):
    """Create the Telegram user once while preserving a valid first referrer."""
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
            except (TypeError, ValueError):
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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or not update.message:
        return
    user = update.effective_user
    username = user.username or user.first_name or f"user_{user.id}"
    referred_by = context.args[0] if context.args else None
    ensure_user(user.id, username, referred_by)
    await update.message.reply_text(
        f"🎉 Welcome to PT-AI Intelligent Trading System, {username}!\n\n{COMPANY_DESCRIPTION}\n\n"
        "Choose an option below to get started.",
        reply_markup=main_keyboard(user.id, username),
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
        await query.message.reply_text(
            "👥 Invite Friends\n\n"
            "Share your personal link. When a friend joins and deposits, your referral reward is added to your wallet.\n\n"
            f"Your referral link:\n{link}"
        )
    elif query.data == "about":
        await query.message.reply_text(
            "🏢 About PT-AI Trading\n\n"
            "PT-AI provides a dashboard for trading activity, account balances, deposits, withdrawals, and referral rewards. "
            "Open the Mini App to manage your account."
        )
    elif query.data == "functions":
        await query.message.reply_text(
            "⚙️ Available Functions\n\n"
            "• Trading dashboard\n• Deposit invoices\n• Withdrawal requests\n• Referral link and earnings\n• Deposit and withdrawal history\n\n"
            "Tap ‘Enter Mini App’ to use these functions."
        )
    elif query.data == "menu":
        conn = get_conn()
        try:
            cur = conn.cursor()
            ph = placeholder()
            cur.execute(f"SELECT balance,withdrawable,profit FROM users WHERE user_id={ph}", (user.id,))
            row = cur.fetchone()
            cur.close()
        finally:
            put_conn(conn)
        if isinstance(row, dict):
            balance, wallet, profit = row.get("balance", 0), row.get("withdrawable", 0), row.get("profit", 0)
        else:
            balance, wallet, profit = row or (0, 0, 0)
        await query.message.reply_text(
            f"📋 Account Menu\n\nTrading balance: {float(balance or 0):.2f} USDT\n"
            f"Wallet: {float(wallet or 0):.2f} USDT\nUnclaimed profit: {float(profit or 0):.2f} USDT",
            reply_markup=main_keyboard(user.id, username),
        )
