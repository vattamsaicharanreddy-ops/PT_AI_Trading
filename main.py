
import os
import threading
import time
import asyncio
from database import init_db, USE_POSTGRES

init_db()
print(f"✅ Main starting with DB: {'POSTGRES - PERSISTENT' if USE_POSTGRES else 'SQLITE'}")

PORT = int(os.getenv("PORT", 10000))

def run_api():
    import uvicorn
    print(f"🌐 Starting API on 0.0.0.0:{PORT}")
    # FIXED: Add log level and prevent reload
    uvicorn.run("server:app", host="0.0.0.0", port=PORT, log_level="info")

def keep_alive_ping():
    import urllib.request
    time.sleep(30)
    while True:
        try:
            url = f"http://127.0.0.1:{PORT}/health"
            req = urllib.request.Request(url, headers={"User-Agent": "PT_AI_KeepAlive"})
            with urllib.request.urlopen(req, timeout=5) as r:
                r.read()
        except: pass
        time.sleep(240)

async def delete_webhook_and_start():
    from telegram import Bot
    from bot import BOT_TOKEN
    bot = Bot(token=BOT_TOKEN)
    try:
        # Delete any webhook that might be causing conflict
        await bot.delete_webhook(drop_pending_updates=True)
        print("✅ Webhook deleted, pending updates dropped")
    except Exception as e:
        print(f"Webhook delete: {e}")
    try:
        # Delete any existing getUpdates session
        await bot.log_out()
        print("✅ Previous sessions logged out")
    except: pass
    try:
        await bot.close()
    except: pass

if __name__ == "__main__":
    # First, clear any existing webhook/conflict
    try:
        asyncio.run(delete_webhook_and_start())
    except Exception as e:
        print(f"Pre-cleanup: {e}")

    t = threading.Thread(target=run_api, daemon=True)
    t.start()
    time.sleep(3)
    print("✅ API thread started")

    kp = threading.Thread(target=keep_alive_ping, daemon=True)
    kp.start()
    print("✅ Keep-alive ping started")

    try:
        from telegram.ext import Application, CommandHandler, CallbackQueryHandler
        from bot import BOT_TOKEN, WEBAPP_URL, BOT_USERNAME, start, callback_handler

        print(f"✅ BOT_TOKEN found: {BOT_TOKEN[:10]}...")
        print(f"🌐 WEBAPP_URL: {WEBAPP_URL}")
        print(f"🤖 BOT_USERNAME: @{BOT_USERNAME}")

        # FIXED: Add conflict prevention
        telegram_app = (
            Application.builder()
            .token(BOT_TOKEN)
            .build()
        )

        telegram_app.add_handler(CommandHandler("start", start))
        telegram_app.add_handler(CallbackQueryHandler(callback_handler))

        print("✅ Telegram bot handlers registered")
        print("🚀 Bot starting polling with drop_pending_updates=True...")

        # FIXED: drop_pending_updates and stop_signals to prevent conflict
        telegram_app.run_polling(
            drop_pending_updates=True,
            allowed_updates=["message", "callback_query"],
            close_loop=False,
            stop_signals=None
        )

    except Exception as e:
        print(f"❌ Bot error: {e}")
        import traceback
        traceback.print_exc()
        while True:
            time.sleep(60)
