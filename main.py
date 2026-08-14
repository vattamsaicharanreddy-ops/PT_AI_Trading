import os
import threading
import time

PORT = int(os.getenv("PORT", 10000))


def run_api():
    import uvicorn

    print(f"🌐 Starting API on 0.0.0.0:{PORT}")

    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=PORT
    )


def keep_alive_ping():

    # Keep Render service warm
    import urllib.request

    time.sleep(30)

    while True:

        try:

            url = (
                f"http://127.0.0.1:{PORT}/health"
            )

            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent":
                        "PT_AI_KeepAlive"
                }
            )

            with urllib.request.urlopen(
                req,
                timeout=5
            ) as r:

                r.read()

        except Exception:
            pass

        time.sleep(240)


if __name__ == "__main__":

    # ========================================================
    # START API
    # ========================================================

    t = threading.Thread(
        target=run_api,
        daemon=True
    )

    t.start()

    time.sleep(2)

    print(
        "✅ API thread started"
    )

    # ========================================================
    # KEEP ALIVE
    # ========================================================

    kp = threading.Thread(
        target=keep_alive_ping,
        daemon=True
    )

    kp.start()

    print(
        "✅ Keep-alive ping started"
    )

    # ========================================================
    # START TELEGRAM BOT
    # ========================================================

    try:

        from telegram.ext import (
            Application,
            CommandHandler,
            CallbackQueryHandler
        )

        # IMPORTANT:
        # bot.py contains callback_handler,
        # NOT ref_callback.

        from bot import (
            BOT_TOKEN,
            WEBAPP_URL,
            BOT_USERNAME,
            start,
            callback_handler
        )

        print(
            f"✅ BOT_TOKEN found: "
            f"{BOT_TOKEN[:10]}..."
        )

        print(
            f"🌐 WEBAPP_URL: "
            f"{WEBAPP_URL}"
        )

        print(
            f"🤖 BOT_USERNAME: "
            f"@{BOT_USERNAME}"
        )

        # ====================================================
        # TELEGRAM APPLICATION
        # ====================================================

        telegram_app = (
            Application
            .builder()
            .token(BOT_TOKEN)
            .build()
        )

        # /start
        telegram_app.add_handler(
            CommandHandler(
                "start",
                start
            )
        )

        # All inline buttons
        telegram_app.add_handler(
            CallbackQueryHandler(
                callback_handler
            )
        )

        print(
            "✅ Telegram bot handlers registered"
        )

        print(
            "🚀 Bot starting polling..."
        )

        telegram_app.run_polling()

    except Exception as e:

        print(
            f"❌ Bot error: {e}"
        )

        import traceback

        traceback.print_exc()

        # Keep API alive even if bot fails
        while True:

            time.sleep(60)