
import os, threading, time, asyncio
from dotenv import load_dotenv
load_dotenv()

from database import init_db, USE_POSTGRES
init_db()
print(f"✅ DB: {'POSTGRES' if USE_POSTGRES else 'SQLITE'}")

PORT=int(os.getenv("PORT",10000))
BOT_TOKEN=os.getenv("BOT_TOKEN","")
WEBAPP_URL=os.getenv("WEBAPP_URL","https://pt-ai-trading.onrender.com")
WEBHOOK_SECRET=os.getenv("WEBHOOK_SECRET","")
if not WEBHOOK_SECRET:
    print("⚠️ WEBHOOK_SECRET not set - set a random 32-char string!")

WEBHOOK_URL=f"{WEBAPP_URL}/webhook"

def run_api():
    import uvicorn
    print(f"🌐 Starting API on 0.0.0.0:{PORT}")
    print(f"🔗 Webhook will be at {WEBHOOK_URL}")
    uvicorn.run("server:app", host="0.0.0.0", port=PORT, log_level="info", workers=1)

if __name__=="__main__":
    api_thread = threading.Thread(target=run_api, daemon=True)
    api_thread.start()
    time.sleep(3)
    
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN missing - API only mode")
        while True: time.sleep(60)
    
    from telegram import Bot
    async def setup_webhook():
        try:
            bot = Bot(token=BOT_TOKEN)
            await bot.delete_webhook(drop_pending_updates=True)
            print("✅ Old webhook/polling cleared")
            result = await bot.set_webhook(url=WEBHOOK_URL, drop_pending_updates=True, allowed_updates=["message","callback_query"], secret_token=WEBHOOK_SECRET if WEBHOOK_SECRET else None)
            print(f"✅ Webhook set to {WEBHOOK_URL}: {result}")
            me = await bot.get_me()
            print(f"✅ Bot verified: @{me.username} - WEBHOOK MODE")
            try:
                await bot.close()
            except Exception as e:
                print(f"Close warning (ignore if flood): {e}")
        except Exception as e:
            print(f"❌ Webhook setup error: {e}")
            import traceback; traceback.print_exc()
    
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(setup_webhook())
    except Exception as e:
        print(f"Setup error: {e}")
    
    print("✅ Webhook mode active")
    while True:
        time.sleep(60)
        print("💚 Webhook alive")
