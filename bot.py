import logging
import os
import urllib.request
import urllib.parse
import json

logger = logging.getLogger("bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://example.com")
FORCE_CHANNEL_LINK = os.getenv("FORCE_CHANNEL_LINK", "").strip()
FORCE_GROUP_LINK = os.getenv("FORCE_GROUP_LINK", "").strip()

_bot_username_cache = None


def _tg_api(token, method, payload=None):
    url = f"https://api.telegram.org/bot{token}/{method}"
    body = json.dumps(payload).encode() if payload else None
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())


def get_bot_username():
    global _bot_username_cache
    if _bot_username_cache:
        return _bot_username_cache
    try:
        data = _tg_api(BOT_TOKEN, "getMe")
        if data.get("ok"):
            _bot_username_cache = data["result"]["username"]
            logger.info(f"Fetched bot username from API: @{_bot_username_cache}")
            return _bot_username_cache
    except Exception as e:
        logger.error(f"Failed to fetch bot username from API: {e}")
    _bot_username_cache = os.getenv("BOT_USERNAME", "").strip().lstrip("@")
    if _bot_username_cache:
        return _bot_username_cache
    _bot_username_cache = "PT_AI_TRADING_TESTINGBOT"
    return _bot_username_cache


def _send_message(token, chat_id, text, reply_markup=None, parse_mode="HTML"):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return _tg_api(token, "sendMessage", payload)


def _edit_message(token, chat_id, message_id, text, reply_markup=None, parse_mode="HTML"):
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": parse_mode}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return _tg_api(token, "editMessageText", payload)


def _answer_callback(token, callback_query_id, text="", show_alert=False):
    return _tg_api(token, "answerCallbackQuery", {
        "callback_query_id": callback_query_id,
        "text": text,
        "show_alert": show_alert,
    })


def _inline_kb(rows):
    return {"inline_keyboard": rows}


def _btn(text, **kwargs):
    return {"text": text, **kwargs}


INVITE_TEXT = (
    "\U0001f4e2 <b>Join Our Community!</b>\n\n"
    "\U0001f449 Tap below to join our channel & group.\n"
    "Get <b>signals, updates & support</b> \u2014 <b>1 tap to join!</b>"
)


def _invite_kb():
    rows = []
    if FORCE_CHANNEL_LINK:
        rows.append([_btn("\U0001f4e2  Join Channel", url=FORCE_CHANNEL_LINK)])
    if FORCE_GROUP_LINK:
        rows.append([_btn("\U0001f465  Join Group", url=FORCE_GROUP_LINK)])
    if rows:
        return _inline_kb(rows)
    return None


def _make_kb():
    return _inline_kb([
        [_btn("\U0001f4b0  Open Trading Dashboard", web_app={"url": WEBAPP_URL})],
        [
            _btn("\U0001f465  Join Group", url="https://t.me/PT_AI_Trading_Group"),
            _btn("\U0001f4e2  Join Channel", url="https://t.me/PT_AI_Trading"),
        ],
        [
            _btn("\U0001f527  Support", url="https://t.me/PT_AI_Support"),
            _btn("\U0001f464  Profile", callback_data="profile"),
        ],
        [
            _btn("\U0001f4b3  Deposit", callback_data="deposit_info"),
            _btn("\U0001f4b5  Withdraw", callback_data="withdraw_info"),
        ],
        [
            _btn("\U0001f3af  Tasks & Earn", callback_data="tasks_info"),
            _btn("\U0001f91d  Refer & Earn", callback_data="referral_info"),
        ],
    ])


WELCOME_TEXT_TEMPLATE = "\u2728 <b>Welcome, {name}!</b>\n\n\U0001f3af <b>PT_AI Trading</b> \u2014 AI-Powered Crypto Trading Platform\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n\U0001f4ca <b>How It Works</b>\n\u2022 Complete <b>tasks</b> \u2192 Earn <b>1+ USDT</b> each\n\u2022 <b>Deposit</b> min <b>$20 USDT</b> \u2192 AI earns <b>7.6% \u2013 14.9%</b> daily\n\u2022 <b>Auto-compound</b> profits for 30 days\n\u2022 <b>Withdraw</b> anytime to your wallet\n\n\U0001f3e6 <b>Supported Networks</b>\nTRC20 \u2022 BEP20 \u2022 ERC20 \u2022 TON \u2022 SOL\n\n\U0001f48e <b>Tier System</b> \u2014 Higher balance = Higher returns\n\U0001f7e2 Starter: 7.6% | \U0001f7e1 Bronze: 8.9% | \U0001f535 Silver: 9.6%\n\U0001f7e3 Platinum: 10.9% | \U0001f48e Gold: 11.8% | \U0001f48e Diamond: 13.6%\n\U0001f451 Platinum+: 14.9%\n\n\u26a0\ufe0f <b>Important</b>\n\u2022 Complete <b>mandatory tasks</b> to unlock withdrawal\n\u2022 Refer friends to earn <b>7% bonus</b> on deposits\n\u2022 Minimum deposit: <b>20 USDT</b>\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\U0001f680 <b>Tap a button below to get started!</b>{ref_line}"


