
import os
import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN","")
WEBAPP_URL = os.getenv("WEBAPP_URL","")
BOT_USERNAME = os.getenv("BOT_USERNAME","YourBot")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    ref = args[0] if args and len(args)>0 else None

    # Ensure user exists via API - use httpx async would be better but keep simple
    port = int(os.getenv("PORT",10000))
    # Build safe URL
    try:
        # Call API me with referral
        import urllib.request, urllib.parse
        qs = urllib.parse.urlencode({"username": user.username or "", "referred_by": ref or ""})
        url = f"http://127.0.0.1:{port}/api/me/{user.id}?{qs}"
        req = urllib.request.Request(url, headers={"User-Agent":"bot"})
        with urllib.request.urlopen(req, timeout=5) as r:
            r.read()
    except Exception as e:
        print(f"[bot] ensure_user failed: {e}")

    kb = [
        [InlineKeyboardButton("🚀 Open PT_AI Trading App", web_app={"url": WEBAPP_URL or "https://example.com"})],
        [InlineKeyboardButton("📢 Join Group", url="https://t.me/PT_AI_Trading_Group"), InlineKeyboardButton("💬 Support", url="https://t.me/PT_AI_Support")]
    ]
    text = (
        f"👋 Welcome {user.first_name}!\n\n"
        f"💰 PT_AI Trading - AI Powered Crypto Trading\n"
        f"🎯 Complete Tasks → Earn 1 USDT each\n"
        f"💸 Deposit min $20 → AI earns 7.6%-14.9%/day\n\n"
        f"🔒 Complete mandatory join tasks to unlock withdrawal!\n\n"
        f"👉 Tap below to open the app"
    )
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb))

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
