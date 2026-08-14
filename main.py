import os
import threading
import time

PORT = int(os.getenv("PORT", 10000))

def run_api():
    import uvicorn
    print(f"🌐 Starting API on 0.0.0.0:{PORT}")
    uvicorn.run("server:app", host="0.0.0.0", port=PORT)

def keep_alive_ping():
    # FIXED BUG 2: Prevent Render free tier sleep which shows 'Application Loading' page
    # Pings own /health every 4 minutes to stay warm
    import urllib.request
    time.sleep(30)  # wait for server to start
    while True:
        try:
            url = f"http://127.0.0.1:{PORT}/health"
            req = urllib.request.Request(url, headers={'User-Agent':'PT_AI_KeepAlive'})
            with urllib.request.urlopen(req, timeout=5) as r:
                r.read()
            # print("keep-alive ping ok")
        except Exception as e:
            # print(f"keep-alive ping failed: {e}")
            pass
        time.sleep(240)  # 4 min

if __name__ == "__main__":
    # Start API
    t = threading.Thread(target=run_api, daemon=True)
    t.start()
    time.sleep(2)
    print("✅ API thread started")
    
    # Start keep-alive thread to fix Render loading page issue
    kp = threading.Thread(target=keep_alive_ping, daemon=True)
    kp.start()
    print("✅ Keep-alive ping started (fixes Render loading screen)")
    
    # Start bot using simple polling (no Updater direct usage)
    try:
        from telegram.ext import Application, CommandHandler, CallbackQueryHandler
        from bot import BOT_TOKEN, WEBAPP_URL, BOT_USERNAME, start, ref_callback
        
        print(f"✅ BOT_TOKEN found: {BOT_TOKEN[:10]}...")
        print(f"🌐 WEBAPP_URL: {WEBAPP_URL}")
        
        # Use Application.run_polling which is the modern way (no Updater bug)
        app = Application.builder().token(BOT_TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CallbackQueryHandler(ref_callback, pattern="ref"))
        
        print("✅ Bot starting polling...")
        app.run_polling()
    except Exception as e:
        print(f"❌ Bot error: {e}")
        import traceback
        traceback.print_exc()
        # Keep API alive even if bot fails
        while True:
            time.sleep(60)
