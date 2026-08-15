
import os
import threading
import time
import asyncio
from database import init_db, USE_POSTGRES

init_db()

# Start blockchain monitor
try:
    import blockchain_monitor
    print("✅ Blockchain monitor started from main.py")
except Exception as e:
    print(f"⚠️ Monitor import error: {e}")
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

    # Create event loop
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    except: pass

    retry_delay = 10
    while True:
        try:
            from telegram import Bot
            from telegram.ext import Application, CommandHandler, CallbackQueryHandler
            from bot import BOT_TOKEN, WEBAPP_URL, BOT_USERNAME, start, callback_handler
            from telegram.error import Conflict

            print(f"✅ BOT_TOKEN found: {BOT_TOKEN[:10]}...")
            print(f"🌐 WEBAPP_URL: {WEBAPP_URL}")
            print(f"🤖 BOT_USERNAME: @{BOT_USERNAME}")

            async def clear_webhook():
                try:
                    b = Bot(token=BOT_TOKEN)
                    await b.delete_webhook(drop_pending_updates=True)
                    print("✅ Webhook deleted, pending cleared")
                    # Also getMe to test token
                    me = await b.get_me()
                    print(f"✅ Bot verified: @{me.username}")
                    await b.close()
                except Exception as e:
                    print(f"Clear webhook error: {e}")

            try:
                loop.run_until_complete(clear_webhook())
            except Exception as e:
                print(f"Pre-clean error: {e}")

            telegram_app = Application.builder().token(BOT_TOKEN).build()
            telegram_app.add_handler(CommandHandler("start", start))
            telegram_app.add_handler(CallbackQueryHandler(callback_handler))

            print("✅ Telegram bot handlers registered")
            print(f"🚀 Bot starting polling (retry delay {retry_delay}s)...")

            # This blocks until conflict or error
            telegram_app.run_polling(
                drop_pending_updates=True,
                allowed_updates=["message", "callback_query"],
                close_loop=False,
                stop_signals=None
            )

        except Conflict as e:
            print(f"⚠️ Conflict detected: Another bot instance is running. Message: {e}")
            print(f"⏳ Waiting {retry_delay}s before retry... Render may have 2 instances running.")
            print("💡 FIX: In Render Dashboard -> Set 1 instance only (Scaling -> Manual -> 1), or wait for old instance to die.")
            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 300)  # exponential backoff up to 5min
            continue
        except Exception as e:
            err_str = str(e)
            if "Conflict" in err_str or "terminated by other getUpdates" in err_str:
                print(f"⚠️ Conflict in exception: {e}")
                print(f"⏳ Retry in {retry_delay}s...")
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 300)
                continue
            if "Flood control exceeded" in err_str:
                # Parse retry seconds
                import re
                m = re.search(r'Retry in (\d+)', err_str)
                wait = int(m.group(1)) + 5 if m else 320
                print(f"⏳ Flood control: waiting {wait}s")
                time.sleep(wait)
                continue
            print(f"❌ Bot error: {e}")
            import traceback
            traceback.print_exc()
            print(f"⏳ Retry in {retry_delay}s...")
            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 300)
