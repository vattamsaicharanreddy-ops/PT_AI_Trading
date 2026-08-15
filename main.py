
import os, threading, time, asyncio
from database import init_db, USE_POSTGRES
init_db()
print(f"✅ Main starting with DB: {'POSTGRES' if USE_POSTGRES else 'SQLITE - WARNING: ephemeral on Render! Add DATABASE_URL'}")

PORT=int(os.getenv("PORT",10000))

def run_api():
    import uvicorn
    # IMPORTANT: single worker only to avoid duplicate bot instances
    print(f"🌐 Starting API on 0.0.0.0:{PORT} with 1 worker")
    uvicorn.run("server:app", host="0.0.0.0", port=PORT, log_level="info", workers=1)

def keep_alive_ping():
    import urllib.request
    time.sleep(20)
    while True:
        try:
            url=f"http://127.0.0.1:{PORT}/health"
            req=urllib.request.Request(url, headers={"User-Agent":"PT_AI_KeepAlive"})
            with urllib.request.urlopen(req, timeout=5) as r: r.read()
        except: pass
        time.sleep(240)

if __name__=="__main__":
    t=threading.Thread(target=run_api, daemon=True)
    t.start()
    time.sleep(5)
    print("✅ API thread started - waiting for health")

    kp=threading.Thread(target=keep_alive_ping, daemon=True)
    kp.start()

    # Create event loop
    try:
        loop=asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    except: pass

    retry_delay=30  # increased base delay to avoid flood
    consecutive_conflicts=0

    while True:
        try:
            from telegram import Bot
            from telegram.ext import Application, CommandHandler, CallbackQueryHandler
            from bot import BOT_TOKEN, WEBAPP_URL, BOT_USERNAME, start, callback_handler
            from telegram.error import Conflict

            if not BOT_TOKEN:
                print("❌ BOT_TOKEN missing - bot cannot start, but API will run")
                time.sleep(60)
                continue

            print(f"✅ BOT_TOKEN found: {BOT_TOKEN[:10]}...")
            print(f"🌐 WEBAPP_URL: {WEBAPP_URL}")
            print(f"🤖 BOT_USERNAME: @{BOT_USERNAME}")

            async def clear_webhook():
                try:
                    b = Bot(token=BOT_TOKEN)
                    await b.delete_webhook(drop_pending_updates=True)
                    print("✅ Webhook deleted, pending cleared")
                    me = await b.get_me()
                    print(f"✅ Bot verified: @{me.username}")
                    await b.close()
                except Exception as e:
                    print(f"Clear webhook error: {e}")

            try:
                loop.run_until_complete(clear_webhook())
            except Exception as e:
                print(f"Pre-clean error: {e}")

            # Small delay after webhook delete
            time.sleep(5)

            telegram_app = Application.builder().token(BOT_TOKEN).build()
            telegram_app.add_handler(CommandHandler("start", start))
            telegram_app.add_handler(CallbackQueryHandler(callback_handler))

            print("✅ Telegram bot handlers registered")
            print(f"🚀 Bot starting polling (retry delay {retry_delay}s)...")
            print("💡 FIX CONFLICT: On Render Dashboard -> Your Service -> Scaling -> Set Instances to 1 (Manual), and disable auto-deploy overlap if possible")

            # This blocks until conflict or error
            telegram_app.run_polling(
                drop_pending_updates=True,
                allowed_updates=["message", "callback_query"],
                close_loop=False,
                stop_signals=None
            )

        except Conflict as e:
            consecutive_conflicts+=1
            print(f"⚠️ Conflict detected ({consecutive_conflicts} times): Another bot instance is running. Message: {e}")
            print(f"⏳ Waiting {retry_delay}s before retry... Render may have 2 instances running during deploy.")
            print("💡 FIX: In Render Dashboard -> Set 1 instance only (Settings -> Scaling -> Manual -> 1), or wait 2-3 minutes for old instance to die.")
            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 1.5 + 10, 300)
            # After 3 conflicts, force longer wait
            if consecutive_conflicts>3:
                print("⏳ Too many conflicts, waiting 120s for old instance to terminate...")
                time.sleep(120)
                consecutive_conflicts=0
                retry_delay=30
            continue
        except Exception as e:
            err_str = str(e)
            if "Conflict" in err_str or "terminated by other getUpdates" in err_str:
                consecutive_conflicts+=1
                print(f"⚠️ Conflict in exception ({consecutive_conflicts}): {e}")
                print(f"⏳ Retry in {retry_delay}s...")
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 1.5 + 10, 300)
                if consecutive_conflicts>3:
                    time.sleep(120)
                    consecutive_conflicts=0
                    retry_delay=30
                continue
            if "Flood control exceeded" in err_str:
                import re
                m = re.search(r'Retry in (\d+)', err_str)
                wait = int(m.group(1)) + 10 if m else 360
                print(f"⏳ Flood control: waiting {wait}s")
                time.sleep(wait)
                continue
            print(f"❌ Bot error: {e}")
            import traceback
            traceback.print_exc()
            print(f"⏳ Retry in {retry_delay}s...")
            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 1.5 + 10, 300)
            consecutive_conflicts=0
