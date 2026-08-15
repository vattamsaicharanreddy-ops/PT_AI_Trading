
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

if __name__ == "__main__":
    t = threading.Thread(target=run_api, daemon=True)
    t.start()
    time.sleep(3)
    print("✅ API thread started")

    kp = threading.Thread(target=keep_alive_ping, daemon=True)
    kp.start()
    print("✅ Keep-alive ping started")

    # FIX: Create new event loop for main thread (fixes RuntimeError)
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    except: pass

    try:
        from telegram import Bot
        from telegram.ext import Application, CommandHandler, CallbackQueryHandler
        from bot import BOT_TOKEN, WEBAPP_URL, BOT_USERNAME, start, callback_handler

        print(f"✅ BOT_TOKEN found: {BOT_TOKEN[:10]}...")
        print(f"🌐 WEBAPP_URL: {WEBAPP_URL}")
        print(f"🤖 BOT_USERNAME: @{BOT_USERNAME}")

        # Clear webhook synchronously using new loop
        async def clear_conflict():
            try:
                b = Bot(token=BOT_TOKEN)
                await b.delete_webhook(drop_pending_updates=True)
                print("✅ Webhook deleted")
                await b.close()
            except Exception as e:
                print(f"Clear webhook: {e}")

        try:
            loop.run_until_complete(clear_conflict())
        except Exception as e:
            print(f"Pre-clean error: {e}")

        telegram_app = Application.builder().token(BOT_TOKEN).build()
        telegram_app.add_handler(CommandHandler("start", start))
        telegram_app.add_handler(CallbackQueryHandler(callback_handler))

        print("✅ Telegram bot handlers registered")
        print("🚀 Bot starting polling with drop_pending_updates=True...")

        # This now works because we have event loop
        telegram_app.run_polling(
            drop_pending_updates=True,
            allowed_updates=["message", "callback_query"],
            close_loop=False
        )

    except Exception as e:
        print(f"❌ Bot error: {e}")
        import traceback
        traceback.print_exc()
        while True:
            time.sleep(60)
