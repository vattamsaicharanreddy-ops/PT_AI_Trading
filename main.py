import asyncio
import logging
import os
import threading
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")
logger = logging.getLogger("main")

from database import init_db, USE_POSTGRES

init_db()
logger.info(f"DB: {'POSTGRES' if USE_POSTGRES else 'SQLITE'}")

PORT = int(os.getenv("PORT", 10000))
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://pt-ai-trading.onrender.com")
WEBHOOK_URL = f"{WEBAPP_URL}/webhook/{BOT_TOKEN}"


def run_api():
    import uvicorn
    logger.info(f"Starting API + Webhook on 0.0.0.0:{PORT}")
    logger.info(f"Webhook: {WEBHOOK_URL}")
    uvicorn.run("server:app", host="0.0.0.0", port=PORT, log_level="info", workers=1)


if __name__ == "__main__":
    api_thread = threading.Thread(target=run_api, daemon=True)
    api_thread.start()
    time.sleep(5)

    if not BOT_TOKEN:
        logger.error("BOT_TOKEN missing")
        while True:
            time.sleep(60)

    from telegram import Bot

    async def setup_webhook():
        try:
            bot = Bot(token=BOT_TOKEN)
            await bot.delete_webhook(drop_pending_updates=True)
            logger.info("Old webhook cleared")
            result = await bot.set_webhook(url=WEBHOOK_URL, drop_pending_updates=True, allowed_updates=["message", "callback_query"])
            logger.info(f"Webhook set: {result}")
            me = await bot.get_me()
            logger.info(f"Bot verified: @{me.username} - WEBHOOK MODE")
            await bot.close()
        except Exception as e:
            logger.error(f"Webhook setup error: {e}")

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(setup_webhook())
    except Exception as e:
        logger.error(f"Setup error: {e}")

    logger.info("Webhook mode active - API running")
    while True:
        time.sleep(60)
