
import os
BOT_TOKEN=os.getenv("BOT_TOKEN","")
WEBAPP_URL=os.getenv("WEBAPP_URL","")
BOT_USERNAME=os.getenv("BOT_USERNAME","YourBot")
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user=update.effective_user
    args=context.args
    ref=None
    if args and len(args)>0:
        ref=args[0]
    # ensure user in DB via API
    import urllib.request, json
    try:
        port=int(os.getenv("PORT",10000))
        url=f"http://127.0.0.1:{port}/api/me/{user.id}?username={user.username or ''}&referred_by={ref or ''}"
        # we call ensure via server - but simpler call /api/me
        req=urllib.request.Request(f"http://127.0.0.1:{port}/api/me/{user.id}", headers={"User-Agent":"bot"})
        with urllib.request.urlopen(req, timeout=3) as r: r.read()
    except: pass
    kb=[[InlineKeyboardButton("🚀 Open PT_AI Trading App", web_app={"url": WEBAPP_URL or "https://example.com"})],
        [InlineKeyboardButton("📢 Join Group", url="https://t.me/PT_AI_Trading_Group"), InlineKeyboardButton("💬 Support", url="https://t.me/PT_AI_Support")]]
    text=f"👋 Welcome {user.first_name}!\n\n💰 PT_AI Trading - AI Powered Crypto Trading\n🎯 Complete Tasks → Earn 1 USDT each\n💸 Deposit min $20 → AI earns 7.6%-14.9%/day\n\n🔒 Complete mandatory join tasks to unlock withdrawal!"
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb))

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
