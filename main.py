
import os
import asyncio
import threading
import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from server import app as fastapi_app
from bot import BOT_TOKEN, WEBAPP_URL

# Combine both apps
app = fastapi_app

# For Render/Railway, they need to know port
PORT = int(os.getenv("PORT", 8000))

def run_fastapi():
    uvicorn.run(app, host="0.0.0.0", port=PORT)

async def run_bot():
    # Import here to avoid circular
    from telegram.ext import Application, CommandHandler, CallbackQueryHandler
    from bot import start, ref_callback
    
    print(f"✅ Bot starting...")
    print(f"🌐 WebApp URL will be: {os.getenv('WEBAPP_URL', 'https://your-app.onrender.com')}")
    
    application = Application.builder().token(BOT_TOKEN).build()
    from telegram.ext import CommandHandler
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(ref_callback, pattern="ref"))
    
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    print("✅ Telegram bot polling started")
    # Keep running
    await asyncio.Event().wait()

if __name__ == "__main__":
    # Run FastAPI in thread
    fastapi_thread = threading.Thread(target=run_fastapi, daemon=True)
    fastapi_thread.start()
    
    # Run bot in main thread asyncio
    asyncio.run(run_bot())
