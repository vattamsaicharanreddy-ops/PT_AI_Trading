import asyncio
import logging
import os
import threading
import time
from datetime import datetime, timedelta

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


NUDGE_TEXT = (
    "\U0001f525 <b>Your PT_AI account is ready!</b>\n\n"
    "\U0001f4b0 Just add your <b>first deposit</b> and the AI starts earning for you 24/7.\n"
    "\U0001f381 First deposit bonus: extra <b>+10%</b> free (max $10)\n"
    "\U0001f4b5 Start from just <b>$5 USDT</b> \u2192 earn <b>7.6% \u2013 14.9%</b> daily\n\n"
    "\U0001f449 Tap <b>Deposit</b> in the app: " + os.getenv("WEBAPP_URL", "https://pt-ai-trading.onrender.com") + "\n\n"
    "Don't let your bonus expire. \U0001f4aa"
)


def auto_nudge_loop():
    from database import get_conn, get_cursor, put_conn, USE_POSTGRES
    from bot import _send_message

    interval_h = max(int(os.getenv("NUDGE_INTERVAL_HOURS", "24")), 6)
    cool_min = max(int(os.getenv("NUDGE_COOLDOWN_MIN", "1440")), 60)
    enable = os.getenv("ENABLE_AUTO_NUDGE", "1") == "1"
    batch = max(int(os.getenv("NUDGE_BATCH", "50")), 1)
    logger.info(f"Auto-nudge Drip started: every {interval_h}h, cooldown {cool_min}m, batch {batch}, enabled={enable}")
    while True:
        time.sleep(interval_h * 3600)
        if not enable:
            continue
        try:
            conn = get_conn()
            cur = get_cursor(conn)
            since = (datetime.utcnow() - timedelta(minutes=cool_min)).isoformat()
            if USE_POSTGRES:
                cur.execute(
                    "SELECT user_id FROM users WHERE COALESCE(is_banned,0)=0 "
                    "AND COALESCE(total_deposit,0)<=0 "
                    "AND (last_nudge_at IS NULL OR last_nudge_at='' OR last_nudge_at < %s) "
                    "ORDER BY created_at DESC LIMIT %s",
                    (since, batch),
                )
            else:
                cur.execute(
                    "SELECT user_id FROM users WHERE COALESCE(is_banned,0)=0 "
                    "AND COALESCE(total_deposit,0)<=0 "
                    "AND (last_nudge_at IS NULL OR last_nudge_at='' OR last_nudge_at < ?) "
                    "ORDER BY created_at DESC LIMIT ?",
                    (since, batch),
                )
            rows = cur.fetchall()
            now = datetime.utcnow().isoformat()
            for r in rows:
                uid = r["user_id"] if isinstance(r, dict) else r[0]
                try:
                    _send_message(BOT_TOKEN, uid, NUDGE_TEXT)
                    if USE_POSTGRES:
                        cur.execute("UPDATE users SET last_nudge_at=%s WHERE user_id=%s", (now, uid))
                    else:
                        cur.execute("UPDATE users SET last_nudge_at=? WHERE user_id=?", (now, uid))
                    logger.info(f"Auto-nudge sent to {uid}")
                except Exception as e:
                    logger.warning(f"Auto-nudge failed for {uid}: {e}")
            conn.commit()
            put_conn(conn)
        except Exception as e:
            logger.error(f"Auto-nudge loop error: {e}")




if __name__ == "__main__":
    api_thread = threading.Thread(target=run_api, daemon=True)
    api_thread.start()
    nudge_thread = threading.Thread(target=auto_nudge_loop, daemon=True)
    nudge_thread.start()
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
