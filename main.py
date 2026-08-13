import os
import threading
import time

PORT = int(os.getenv("PORT", 10000))

def run_api():
    import uvicorn
    print(f"🌐 Starting API on 0.0.0.0:{PORT}")
    uvicorn.run("server:app", host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    # Start API
    t = threading.Thread(target=run_api, daemon=True)
    t.start()
    time.sleep(2)
    print("✅ API thread started")
    
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