def _ensure_user(user_id, username="", referred_by=None):
    try:
        port = int(os.getenv("PORT", 10000))
        url = f"http://127.0.0.1:{port}/api/me/{user_id}?username={urllib.parse.quote(username or '')}&referred_by={referred_by or ''}"
        req = urllib.request.Request(url, headers={"User-Agent": "bot"})
        with urllib.request.urlopen(req, timeout=5) as r:
            r.read()
    except Exception as e:
        logger.warning(f"ensure_user failed for {user_id}: {e}")


def _fetch_user_data(user_id):
    try:
        port = int(os.getenv("PORT", 10000))
        url = f"http://127.0.0.1:{port}/api/me/{user_id}"
        req = urllib.request.Request(url, headers={"User-Agent": "bot"})
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        logger.warning(f"fetch_user failed for {user_id}: {e}")
        return None


async def handle_start(token, chat_id, user, args):
    user_id = user.get("id", 0)
    username = user.get("username", "")
    first_name = user.get("first_name", "Trader")
    ref = args[0] if args else None

    logger.info(f"/start from user {user_id} (@{username}) ref={ref}")

    _ensure_user(user_id, username, ref)

    ref_line = ""
    if ref:
        ref_line = f"\n\n\U0001f517 <b>Referred by:</b> User #{ref}"

    text = WELCOME_TEXT_TEMPLATE.format(name=first_name, ref_line=ref_line)
    kb = _make_kb()

    try:
        _send_message(token, chat_id, text, reply_markup=kb)
        logger.info(f"Sent /start reply to {chat_id}")
    except Exception as e:
        logger.error(f"Failed to send /start reply to {chat_id}: {e}", exc_info=True)

    invite_kb = _invite_kb()
    if invite_kb:
        try:
            _send_message(token, chat_id, INVITE_TEXT, reply_markup=invite_kb)
            logger.info(f"Sent invite links to {chat_id}")
        except Exception as e:
            logger.error(f"Failed to send invite to {chat_id}: {e}")


