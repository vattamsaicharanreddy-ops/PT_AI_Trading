import logging
import os
import urllib.request
import urllib.parse
import json

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

logger = logging.getLogger("bot")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://example.com")

_bot_username_cache = None


def get_bot_username():
    global _bot_username_cache
    if _bot_username_cache:
        return _bot_username_cache
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getMe"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
            if data.get("ok"):
                _bot_username_cache = data["result"]["username"]
                logger.info(f"Fetched bot username from API: @{_bot_username_cache}")
                return _bot_username_cache
    except Exception as e:
        logger.error(f"Failed to fetch bot username from API: {e}")
    _bot_username_cache = os.getenv("BOT_USERNAME", "").strip().lstrip("@")
    if _bot_username_cache:
        logger.info(f"Using bot username from env: @{_bot_username_cache}")
        return _bot_username_cache
    _bot_username_cache = "PT_AI_TRADING_TESTINGBOT"
    logger.warning(f"Using hardcoded bot username: @{_bot_username_cache}")
    return _bot_username_cache


WELCOME_TEXT = """\u2728 <b>Welcome, {name}!</b>

\U0001f3af <b>PT_AI Trading</b> \u2014 AI-Powered Crypto Trading Platform
{'━' * 30}

\U0001f4ca <b>How It Works</b>
\u2022 Complete <b>tasks</b> \u2192 Earn <b>1+ USDT</b> each
\u2022 <b>Deposit</b> min <b>$20 USDT</b> \u2192 AI earns <b>7.6% \u2013 14.9%</b> daily
\u2022 <b>Auto-compound</b> profits for 30 days
\u2022 <b>Withdraw</b> anytime to your wallet

\U0001f3e6 <b>Supported Networks</b>
TRC20 \u2022 BEP20 \u2022 ERC20 \u2022 TON \u2022 SOL

\U0001f48e <b>Tier System</b> \u2014 Higher balance = Higher returns
\U0001f7e2 Starter: 7.6% | \U0001f7e1 Bronze: 8.9% | \U0001f535 Silver: 9.6%
\U0001f7e3 Platinum: 10.9% | \U0001f48e Gold: 11.8% | \U0001f48e Diamond: 13.6%
\U0001f451 Platinum+: 14.9%

\u26a0\ufe0f <b>Important</b>
\u2022 Complete <b>mandatory tasks</b> to unlock withdrawal
\u2022 Refer friends to earn <b>7% bonus</b> on deposits
\u2022 Minimum deposit: <b>20 USDT</b>
{'━' * 30}
\U0001f680 <b>Tap a button below to get started!</b>{ref_line}"""


def _make_kb():
    return [
        [InlineKeyboardButton("\U0001f4b0  Open Trading Dashboard", web_app={"url": WEBAPP_URL})],
        [
            InlineKeyboardButton("\U0001f465  Join Group", url="https://t.me/PT_AI_Trading_Group"),
            InlineKeyboardButton("\U0001f4e2  Join Channel", url="https://t.me/PT_AI_Trading"),
        ],
        [
            InlineKeyboardButton("\U0001f527  Support", url="https://t.me/PT_AI_Support"),
            InlineKeyboardButton("\U0001f464  Profile", callback_data="profile"),
        ],
        [
            InlineKeyboardButton("\U0001f4b3  Deposit", callback_data="deposit_info"),
            InlineKeyboardButton("\U0001f4b5  Withdraw", callback_data="withdraw_info"),
        ],
        [
            InlineKeyboardButton("\U0001f3af  Tasks & Earn", callback_data="tasks_info"),
            InlineKeyboardButton("\U0001f91d  Refer & Earn", callback_data="referral_info"),
        ],
    ]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    args = context.args
    ref = args[0] if args and len(args) > 0 else None

    try:
        port = int(os.getenv("PORT", 10000))
        url = f"http://127.0.0.1:{port}/api/me/{user.id}?username={user.username or ''}&referred_by={ref or ''}"
        req = urllib.request.Request(url, headers={"User-Agent": "bot"})
        with urllib.request.urlopen(req, timeout=5) as r:
            r.read()
    except Exception as e:
        logger.warning(f"ensure_user failed for {user.id}: {e}")

    ref_line = ""
    if ref:
        ref_line = f"\n\n\U0001f517 <b>Referred by:</b> User #{ref}"

    text = WELCOME_TEXT.format(name=user.first_name or "Trader", ref_line=ref_line)
    kb = _make_kb()

    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data

    try:
        if data == "profile":
            user_id = query.from_user.id
            try:
                port = int(os.getenv("PORT", 10000))
                url = f"http://127.0.0.1:{port}/api/me/{user_id}"
                req = urllib.request.Request(url, headers={"User-Agent": "bot"})
                with urllib.request.urlopen(req, timeout=5) as r:
                    me = json.loads(r.read().decode())
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
            except Exception:
                text = "\u274c Could not load profile. Try again later."
            kb = [[InlineKeyboardButton("\U0001f4b0  Open Dashboard", web_app={"url": WEBAPP_URL})]]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

        elif data == "deposit_info":
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
            kb = [
                [InlineKeyboardButton("\U0001f4b3  Make Deposit", web_app={"url": WEBAPP_URL})],
                [InlineKeyboardButton("\u2b05\ufe0f  Back", callback_data="back_start")],
            ]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

        elif data == "withdraw_info":
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
            kb = [
                [InlineKeyboardButton("\U0001f4b5  Withdraw Now", web_app={"url": WEBAPP_URL})],
                [InlineKeyboardButton("\u2b05\ufe0f  Back", callback_data="back_start")],
            ]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

        elif data == "tasks_info":
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
            kb = [
                [InlineKeyboardButton("\U0001f3af  Open Tasks", web_app={"url": WEBAPP_URL})],
                [InlineKeyboardButton("\u2b05\ufe0f  Back", callback_data="back_start")],
            ]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

        elif data == "referral_info":
            bot_name = get_bot_username()
            ref_link = f"https://t.me/{bot_name}?start={query.from_user.id}"
            text = (
                f"\U0001f91d <b>Refer & Earn</b>\n\n"
                f"\u2022 Earn <b>7%</b> bonus on direct referral deposits\n"
                f"\u2022 Earn <b>1%</b> bonus on level 2\u201310 referrals\n"
                f"\u2022 Complete referral tasks for extra rewards\n\n"
                f"\U0001f517 <b>Your Referral Link:</b>\n"
                f"<code>{ref_link}</code>\n\n"
                f"\U0001f4a1 Share this link with friends to start earning!"
            )
            share_text = urllib.parse.quote(
                f"Join PT_AI Trading and earn USDT daily!\n\nUse my referral link:\n{ref_link}"
            )
            kb = [
                [InlineKeyboardButton("\U0001f44c  Copy & Share", callback_data="copy_ref")],
                [InlineKeyboardButton("\u2b05\ufe0f  Back", callback_data="back_start")],
            ]
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

        elif data == "back_start":
            ref_line = ""
            text = WELCOME_TEXT.format(name=query.from_user.first_name or "Trader", ref_line=ref_line)
            kb = _make_kb()
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

        elif data == "copy_ref":
            bot_name = get_bot_username()
            ref_link = f"https://t.me/{bot_name}?start={query.from_user.id}"
            await query.answer(text=f"Link ready to paste!", show_alert=True)

    except Exception as e:
        logger.error(f"Callback handler error for '{data}': {e}", exc_info=True)

    await query.answer()