async def handle_callback(token, chat_id, message_id, user, cb_data, cb_query_id=""):
    cb_id = user.get("id", 0)

    try:
        if cb_data == "profile":
            user_id = user.get("id", 0)
            me = _fetch_user_data(user_id)
            if me:
                bal = float(me.get("balance", 0) or 0)
                wd = float(me.get("withdrawable", 0) or 0)
                profit = float(me.get("profit", 0) or 0)
                tier = me.get("daily_percent", 0) or 0
                dep = float(me.get("total_deposit", 0) or 0)
                refs = me.get("referral_earnings", 0) or 0
                text = (
                    f"\U0001f464 <b>Your Profile</b>\n\n"
                    f"\U0001f464 <b>ID:</b> {user_id}\n"
                    f"\U0001f4b0 <b>Balance:</b> {bal:.2f} USDT\n"
                    f"\U0001f4b5 <b>Withdrawable:</b> {wd:.2f} USDT\n"
                    f"\U0001f4c8 <b>Profit:</b> {profit:.2f} USDT\n"
                    f"\U0001f3af <b>Daily Rate:</b> {tier}%\n"
                    f"\U0001f4b3 <b>Total Deposited:</b> {dep:.2f} USDT\n"
                    f"\U0001f91d <b>Referral Earnings:</b> {refs:.2f} USDT\n\n"
                    f"\U0001f449 Open dashboard for full details"
                )
            else:
                text = "\u274c Could not load profile. Try again later."
            kb = _inline_kb([[_btn("\U0001f4b0  Open Dashboard", web_app={"url": WEBAPP_URL})]])
            _edit_message(token, chat_id, message_id, text, reply_markup=kb)

        elif cb_data == "deposit_info":
            text = (
                f"\U0001f4b3 <b>Deposit USDT</b>\n\n"
                f"\u2022 Minimum deposit: <b>20 USDT</b>\n"
                f"\u2022 Invoice valid for <b>15 minutes</b>\n"
                f"\u2022 Auto-verified within <b>15 seconds</b>\n\n"
                f"\U0001f3e6 <b>Supported Networks:</b>\n"
                f"\u2022 TRC20 (Tron)\n"
                f"\u2022 BEP20 (BSC)\n"
                f"\u2022 ERC20 (Ethereum)\n"
                f"\u2022 TON\n"
                f"\u2022 SOL (Solana)\n\n"
                f"\u26a0\ufe0f Send <b>exact amount</b> to the address shown.\n"
                f"After deposit, AI contract starts automatically for <b>30 days</b>.\n\n"
                f"\U0001f449 Tap below to create an invoice"
            )
            kb = _inline_kb([
                [_btn("\U0001f4b3  Make Deposit", web_app={"url": WEBAPP_URL})],
                [_btn("\u2b05\ufe0f  Back", callback_data="back_start")],
            ])
            _edit_message(token, chat_id, message_id, text, reply_markup=kb)

        elif cb_data == "withdraw_info":
            text = (
                f"\U0001f4b5 <b>Withdraw USDT</b>\n\n"
                f"\u2022 Minimum withdrawal: <b>10 USDT</b>\n"
                f"\u2022 Processed from <b>Withdrawable</b> balance\n"
                f"\u2022 All 5 networks supported\n\n"
                f"\u26a0\ufe0f <b>Requirements:</b>\n"
                f"\u2022 Complete all <b>mandatory tasks</b> first\n"
                f"\u2022 Must have sufficient <b>withdrawable</b> balance\n\n"
                f"\U0001f449 Tap below to open withdrawal"
            )
            kb = _inline_kb([
                [_btn("\U0001f4b5  Withdraw Now", web_app={"url": WEBAPP_URL})],
                [_btn("\u2b05\ufe0f  Back", callback_data="back_start")],
            ])
            _edit_message(token, chat_id, message_id, text, reply_markup=kb)

        elif cb_data == "tasks_info":
            text = (
                f"\U0001f3af <b>Tasks & Earn USDT</b>\n\n"
                f"\u2705 <b>Join Group Tasks</b>\n"
                f"Join our Telegram groups & channels.\n"
                f"Earn <b>1 USDT</b> per task.\n\n"
                f"\U0001f465 <b>Referral Tasks</b>\n"
                f"Invite friends and earn bonuses.\n"
                f"Up to <b>25 USDT</b> for top recruiters.\n\n"
                f"\u26a0\ufe0f <b>Mandatory tasks block withdrawal</b>\n"
                f"Complete all mandatory tasks to unlock.\n\n"
                f"\U0001f449 Tap below to see all tasks"
            )
            kb = _inline_kb([
                [_btn("\U0001f3af  Open Tasks", web_app={"url": WEBAPP_URL})],
                [_btn("\u2b05\ufe0f  Back", callback_data="back_start")],
            ])
            _edit_message(token, chat_id, message_id, text, reply_markup=kb)

        elif cb_data == "referral_info":
            bot_name = get_bot_username()
            user_id = user.get("id", 0)
            ref_link = f"https://t.me/{bot_name}?start={user_id}"
            text = (
                f"\U0001f91d <b>Refer & Earn</b>\n\n"
                f"\u2022 Earn <b>7%</b> bonus on direct referral deposits\n"
                f"\u2022 Earn <b>1%</b> bonus on level 2\u201310 referrals\n"
                f"\u2022 Complete referral tasks for extra rewards\n\n"
                f"\U0001f517 <b>Your Referral Link:</b>\n"
                f"<code>{ref_link}</code>\n\n"
                f"\U0001f4a1 Share this link with friends to start earning!"
            )
            kb = _inline_kb([
                [_btn("\u2b05\ufe0f  Back", callback_data="back_start")],
            ])
            _edit_message(token, chat_id, message_id, text, reply_markup=kb)

        elif cb_data == "back_start":
            first_name = user.get("first_name", "Trader")
            text = WELCOME_TEXT_TEMPLATE.format(name=first_name, ref_line="")
            kb = _make_kb()
            _edit_message(token, chat_id, message_id, text, reply_markup=kb)

    except Exception as e:
        logger.error(f"Callback error for '{cb_data}': {e}", exc_info=True)

    try:
        _answer_callback(token, cb_query_id)
    except Exception:
        pass
