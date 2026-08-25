import hashlib
import json
import logging
import os
import random
import string
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta
from functools import wraps

from fastapi import FastAPI, Query, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from typing import Optional, List

from database import USE_POSTGRES, get_conn, get_cursor, init_db, put_conn, safe_close, ph

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")
logger = logging.getLogger("server")

app = FastAPI(title="PT_AI Trading ULTRA V5")

UPLOAD_DIR = "/data/uploads" if os.path.isdir("/data") else os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

from fastapi.staticfiles import StaticFiles
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error on {request.method} {request.url}: {exc}", exc_info=True)
    return JSONResponse(status_code=500, content={"ok": False, "error": "Internal server error: " + str(exc)[:200]})


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"ok": False, "error": exc.detail})


app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Admin-Token"],
)
init_db()


def _seed_referral_tasks():
    conn = get_conn()
    try:
        cur = cursor(conn)
        try:
            cur.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS task_type TEXT DEFAULT 'join'")
            cur.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS task_config TEXT DEFAULT ''")
            cur.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS sort_order INTEGER DEFAULT 0")
            conn.commit()
        except Exception:
            pass
        cur.execute(f"SELECT COUNT(*) as cnt FROM tasks WHERE task_type='referral'")
        cnt = val(cur.fetchone(), "cnt", 0) or 0
        if cnt >= 4:
            return
        now = datetime.utcnow().isoformat()
        seed_tasks = [
            ("Refer 1 Friend", "Invite 1 friend to join any task group", 0.5, '{"ref_count":1}', 100),
            ("Refer 3 Friends", "Invite 3 friends to join any task groups", 1.5, '{"ref_count":3}', 101),
            ("Refer 5 Friends", "Invite 5 friends to join any task groups", 3.0, '{"ref_count":5}', 102),
            ("Super Recruiter", "Refer 5 friends who each deposit \u226520 USDT", 25.0, '{"ref_count":5,"min_deposit":20}', 103),
        ]
        for title, desc, reward, config, sort_o in seed_tasks:
            cur.execute(f"SELECT id FROM tasks WHERE title={ph()} LIMIT 1", (title,))
            if cur.fetchone():
                continue
            cur.execute(
                f"INSERT INTO tasks (title,description,group_link,group_id,group_username,reward,reward_type,is_active,is_mandatory,icon,task_type,task_config,sort_order,created_at) VALUES ({ph()},{ph()},'','','',{ph()},'withdrawable',1,0,'','referral',{ph()},{ph()},{ph()})",
                (title, desc, reward, config, sort_o, now),
            )
        conn.commit()
        logger.info("Seeded referral tasks (checked/inserted)")
    except Exception as e:
        logger.error(f"Seed referral tasks error: {e}")
    finally:
        safe_close(conn)


def _seed_join_tasks():
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute(f"SELECT COUNT(*) as cnt FROM tasks WHERE task_type='join'")
        cnt = val(cur.fetchone(), "cnt", 0) or 0
        if cnt >= 3:
            return
        now = datetime.utcnow().isoformat()
        seed_tasks = [
            ("Join Main Trading Group", "Join PT_AI Trading Group and earn reward", "https://t.me/PT_AI_Trading_Group", "@PT_AI_Trading_Group", "PT_AI_Trading_Group", 1.0, 1, 1),
            ("Join Trading Channel", "Join official channel for signals and updates", "https://t.me/PT_AI_Trading", "@PT_AI_Trading", "PT_AI_Trading", 1.0, 1, 2),
            ("Join Support Group", "Join support group and earn bonus reward", "https://t.me/PT_AI_Support", "@PT_AI_Support", "PT_AI_Support", 1.0, 1, 3),
        ]
        for title, desc, link, gid, username, reward, mandatory, sort_o in seed_tasks:
            cur.execute(f"SELECT id FROM tasks WHERE title={ph()} LIMIT 1", (title,))
            if cur.fetchone():
                continue
            cur.execute(
                f"INSERT INTO tasks (title,description,group_link,group_id,group_username,reward,reward_type,is_active,is_mandatory,icon,task_type,task_config,sort_order,created_at) VALUES ({ph()},{ph()},{ph()},{ph()},{ph()},{ph()},'withdrawable',1,{ph()},'','join',{ph()},{ph()},{ph()})",
                (title, desc, link, gid, username, reward, mandatory, '', sort_o, now),
            )
        conn.commit()
        logger.info("Seeded join tasks (checked/inserted)")
    except Exception as e:
        logger.error(f"Seed join tasks error: {e}")
    finally:
        safe_close(conn)


DEPOSIT_ADDR = {
    "TRC20": os.getenv("ADDR_TRC20", "TAFHf1pxsXRCSnhn8jRU5UcU4STK6u9tAC"),
    "BEP20": os.getenv("ADDR_BEP20", "0xDD190484827BB976acEB975C94d5c58fc8c87Cfd"),
    "ERC20": os.getenv("ADDR_ERC20", "0xDD190484827BB976acEB975C94d5c58fc8c87Cfd"),
    "TON": os.getenv("ADDR_TON", "UQBlNeJ90El3LxBhikC2HUG3mqS16k1q177AjcNAaURVa_zw"),
    "SOL": os.getenv("ADDR_SOL", "87fwXKMuH8wyayeMJ74eRUq3knQ3UXmFQPj9g87A4se7"),
}
TIERS = [(15000, 14.9), (6000, 13.6), (2500, 11.8), (1200, 10.9), (500, 9.6), (120, 8.9), (20, 7.6), (0, 0.0)]
REF_BONUS = {1: 7, **{level: 1 for level in range(2, 11)}}
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "LTCUSDT", "ADAUSDT", "PEPEUSDT", "SHIBUSDT", "MATICUSDT", "DOTUSDT", "ARBUSDT"]
BASE_PRICES = {"BTCUSDT": 67200, "ETHUSDT": 3400, "SOLUSDT": 178, "BNBUSDT": 610, "XRPUSDT": .62, "DOGEUSDT": .16, "AVAXUSDT": 42, "LINKUSDT": 18.5, "LTCUSDT": 84, "ADAUSDT": .48, "PEPEUSDT": .000009, "SHIBUSDT": .000027, "MATICUSDT": .89, "DOTUSDT": 7.2, "ARBUSDT": 1.12}

ADMIN_SECRET = os.getenv("ADMIN_SECRET", os.getenv("ADMIN_PASSWORD", ""))
rate_limit_store = defaultdict(list)
RATE_LIMIT_WINDOW = 60
RATE_LIMIT_MAX = 60


def check_rate_limit(ip: str, limit: int = RATE_LIMIT_MAX):
    now = time.time()
    rate_limit_store[ip] = [t for t in rate_limit_store[ip] if now - t < RATE_LIMIT_WINDOW]
    if len(rate_limit_store[ip]) >= limit:
        return False
    rate_limit_store[ip].append(now)
    return True


def require_admin(request: Request):
    if not ADMIN_SECRET:
        return
    auth = request.headers.get("X-Admin-Token", "")
    if auth != ADMIN_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")


class InvoiceRequest(BaseModel):
    amount: float = Field(gt=0)
    network: str


class WithdrawalRequest(BaseModel):
    amount: float = Field(gt=0)
    address: str = Field(min_length=10)
    network: str


class AdminAction(BaseModel):
    user_id: int
    action: str
    amount: float = 0
    note: Optional[str] = None
    field: Optional[str] = None


class IdAction(BaseModel):
    id: int
    action: str
    amount: Optional[float] = None
    note: Optional[str] = None
    tx_hash: Optional[str] = None


class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = ""
    group_link: Optional[str] = ""
    group_id: Optional[str] = ""
    group_username: Optional[str] = ""
    reward: float = 1.0
    reward_type: str = "withdrawable"
    is_active: int = 1
    is_mandatory: int = 1
    icon: str = ""
    task_type: str = "join"
    task_config: Optional[str] = ""


class GroupBroadcast(BaseModel):
    message: str
    group_ids: list = []
    parse_mode: str = "HTML"
    photo_url: Optional[str] = ""


class DirectMessage(BaseModel):
    user_id: int
    message: str
    photo_url: Optional[str] = ""
    parse_mode: str = "HTML"


@app.post("/api/admin/dm")
def admin_send_dm(req: DirectMessage, request: Request):
    require_admin(request)
    import json as _json
    import urllib.request as _urllib
    token = os.getenv("BOT_TOKEN", "")
    if not token:
        return {"ok": False, "error": "BOT_TOKEN not set"}
    message = req.message.strip()
    if not message:
        return {"ok": False, "error": "Message is required"}
    has_photo = bool(req.photo_url and req.photo_url.strip())
    try:
        if has_photo:
            url = f"https://api.telegram.org/bot{token}/sendPhoto"
            payload = _json.dumps({"chat_id": req.user_id, "photo": req.photo_url.strip(), "caption": message, "parse_mode": req.parse_mode}).encode()
        else:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            payload = _json.dumps({"chat_id": req.user_id, "text": message, "parse_mode": req.parse_mode}).encode()
        req_url = _urllib.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with _urllib.urlopen(req_url, timeout=15) as r:
            resp = _json.loads(r.read().decode())
            if resp.get("ok"):
                return {"ok": True, "message": f"Message sent to user {req.user_id}"}
            else:
                return {"ok": False, "error": resp.get("description", "Unknown error")}
    except Exception as e:
        return {"ok": False, "error": str(e)}


class GroupBulkAdd(BaseModel):
    user_ids: List[str]
    group: str
    method: str = "direct"


def cursor(conn):
    return get_cursor(conn)


def val(row, key, default=None):
    if row is None:
        return default
    try:
        return row[key] if row[key] is not None else default
    except Exception:
        return default


def rows_as_dicts(rows):
    return [dict(r) for r in rows]


def get_tier(balance):
    for idx, (minimum, pct) in enumerate(TIERS):
        if balance >= minimum:
            return idx, minimum, pct
    return len(TIERS) - 1, 0, 0


_seed_referral_tasks()
_seed_join_tasks()


def invoice_id():
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=8))


def ensure_user(user_id: int, username: str = "", referred_by=None):
    user_id = int(user_id or 123456789)
    if user_id < 1:
        user_id = 123456789
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute(f"SELECT * FROM users WHERE user_id={ph()}", (user_id,))
        row = cur.fetchone()
        now = datetime.utcnow().isoformat()
        if not row:
            ref = None
            try:
                cand = int(referred_by) if referred_by else None
                if cand and cand != user_id:
                    cur.execute(f"SELECT user_id FROM users WHERE user_id={ph()}", (cand,))
                    ref = cand if cur.fetchone() else None
            except Exception:
                pass
            cur.execute(
                f"INSERT INTO users (user_id,username,referred_by,created_at,last_claim,last_auto_claim,current_tier) VALUES ({ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()})",
                (user_id, username or f"user_{user_id}", ref, now, now, now, len(TIERS) - 1),
            )
            conn.commit()
        elif username and username != val(row, "username", ""):
            cur.execute(f"UPDATE users SET username={ph()} WHERE user_id={ph()}", (username, user_id))
            conn.commit()
        cur.execute(f"SELECT * FROM users WHERE user_id={ph()}", (user_id,))
        return cur.fetchone()
    finally:
        safe_close(conn)


def recalc_profit(user_id: int):
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute(f"SELECT * FROM users WHERE user_id={ph()}", (user_id,))
        user = cur.fetchone()
        if not user:
            return None
        now = datetime.utcnow()
        balance = float(val(user, "balance", 0) or 0)
        tier_index, _, daily_percent = get_tier(balance)
        ai_end_str = val(user, "ai_end")
        ai_start_str = val(user, "ai_start")
        current_tier = val(user, "current_tier", len(TIERS) - 1)
        end_dt = None
        try:
            end_dt = datetime.fromisoformat(ai_end_str) if ai_end_str else None
        except Exception:
            end_dt = None
        if end_dt and now >= end_dt and balance > 0:
            expired_amount = balance
            cur.execute(
                f"UPDATE users SET balance=0, profit=0, ai_start=NULL, ai_end=NULL, current_tier={ph()}, profit_per_hour=0 WHERE user_id={ph()}",
                (len(TIERS) - 1, user_id),
            )
            try:
                cur.execute(
                    f"INSERT INTO admin_logs (admin_action,target_user_id,details) VALUES ('ai_expired',{ph()},{ph()})",
                    (user_id, f"Expired {expired_amount} USDT after 30d - {ai_end_str}"),
                )
            except Exception:
                pass
            conn.commit()
            cur.execute(f"SELECT * FROM users WHERE user_id={ph()}", (user_id,))
            user = cur.fetchone()
            balance = 0
            tier_index, _, daily_percent = get_tier(0)
            end_dt = None
            ai_end_str = None
        if balance >= 20 and not ai_end_str:
            ai_start = now.isoformat()
            ai_end = (now + timedelta(days=30)).isoformat()
            cur.execute(
                f"UPDATE users SET ai_start={ph()}, ai_end={ph()}, current_tier={ph()} WHERE user_id={ph()}",
                (ai_start, ai_end, tier_index, user_id),
            )
            ai_end_str = ai_end
            try:
                end_dt = datetime.fromisoformat(ai_end)
            except Exception:
                end_dt = now + timedelta(days=30)
        elif current_tier != tier_index and balance >= 20:
            ai_start = now.isoformat()
            ai_end = (now + timedelta(days=30)).isoformat()
            cur.execute(
                f"UPDATE users SET ai_start={ph()}, ai_end={ph()}, current_tier={ph()} WHERE user_id={ph()}",
                (ai_start, ai_end, tier_index, user_id),
            )
            ai_end_str = ai_end
            try:
                end_dt = datetime.fromisoformat(ai_end)
            except Exception:
                end_dt = now + timedelta(days=30)
            try:
                cur.execute(
                    f"INSERT INTO admin_logs (admin_action,target_user_id,details) VALUES ('tier_change_reset',{ph()},{ph()})",
                    (user_id, f"Tier {current_tier}->{tier_index}, timer reset to 30d"),
                )
            except Exception:
                pass
        elif current_tier != tier_index:
            cur.execute(f"UPDATE users SET current_tier={ph()} WHERE user_id={ph()}", (tier_index, user_id))
        profit = float(val(user, "profit", 0) or 0)
        per_hour = balance * daily_percent / 2400 if balance > 0 else 0
        last_claim = val(user, "last_claim")
        active = False
        try:
            active = bool(end_dt and now < end_dt and balance >= 20)
            if active and last_claim:
                hours = max(0, (now - datetime.fromisoformat(last_claim)).total_seconds() / 3600)
                profit += hours * per_hour
        except Exception:
            active = False
        cur.execute(
            f"UPDATE users SET profit={ph()}, profit_per_hour={ph()}, daily_percent={ph()}, last_claim={ph()} WHERE user_id={ph()}",
            (profit, per_hour, daily_percent, now.isoformat(), user_id),
        )
        last_auto = val(user, "last_auto_claim")
        try:
            due = not last_auto or (now - datetime.fromisoformat(last_auto)).total_seconds() >= 86400
        except Exception:
            due = True
        if due and profit > .01 and active:
            cur.execute(
                f"UPDATE users SET withdrawable=COALESCE(withdrawable,0)+{ph()}, profit=0, last_auto_claim={ph()} WHERE user_id={ph()}",
                (profit, now.isoformat(), user_id),
            )
        conn.commit()
        cur.execute(f"SELECT * FROM users WHERE user_id={ph()}", (user_id,))
        return cur.fetchone()
    finally:
        safe_close(conn)


def check_telegram_membership(bot_token, chat_id, user_id):
    try:
        url = f"https://api.telegram.org/bot{bot_token}/getChatMember?chat_id={urllib.parse.quote(str(chat_id))}&user_id={user_id}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode())
            if not data.get("ok"):
                return False, data
            status = data["result"]["status"]
            return status in ["member", "administrator", "creator", "restricted"], data
    except Exception as e:
        return False, {"error": str(e)}


def process_invoice_payment(invoice_id_str, tx_hash, actual_amount):
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute(f"SELECT * FROM deposits WHERE invoice_id={ph()}", (invoice_id_str,))
        dep = cur.fetchone()
        if not dep:
            return False, "Invoice not found"
        if val(dep, "status") != "awaiting_payment":
            return False, "Already processed"
        cur.execute(f"SELECT tx_hash FROM used_tx_hashes WHERE tx_hash={ph()}", (tx_hash,))
        if cur.fetchone():
            return False, "TX already used"
        user_id = val(dep, "user_id")
        expected = float(val(dep, "expected_amount", 0) or val(dep, "amount", 0))
        amt = actual_amount or expected
        now = datetime.utcnow().isoformat()
        cur.execute(
            f"UPDATE deposits SET status='verified', actual_amount={ph()}, tx_hash={ph()}, verified_at={ph()} WHERE invoice_id={ph()}",
            (amt, tx_hash, now, invoice_id_str),
        )
        cur.execute(f"INSERT INTO used_tx_hashes (tx_hash, used_at) VALUES ({ph()},{ph()})", (tx_hash, now))
        cur.execute(f"SELECT * FROM users WHERE user_id={ph()}", (user_id,))
        user = cur.fetchone()
        if user:
            new_bal = float(val(user, "balance", 0) or 0) + amt
            new_total = float(val(user, "total_deposit", 0) or 0) + amt
            tier_idx, _, _ = get_tier(new_bal)
            ai_end = (datetime.utcnow() + timedelta(days=30)).isoformat()
            cur.execute(
                f"UPDATE users SET balance={ph()}, total_deposit={ph()}, current_tier={ph()}, ai_start={ph()}, ai_end={ph()} WHERE user_id={ph()}",
                (new_bal, new_total, tier_idx, now, ai_end, user_id),
            )
            _process_referrals(cur, user_id, amt)
        conn.commit()
        logger.info(f"Invoice {invoice_id_str} auto-verified: {amt} USDT for user {user_id}")
        return True, "Verified"
    except Exception as e:
        logger.error(f"process_invoice_payment error: {e}")
        return False, str(e)
    finally:
        safe_close(conn)


def _process_referrals(cur, user_id, deposit_amount):
    cur.execute(f"SELECT referred_by FROM users WHERE user_id={ph()}", (user_id,))
    row = cur.fetchone()
    if not row:
        return
    referrer = val(row, "referred_by")
    if not referrer:
        return
    now = datetime.utcnow().isoformat()
    bonus_pct = REF_BONUS.get(1, 7)
    bonus = round(deposit_amount * bonus_pct / 100, 2)
    if bonus > 0:
        cur.execute(
            f"UPDATE users SET withdrawable=COALESCE(withdrawable,0)+{ph()}, referral_earnings=COALESCE(referral_earnings,0)+{ph()} WHERE user_id={ph()}",
            (bonus, bonus, referrer),
        )
        cur.execute(
            f"INSERT INTO referral_logs (from_user,to_user,level,deposit_amount,bonus_amount,bonus_percent,created_at) VALUES ({ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()})",
            (user_id, referrer, 1, deposit_amount, bonus, bonus_pct, now),
        )


@app.post("/webhook/{token}")
async def webhook_handler(token: str, request: Request):
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")
    if token != BOT_TOKEN:
        return {"ok": False}
    ip = request.client.host if request.client else "unknown"
    if not check_rate_limit(ip, 200):
        return {"ok": False}
    try:
        data = await request.json()
        msg = data.get("message") or data.get("callback_query")
        if not msg:
            return {"ok": True}

        is_callback = "callback_query" in data
        if is_callback:
            cb = data["callback_query"]
            chat_id = cb["message"]["chat"]["id"]
            message_id = cb["message"]["message_id"]
            user = cb["from"]
            cb_data = cb.get("data", "")
            cb_query_id = cb.get("id", "")
        else:
            chat_id = msg["chat"]["id"]
            user = msg.get("from", {})
            cb_data = ""
            cb_query_id = ""

        from bot import handle_start, handle_callback
        if not is_callback and msg.get("new_chat_members"):
            mid = msg.get("message_id")
            if mid and chat_id:
                try:
                    import urllib.request as _urllib2
                    import json as _json2
                    del_url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteMessage"
                    del_payload = _json2.dumps({"chat_id": chat_id, "message_id": mid}).encode()
                    del_req = _urllib2.Request(del_url, data=del_payload, headers={"Content-Type": "application/json"})
                    _urllib2.urlopen(del_req, timeout=5)
                except Exception:
                    pass
        elif not is_callback and msg.get("left_chat_member"):
            mid = msg.get("message_id")
            if mid and chat_id:
                try:
                    import urllib.request as _urllib3
                    import json as _json3
                    del_url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteMessage"
                    del_payload = _json3.dumps({"chat_id": chat_id, "message_id": mid}).encode()
                    del_req = _urllib3.Request(del_url, data=del_payload, headers={"Content-Type": "application/json"})
                    _urllib3.urlopen(del_req, timeout=5)
                except Exception:
                    pass
        elif not is_callback and msg.get("text", "").startswith("/start"):
            args = msg["text"].split(" ", 1)[1:] if " " in msg.get("text", "") else []
            await handle_start(BOT_TOKEN, chat_id, user, args)
        elif is_callback:
            await handle_callback(BOT_TOKEN, chat_id, message_id, user, cb_data, cb_query_id)

        return {"ok": True}
    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
        return {"ok": False}


@app.get("/webhook/{token}")
def webhook_get(token: str):
    return {"ok": True, "message": "Webhook active"}


@app.get("/api/me/{user_id}")
def api_me(user_id: int, username: Optional[str] = Query(None), referred_by: Optional[str] = Query(None)):
    u = ensure_user(user_id, username or "", referred_by)
    u = recalc_profit(user_id)
    d = dict(u)
    tier_idx, _, pct = get_tier(float(d.get("balance", 0)))
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute(f"SELECT COUNT(*) as cnt FROM tasks WHERE is_mandatory=1 AND is_active=1")
        mand_cnt = val(cur.fetchone(), "cnt", 0) or 0
        cur.execute(f"SELECT COUNT(*) as cnt FROM user_tasks ut JOIN tasks t ON ut.task_id=t.id WHERE ut.user_id={ph()} AND ut.status='verified' AND t.is_mandatory=1 AND t.is_active=1", (user_id,))
        verified_cnt = val(cur.fetchone(), "cnt", 0) or 0
        d["mandatory_tasks_total"] = mand_cnt
        d["mandatory_tasks_done"] = verified_cnt
        d["all_tasks_done"] = mand_cnt == 0 or verified_cnt >= mand_cnt
    finally:
        safe_close(conn)
    d["tier"] = tier_idx
    d["daily_percent"] = pct
    d["is_banned"] = bool(d.get("is_banned", 0))
    d["login_streak"] = int(d.get("login_streak", 0) or 0)
    d["last_login_date"] = d.get("last_login_date", "") or ""
    d["last_spin_date"] = d.get("last_spin_date", "") or ""
    d["can_spin"] = d["last_spin_date"] != _today()
    conn2 = get_conn()
    try:
        cur2 = cursor(conn2)
        cur2.execute(f"SELECT COUNT(*) as cnt FROM deposits WHERE user_id={ph()} AND status='verified'", (user_id,))
        d["verified_deposits_count"] = val(cur2.fetchone(), "cnt", 0) or 0
        cur2.execute(f"SELECT expected_amount FROM deposits WHERE user_id={ph()} AND status='verified' ORDER BY id DESC LIMIT 1", (user_id,))
        last_dep = cur2.fetchone()
        d["last_deposit_amount"] = float(val(last_dep, "expected_amount", 0) or 0) if last_dep else 0
    except Exception:
        d["verified_deposits_count"] = 0
        d["last_deposit_amount"] = 0
    finally:
        safe_close(conn2)
    try:
        conn3 = get_conn()
        cur3 = cursor(conn3)
        cur3.execute(f"UPDATE users SET last_webapp_open={ph()} WHERE user_id={ph()}", (datetime.utcnow().isoformat(), user_id))
        conn3.commit()
        safe_close(conn3)
    except Exception:
        pass
    return d


@app.get("/api/user/{user_id}")
def api_user_alias(user_id: int, username: Optional[str] = Query(None), referred_by: Optional[str] = Query(None)):
    return api_me(user_id, username, referred_by)


DAILY_BONUS_AMOUNT = 0.10
STREAK_REWARDS = {3: 0.5, 7: 2.0, 14: 5.0, 30: 10.0}
SPIN_PRIZES = [0.05, 0.10, 0.15, 0.20, 0.50, 1.00, 2.00, 5.00]
SPIN_WEIGHTS = [30, 25, 18, 12, 8, 4, 2, 1]


def _today():
    return datetime.utcnow().strftime("%Y-%m-%d")


def _is_yesterday(date_str):
    if not date_str:
        return False
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        return d == (datetime.utcnow().date() - timedelta(days=1))
    except Exception:
        return False


@app.post("/api/daily-bonus/{user_id}")
def claim_daily_bonus(user_id: int):
    today = _today()
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute(f"SELECT last_login_date, login_streak FROM users WHERE user_id={ph()}", (user_id,))
        row = cur.fetchone()
        if not row:
            return {"ok": False, "error": "User not found"}
        last_date = val(row, "last_login_date", "") or ""
        streak = int(val(row, "login_streak", 0) or 0)
        if last_date == today:
            return {"ok": False, "error": "Already claimed today", "streak": streak, "bonus": 0}
        if _is_yesterday(last_date):
            streak += 1
        else:
            streak = 1
        bonus = DAILY_BONUS_AMOUNT
        streak_bonus = 0
        for days, reward in sorted(STREAK_REWARDS.items()):
            if streak == days:
                streak_bonus = reward
                break
        total = bonus + streak_bonus
        cur.execute(f"UPDATE users SET balance=COALESCE(balance,0)+{ph()}, withdrawable=COALESCE(withdrawable,0)+{ph()}, last_login_date={ph()}, login_streak={ph()} WHERE user_id={ph()}", (total, total, today, streak, user_id))
        conn.commit()
        msg = f"+{bonus:.2f} USDT daily bonus!"
        if streak_bonus > 0:
            msg += f" +{streak_bonus:.2f} USDT streak bonus ({streak} days!)"
        return {"ok": True, "bonus": bonus, "streak_bonus": streak_bonus, "total": total, "streak": streak, "message": msg}
    except Exception as e:
        logger.error(f"daily_bonus error: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        safe_close(conn)


@app.get("/api/spin/status/{user_id}")
def spin_status(user_id: int):
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute(f"SELECT last_spin_date, login_streak FROM users WHERE user_id={ph()}", (user_id,))
        row = cur.fetchone()
        if not row:
            return {"available": False}
        last_spin = val(row, "last_spin_date", "") or ""
        streak = int(val(row, "login_streak", 0) or 0)
        can_spin = last_spin != _today()
        return {"available": can_spin, "last_spin": last_spin, "streak": streak, "prizes": SPIN_PRIZES}
    finally:
        safe_close(conn)


import random as _random

@app.post("/api/spin/{user_id}")
def claim_spin(user_id: int):
    today = _today()
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute(f"SELECT last_spin_date FROM users WHERE user_id={ph()}", (user_id,))
        row = cur.fetchone()
        if not row:
            return {"ok": False, "error": "User not found"}
        last_spin = val(row, "last_spin_date", "") or ""
        if last_spin == today:
            return {"ok": False, "error": "Already spun today. Come back tomorrow!"}
        prize = _random.choices(SPIN_PRIZES, weights=SPIN_WEIGHTS, k=1)[0]
        cur.execute(f"UPDATE users SET balance=COALESCE(balance,0)+{ph()}, last_spin_date={ph()} WHERE user_id={ph()}", (prize, today, user_id))
        conn.commit()
        return {"ok": True, "prize": prize, "message": f"You won {prize:.2f} USDT!"}
    except Exception as e:
        logger.error(f"spin error: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        safe_close(conn)


# ==================== MINI GAMES ====================
# WIN: withdrawable unchanged (bet returned), profit goes to deposit balance
# LOSE: withdrawable decreases by bet
# Admin profits via house edge built into each game

class GameBet(BaseModel):
    bet: float
    choice: str = ""

class CrashBet(BaseModel):
    bet: float

@app.post("/api/game/coinflip/{user_id}")
def play_coinflip(user_id: int, body: GameBet):
    bet = round(body.bet, 2)
    choice = body.choice.lower().strip()
    if bet < 0.50:
        return {"ok": False, "error": "Minimum bet is 0.50 USDT"}
    if choice not in ("heads", "tails"):
        return {"ok": False, "error": "Choose heads or tails"}
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute(f"SELECT withdrawable FROM users WHERE user_id={ph()}", (user_id,))
        row = cur.fetchone()
        if not row:
            return {"ok": False, "error": "User not found"}
        wd = float(val(row, "withdrawable", 0) or 0)
        if wd < bet:
            return {"ok": False, "error": f"Insufficient withdrawable ({wd:.2f} USDT)"}
        result = _random.choice(["heads", "tails"])
        won = result == choice
        profit = round(bet * 0.9, 2) if won else 0
        if won:
            cur.execute(f"UPDATE users SET balance=COALESCE(balance,0)+{ph()},total_games_played=total_games_played+1,total_games_won=total_games_won+1 WHERE user_id={ph()}", (profit, user_id))
        else:
            cur.execute(f"UPDATE users SET withdrawable=withdrawable-{ph()},total_games_played=total_games_played+1 WHERE user_id={ph()}", (bet, user_id))
        cur.execute(f"INSERT INTO game_history (user_id,game_type,bet,result,payout,choice,details,created_at) VALUES ({ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()})", (user_id, 'coinflip', bet, 'won' if won else 'lost', round(bet + profit, 2) if won else 0, choice, json.dumps({"coin": result}), datetime.utcnow().isoformat()))
        conn.commit()
        cur.execute(f"SELECT balance, withdrawable FROM users WHERE user_id={ph()}", (user_id,))
        row2 = cur.fetchone()
        new_bal = float(val(row2, "balance", 0) or 0)
        new_wd = float(val(row2, "withdrawable", 0) or 0)
        return {"ok": True, "result": result, "choice": choice, "won": won, "payout": round(bet + profit, 2) if won else 0, "profit": profit, "bet": bet, "balance": round(new_bal, 2), "withdrawable": round(new_wd, 2)}
    except Exception as e:
        logger.error(f"coinflip error: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        safe_close(conn)


@app.post("/api/game/dice/{user_id}")
def play_dice(user_id: int, body: GameBet):
    bet = round(body.bet, 2)
    prediction = body.choice.lower().strip()
    if bet < 0.50:
        return {"ok": False, "error": "Minimum bet is 0.50 USDT"}
    if prediction not in ("over", "under"):
        return {"ok": False, "error": "Choose over or under"}
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute(f"SELECT withdrawable FROM users WHERE user_id={ph()}", (user_id,))
        row = cur.fetchone()
        if not row:
            return {"ok": False, "error": "User not found"}
        wd = float(val(row, "withdrawable", 0) or 0)
        if wd < bet:
            return {"ok": False, "error": f"Insufficient withdrawable ({wd:.2f} USDT)"}
        d1 = _random.randint(1, 6)
        d2 = _random.randint(1, 6)
        total = d1 + d2
        is_over = total > 7
        is_under = total < 7
        won = (prediction == "over" and is_over) or (prediction == "under" and is_under)
        profit = round(bet * 1.0, 2) if won else 0
        if won:
            cur.execute(f"UPDATE users SET balance=COALESCE(balance,0)+{ph()},total_games_played=total_games_played+1,total_games_won=total_games_won+1 WHERE user_id={ph()}", (profit, user_id))
        else:
            cur.execute(f"UPDATE users SET withdrawable=withdrawable-{ph()},total_games_played=total_games_played+1 WHERE user_id={ph()}", (bet, user_id))
        cur.execute(f"INSERT INTO game_history (user_id,game_type,bet,result,payout,choice,details,created_at) VALUES ({ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()})", (user_id, 'dice', bet, 'won' if won else 'lost', round(bet + profit, 2) if won else 0, prediction, json.dumps({"dice": [d1, d2], "total": total}), datetime.utcnow().isoformat()))
        conn.commit()
        cur.execute(f"SELECT balance, withdrawable FROM users WHERE user_id={ph()}", (user_id,))
        row2 = cur.fetchone()
        new_bal = float(val(row2, "balance", 0) or 0)
        new_wd = float(val(row2, "withdrawable", 0) or 0)
        return {"ok": True, "dice": [d1, d2], "total": total, "won": won, "prediction": prediction, "payout": round(bet + profit, 2) if won else 0, "profit": profit, "bet": bet, "balance": round(new_bal, 2), "withdrawable": round(new_wd, 2)}
    except Exception as e:
        logger.error(f"dice error: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        safe_close(conn)


@app.post("/api/game/crash/{user_id}")
def play_crash(user_id: int, body: CrashBet):
    bet = round(body.bet, 2)
    if bet < 0.50:
        return {"ok": False, "error": "Minimum bet is 0.50 USDT"}
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute(f"SELECT withdrawable FROM users WHERE user_id={ph()}", (user_id,))
        row = cur.fetchone()
        if not row:
            return {"ok": False, "error": "User not found"}
        wd = float(val(row, "withdrawable", 0) or 0)
        if wd < bet:
            return {"ok": False, "error": f"Insufficient withdrawable ({wd:.2f} USDT)"}
        h = _random.random()
        crash_point = max(1.01, round(0.97 / max(0.0001, 1 - h), 2))
        cur.execute(f"UPDATE users SET withdrawable=withdrawable-{ph()},total_games_played=total_games_played+1 WHERE user_id={ph()}", (bet, user_id))
        cur.execute(f"INSERT INTO game_history (user_id,game_type,bet,result,payout,choice,details,created_at) VALUES ({ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()})", (user_id, 'crash', bet, 'active', 0, '', json.dumps({"crash_point": crash_point}), datetime.utcnow().isoformat()))
        conn.commit()
        cur.execute(f"SELECT balance, withdrawable FROM users WHERE user_id={ph()}", (user_id,))
        row2 = cur.fetchone()
        new_bal = float(val(row2, "balance", 0) or 0)
        new_wd = float(val(row2, "withdrawable", 0) or 0)
        return {"ok": True, "crash_point": crash_point, "bet": bet, "balance": round(new_bal, 2), "withdrawable": round(new_wd, 2)}
    except Exception as e:
        logger.error(f"crash error: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        safe_close(conn)


@app.post("/api/game/crash/cashout/{user_id}")
def crash_cashout(user_id: int, req: GameBet):
    payout = round(req.bet, 2)
    if payout <= 0:
        return {"ok": False, "error": "Invalid payout"}
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute(f"UPDATE users SET balance=COALESCE(balance,0)+{ph()},total_games_won=total_games_won+1 WHERE user_id={ph()}", (payout, user_id))
        cur.execute(f"INSERT INTO game_history (user_id,game_type,bet,result,payout,choice,details,created_at) VALUES ({ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()})", (user_id, 'crash', payout, 'won', payout, 'cashout', json.dumps({"cashout_multiplier": round(payout / max(0.01, payout), 2)}), datetime.utcnow().isoformat()))
        conn.commit()
        cur.execute(f"SELECT balance, withdrawable FROM users WHERE user_id={ph()}", (user_id,))
        row = cur.fetchone()
        new_bal = float(val(row, "balance", 0) or 0)
        new_wd = float(val(row, "withdrawable", 0) or 0)
        return {"ok": True, "balance": round(new_bal, 2), "withdrawable": round(new_wd, 2)}
    except Exception as e:
        logger.error(f"crash cashout error: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        safe_close(conn)


@app.post("/api/game/highlow/{user_id}")
def play_highlow(user_id: int, body: GameBet):
    bet = round(body.bet, 2)
    prediction = body.choice.lower().strip()
    if bet < 0.50:
        return {"ok": False, "error": "Minimum bet is 0.50 USDT"}
    if prediction not in ("high", "low"):
        return {"ok": False, "error": "Choose high or low"}
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute(f"SELECT withdrawable FROM users WHERE user_id={ph()}", (user_id,))
        row = cur.fetchone()
        if not row:
            return {"ok": False, "error": "User not found"}
        wd = float(val(row, "withdrawable", 0) or 0)
        if wd < bet:
            return {"ok": False, "error": f"Insufficient withdrawable ({wd:.2f} USDT)"}
        card1 = _random.randint(2, 14)
        card2 = _random.randint(2, 14)
        won = (prediction == "high" and card2 > card1) or (prediction == "low" and card2 < card1)
        profit = round(bet * 0.8, 2) if won else 0
        if won:
            cur.execute(f"UPDATE users SET balance=COALESCE(balance,0)+{ph()},total_games_played=total_games_played+1,total_games_won=total_games_won+1 WHERE user_id={ph()}", (profit, user_id))
        else:
            cur.execute(f"UPDATE users SET withdrawable=withdrawable-{ph()},total_games_played=total_games_played+1 WHERE user_id={ph()}", (bet, user_id))
        cur.execute(f"INSERT INTO game_history (user_id,game_type,bet,result,payout,choice,details,created_at) VALUES ({ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()})", (user_id, 'highlow', bet, 'won' if won else 'lost', round(bet + profit, 2) if won else 0, prediction, json.dumps({"card1": card1, "card2": card2}), datetime.utcnow().isoformat()))
        conn.commit()
        cur.execute(f"SELECT balance, withdrawable FROM users WHERE user_id={ph()}", (user_id,))
        row2 = cur.fetchone()
        new_bal = float(val(row2, "balance", 0) or 0)
        new_wd = float(val(row2, "withdrawable", 0) or 0)
        return {"ok": True, "card1": card1, "card2": card2, "won": won, "prediction": prediction, "payout": round(bet + profit, 2) if won else 0, "profit": profit, "bet": bet, "balance": round(new_bal, 2), "withdrawable": round(new_wd, 2)}
    except Exception as e:
        logger.error(f"highlow error: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        safe_close(conn)

@app.get("/api/deposit-addresses")
def deposit_addresses():
    return DEPOSIT_ADDR


@app.post("/api/deposit/invoice/{user_id}")
@app.post("/api/deposit/create_invoice/{user_id}")
def create_invoice(user_id: int, req: InvoiceRequest):
    ip = str(user_id)
    if not check_rate_limit(f"inv:{ip}", 10):
        return {"error": "Too many requests. Wait a minute."}
    ensure_user(user_id)
    conn = get_conn()
    try:
        cur = cursor(conn)
        inv = invoice_id()
        now = datetime.utcnow()
        exp = now + timedelta(minutes=15)
        if req.network not in DEPOSIT_ADDR:
            req.network = "TRC20"
        cur.execute(
            f"INSERT INTO deposits (user_id,amount,network,status,created_at,expires_at,invoice_id,expected_amount) VALUES ({ph()},{ph()},{ph()},'awaiting_payment',{ph()},{ph()},{ph()},{ph()})",
            (user_id, req.amount, req.network, now.isoformat(), exp.isoformat(), inv, req.amount),
        )
        conn.commit()
        addr = DEPOSIT_ADDR.get(req.network, DEPOSIT_ADDR["TRC20"])
        return {"invoice_id": inv, "address": addr, "amount": req.amount, "network": req.network, "expires_at": exp.isoformat(), "qr": addr, "expected_amount": req.amount}
    finally:
        safe_close(conn)


@app.get("/api/deposit/invoice_status/{invoice_id}")
def invoice_status(invoice_id: str):
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute(f"SELECT * FROM deposits WHERE invoice_id={ph()}", (invoice_id,))
        d = cur.fetchone()
        if not d:
            return {"error": "not found"}
        return dict(d)
    finally:
        safe_close(conn)


@app.get("/api/deposit/check_payment/{invoice_id}")
def check_payment(invoice_id: str):
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute(f"SELECT * FROM deposits WHERE invoice_id={ph()}", (invoice_id,))
        d = cur.fetchone()
        if not d:
            return {"ok": False, "error": "Invoice not found", "status": "not_found"}
        dep = dict(d)
        status = dep.get("status", "")
        if status == "verified":
            return {"ok": True, "status": "verified", "message": "Payment verified! Balance credited."}
        if status != "awaiting_payment":
            return {"ok": False, "status": status, "message": f"Invoice is {status}."}
        exp_str = dep.get("expires_at")
        if exp_str:
            try:
                if datetime.utcnow() > datetime.fromisoformat(exp_str):
                    cur.execute(f"UPDATE deposits SET status='expired' WHERE invoice_id={ph()}", (invoice_id,))
                    conn.commit()
                    return {"ok": False, "status": "expired", "message": "Invoice expired. Please create a new one."}
            except Exception:
                pass
        from blockchain_monitor import verify_pending_deposits
        try:
            verify_pending_deposits()
        except Exception as e:
            logger.warning(f"Manual check trigger error: {e}")
        cur.execute(f"SELECT * FROM deposits WHERE invoice_id={ph()}", (invoice_id,))
        d2 = cur.fetchone()
        if d2:
            new_status = dict(d2).get("status", status)
            if new_status == "verified":
                return {"ok": True, "status": "verified", "message": "Payment verified! Balance credited."}
            elif new_status == "expired":
                return {"ok": False, "status": "expired", "message": "Invoice expired. Please create a new one."}
        return {"ok": False, "status": "awaiting_payment", "message": "No payment detected yet. Make sure you sent the exact amount to the correct address."}
    except Exception as e:
        logger.error(f"check_payment error: {e}", exc_info=True)
        return {"ok": False, "status": "error", "message": "Check failed. Try again."}
    finally:
        safe_close(conn)


@app.post("/api/withdraw/{user_id}")
@app.post("/api/withdraw/request/{user_id}")
def withdraw(user_id: int, req: WithdrawalRequest):
    u = ensure_user(user_id)
    u = recalc_profit(user_id)
    if float(val(u, "withdrawable", 0) or 0) < req.amount:
        return {"ok": False, "error": "Insufficient withdrawable balance"}
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute(f"SELECT COUNT(*) as cnt FROM tasks WHERE is_mandatory=1 AND is_active=1")
        mand = val(cur.fetchone(), "cnt", 0) or 0
        if mand > 0:
            cur.execute(f"SELECT COUNT(*) as cnt FROM user_tasks ut JOIN tasks t ON ut.task_id=t.id WHERE ut.user_id={ph()} AND ut.status='verified' AND t.is_mandatory=1 AND t.is_active=1", (user_id,))
            done = val(cur.fetchone(), "cnt", 0) or 0
            if done < mand:
                return {"ok": False, "error": f"Complete {mand} mandatory join tasks first! Go to Tasks tab"}
        cur.execute(
            f"UPDATE users SET withdrawable=COALESCE(withdrawable,0)-{ph()} WHERE user_id={ph()}",
            (req.amount, user_id),
        )
        cur.execute(
            f"INSERT INTO withdrawals (user_id,amount,address,network,status,created_at) VALUES ({ph()},{ph()},{ph()},{ph()},'pending',{ph()})",
            (user_id, req.amount, req.address, req.network, datetime.utcnow().isoformat()),
        )
        conn.commit()
        return {"ok": True, "message": "Withdrawal requested"}
    finally:
        safe_close(conn)


@app.get("/api/history/{user_id}")
def history(user_id: int):
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute(f"SELECT * FROM deposits WHERE user_id={ph()} ORDER BY id DESC LIMIT 100", (user_id,))
        deps = rows_as_dicts(cur.fetchall())
        cur.execute(f"SELECT * FROM withdrawals WHERE user_id={ph()} ORDER BY id DESC LIMIT 100", (user_id,))
        wds = rows_as_dicts(cur.fetchall())
        return {"deposits": deps, "withdrawals": wds}
    finally:
        safe_close(conn)


@app.get("/api/referral/{user_id}")
def referral(user_id: int):
    conn = get_conn()
    try:
        cur = cursor(conn)
        bot_name = os.getenv("BOT_USERNAME", "PT_Minebot")
        cur.execute(f"SELECT user_id,username,balance,total_deposit FROM users WHERE referred_by={ph()} ORDER BY created_at DESC", (user_id,))
        direct = rows_as_dicts(cur.fetchall())
        cur.execute(f"SELECT SUM(bonus_amount) as total FROM referral_logs WHERE to_user={ph()}", (user_id,))
        tot = cur.fetchone()
        try:
            cur.execute(f"SELECT COALESCE(SUM(total_deposit),0) as td FROM users WHERE referred_by={ph()}", (user_id,))
            team_dep = val(cur.fetchone(), "td", 0)
        except Exception:
            team_dep = 0
        cur.execute(f"SELECT * FROM referral_logs WHERE to_user={ph()} ORDER BY id DESC LIMIT 100", (user_id,))
        logs = rows_as_dicts(cur.fetchall())
        return {
            "ref_link": f"https://t.me/{bot_name}?start={user_id}",
            "direct_count": len(direct),
            "total_earnings": val(tot, "total", 0) or 0,
            "total_team_deposit": team_dep or 0,
            "direct_refs": [{"user_id": r["user_id"], "username": r.get("username"), "balance": r.get("balance", 0), "deposit": r.get("total_deposit", 0)} for r in direct],
            "logs": [{"from": l["from_user"], "level": l["level"], "deposit": l["deposit_amount"], "bonus": l["bonus_amount"], "percent": l["bonus_percent"], "at": l["created_at"]} for l in logs],
        }
    finally:
        safe_close(conn)


@app.get("/api/tasks/list/{user_id}")
def tasks_list(user_id: int):
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute(f"SELECT * FROM tasks WHERE is_active=1 ORDER BY sort_order ASC, id ASC")
        tasks = rows_as_dicts(cur.fetchall())
        ut = {}
        try:
            cur.execute(f"SELECT task_id,status,reward_claimed FROM user_tasks WHERE user_id={ph()}", (user_id,))
            ut = {r["task_id"]: r for r in rows_as_dicts(cur.fetchall())}
        except Exception:
            pass
        ref_count = 0
        try:
            cur.execute(f"SELECT COUNT(*) as cnt FROM users WHERE referred_by={ph()}", (user_id,))
            ref_count = val(cur.fetchone(), "cnt", 0) or 0
        except Exception:
            pass
        ref_deposit_count_cache = {}
        out = []
        for t in tasks:
            s = ut.get(t.get("id"))
            tt = val(t, "task_type", "join") or "join"
            referral_current = 0
            referral_target = 0
            min_deposit = 0
            if tt == "referral":
                cfg = val(t, "task_config", "") or ""
                try:
                    cfg_obj = json.loads(cfg) if cfg else {}
                except Exception:
                    cfg_obj = {}
                referral_target = int(cfg_obj.get("ref_count", 0))
                min_deposit = float(cfg_obj.get("min_deposit", 0) or 0)
                if min_deposit > 0:
                    cache_key = int(min_deposit)
                    if cache_key not in ref_deposit_count_cache:
                        try:
                            cur.execute(
                                f"SELECT COUNT(*) as cnt FROM users WHERE referred_by={ph()} AND total_deposit>={ph()}",
                                (user_id, min_deposit),
                            )
                            ref_deposit_count_cache[cache_key] = val(cur.fetchone(), "cnt", 0) or 0
                        except Exception:
                            ref_deposit_count_cache[cache_key] = 0
                    referral_current = min(ref_deposit_count_cache[cache_key], referral_target) if referral_target > 0 else ref_deposit_count_cache[cache_key]
                else:
                    referral_current = min(ref_count, referral_target) if referral_target > 0 else ref_count
            out.append({
                **t,
                "user_status": s.get("status", "pending") if s else "pending",
                "reward_claimed": s.get("reward_claimed", 0) if s else 0,
                "referral_current": referral_current,
                "referral_target": referral_target,
                "min_deposit": min_deposit,
            })
        return out
    except Exception as e:
        logger.error(f"tasks_list error: {e}", exc_info=True)
        return []
    finally:
        safe_close(conn)


@app.post("/api/tasks/verify/{user_id}/{task_id}")
def tasks_verify(user_id: int, task_id: int):
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute(f"SELECT * FROM tasks WHERE id={ph()}", (task_id,))
        task = cur.fetchone()
        if not task:
            return {"ok": False, "error": "Task not found"}
        task_type = val(task, "task_type", "join")
        if task_type == "referral":
            return _verify_referral_task(cur, conn, user_id, task)
        bot_token = os.getenv("BOT_TOKEN", "")
        if not bot_token:
            return {"ok": False, "error": "BOT_TOKEN not set in server env"}
        chat_id = val(task, "group_id")
        is_member, details = check_telegram_membership(bot_token, chat_id, user_id)
        if not is_member:
            return {"ok": False, "error": "Not joined yet. Please JOIN the group/channel first, then click Verify", "details": details}
        return _award_task_reward(cur, conn, user_id, task)
    except Exception as e:
        logger.error(f"tasks_verify error: {e}")
        return {"ok": False, "error": str(e)}
    finally:
        safe_close(conn)


def _verify_referral_task(cur, conn, user_id, task):
    import json as _json
    cfg_str = val(task, "task_config", "")
    try:
        cfg = _json.loads(cfg_str) if cfg_str else {}
    except Exception:
        cfg = {}
    ref_count = int(cfg.get("ref_count", 0))
    min_deposit = float(cfg.get("min_deposit", 0) or 0)
    if min_deposit > 0:
        cur.execute(
            f"SELECT COUNT(*) as cnt FROM users WHERE referred_by={ph()} AND total_deposit>={ph()}",
            (user_id, min_deposit),
        )
        actual = val(cur.fetchone(), "cnt", 0) or 0
        if actual < ref_count:
            return {"ok": False, "error": f"You have {actual}/{ref_count} qualifying referrals (≥{int(min_deposit)} USDT deposit). Keep inviting!"}
    else:
        cur.execute(f"SELECT COUNT(*) as cnt FROM users WHERE referred_by={ph()}", (user_id,))
        actual = val(cur.fetchone(), "cnt", 0) or 0
        if actual < ref_count:
            return {"ok": False, "error": f"You have {actual}/{ref_count} referrals. Keep inviting!"}
    return _award_task_reward(cur, conn, user_id, task)


def _award_task_reward(cur, conn, user_id, task):
    task_id = val(task, "id")
    cur.execute(f"SELECT * FROM user_tasks WHERE user_id={ph()} AND task_id={ph()}", (user_id, task_id))
    existing = cur.fetchone()
    now = datetime.utcnow().isoformat()
    if existing:
        cur.execute(f"UPDATE user_tasks SET status='verified', verified_at={ph()} WHERE user_id={ph()} AND task_id={ph()}", (now, user_id, task_id))
    else:
        cur.execute(f"INSERT INTO user_tasks (user_id,task_id,status,verified_at,reward_claimed) VALUES ({ph()},{ph()},'verified',{ph()},0)", (user_id, task_id, now))
    reward = float(val(task, "reward", 1.0) or 1.0)
    cur.execute(f"SELECT reward_claimed FROM user_tasks WHERE user_id={ph()} AND task_id={ph()}", (user_id, task_id))
    rw = cur.fetchone()
    if not val(rw, "reward_claimed", 0):
        rtype = val(task, "reward_type", "withdrawable")
        if rtype == "withdrawable":
            cur.execute(f"UPDATE users SET withdrawable=COALESCE(withdrawable,0)+{ph()} WHERE user_id={ph()}", (reward, user_id))
        else:
            cur.execute(f"UPDATE users SET balance=COALESCE(balance,0)+{ph()} WHERE user_id={ph()}", (reward, user_id))
        cur.execute(f"UPDATE user_tasks SET reward_claimed=1 WHERE user_id={ph()} AND task_id={ph()}", (user_id, task_id))
    conn.commit()
    return {"ok": True, "reward": reward, "message": f"Verified! +{reward} USDT added to withdrawable balance"}


@app.post("/api/tasks/join/{user_id}/{task_id}")
def tasks_join_click(user_id: int, task_id: int):
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute(f"SELECT * FROM tasks WHERE id={ph()}", (task_id,))
        if not cur.fetchone():
            return {"ok": False}
        try:
            if USE_POSTGRES:
                cur.execute(f"INSERT INTO user_tasks (user_id,task_id,status) VALUES ({ph()},{ph()},'joined') ON CONFLICT (user_id,task_id) DO NOTHING", (user_id, task_id))
            else:
                cur.execute(f"INSERT OR IGNORE INTO user_tasks (user_id,task_id,status) VALUES ({ph()},{ph()},'joined')", (user_id, task_id))
            conn.commit()
        except Exception:
            conn.commit()
        return {"ok": True}
    finally:
        safe_close(conn)


@app.get("/api/binance/trades")
def binance_trades():
    utc_now = datetime.utcnow()
    ist_now = utc_now + timedelta(hours=5, minutes=30)
    today_str = ist_now.date().isoformat()
    seed = int(hashlib.md5(today_str.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    total_trades_for_day = 16 + (seed % 3)
    trades_all = []
    for i in range(total_trades_for_day):
        if i == 0:
            trade_minutes = rng.randint(5, 25)
        else:
            remaining = total_trades_for_day - 1
            slot = 1425 // remaining
            base = 60 + i * slot
            jitter = rng.randint(-20, 20)
            trade_minutes = max(60, min(1439, base + jitter))
        hour = trade_minutes // 60
        minute = trade_minutes % 60
        time_str = f"{hour:02d}:{minute:02d}"
        sym = SYMBOLS[i % len(SYMBOLS)]
        side = rng.choice(["LONG", "SHORT"])
        base_price = BASE_PRICES.get(sym, 100)
        entry = base_price * (1 + rng.uniform(-0.015, 0.015))
        if i < total_trades_for_day * 0.65:
            is_win = rng.random() < 0.78
        else:
            is_win = rng.random() < 0.45
        if is_win:
            pnl = round(rng.uniform(1.2, 6.8), 2)
        else:
            pnl = round(rng.uniform(-2.5, -0.3), 2)
        exitp = entry * (1 + pnl / 100) if side == "LONG" else entry * (1 - pnl / 100)
        amount = round(rng.uniform(300, 1800), 2)
        trades_all.append({
            "id": i + 1,
            "pair": sym.replace("USDT", "/USDT"),
            "symbol": sym,
            "side": side,
            "leverage": rng.choice([5, 10, 15, 20]),
            "usdt_amount": amount,
            "entry_price": round(entry, 6 if entry < 1 else 2),
            "exit_price": round(exitp, 6 if exitp < 1 else 2),
            "pnl_percent": pnl,
            "pnl_usdt": round(amount * pnl / 100, 2),
            "is_profit": pnl > 0,
            "time": time_str,
            "minutes": trade_minutes,
            "status": "CLOSED",
            "date": today_str,
        })
    current_minutes = ist_now.hour * 60 + ist_now.minute
    visible_trades = [t for t in trades_all if t["minutes"] <= current_minutes]
    for t in visible_trades:
        t.pop("minutes", None)
    for t in trades_all:
        t.pop("minutes", None)
    total_pnl = sum(t["pnl_percent"] for t in visible_trades)
    total_usdt = sum(t["pnl_usdt"] for t in visible_trades)
    profit_count = sum(1 for t in visible_trades if t["is_profit"])
    expected_total = len(trades_all)
    prices = BASE_PRICES.copy()
    return {
        "trades": visible_trades,
        "all_trades_count": expected_total,
        "summary": {
            "total_trades": len(visible_trades),
            "expected_total": expected_total,
            "profit_trades": profit_count,
            "loss_trades": len(visible_trades) - profit_count,
            "total_pnl_percent": round(total_pnl, 2),
            "total_pnl_usdt": round(total_usdt, 2),
            "daily_accumulated_pnl": round(total_pnl, 2),
            "funds_in_market": round(sum(t["usdt_amount"] for t in visible_trades), 2),
            "date": today_str,
            "current_ist": ist_now.strftime("%H:%M IST"),
            "win_rate": round((profit_count / len(visible_trades) * 100) if visible_trades else 0, 1),
            "next_trade_in": f"{trades_all[len(visible_trades)]['time'] if len(visible_trades) < len(trades_all) else 'Tomorrow 00:30'} IST" if len(visible_trades) < len(trades_all) else "All trades done for today",
        },
        "prices_source": "deterministic_daily",
        "live_prices": prices,
    }


@app.get("/api/admin/stats")
def admin_stats(request: Request):
    require_admin(request)
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute("SELECT COUNT(*) AS users, COALESCE(SUM(balance),0) AS balance, COALESCE(SUM(withdrawable),0) AS wd, COALESCE(SUM(total_deposit),0) AS tdep FROM users")
        stats = cur.fetchone()
        cur.execute("SELECT COUNT(*) AS users FROM users WHERE is_banned=0 AND total_deposit>0")
        active_stats = cur.fetchone()
        cur.execute("SELECT COUNT(*) AS users FROM users WHERE is_banned=0 AND last_webapp_open != '' AND last_webapp_open::timestamp > NOW() - INTERVAL '5 minutes'")
        online_stats = cur.fetchone()
        cur.execute("SELECT COUNT(*) AS users FROM users WHERE total_deposit>0")
        deposited_stats = cur.fetchone()
        try:
            cur.execute("SELECT COUNT(*) as total FROM deposits WHERE status='awaiting_payment'")
            pending_cnt = val(cur.fetchone(), "total", 0)
        except Exception:
            pending_cnt = 0
        try:
            cur.execute("SELECT COUNT(*) as total FROM deposits WHERE status='verified'")
            verified_cnt = val(cur.fetchone(), "total", 0)
        except Exception:
            verified_cnt = 0
        try:
            cur.execute("SELECT COUNT(*) as total FROM deposits WHERE status='expired'")
            expired_cnt = val(cur.fetchone(), "total", 0)
        except Exception:
            expired_cnt = 0
        try:
            cur.execute("SELECT COALESCE(SUM(actual_amount),0) as s FROM deposits WHERE status='verified'")
            verified_sum = val(cur.fetchone(), "s", 0)
        except Exception:
            verified_sum = 0
        cur.execute("SELECT COUNT(*) AS pending FROM withdrawals WHERE status='pending'")
        wd = cur.fetchone()
        cur.execute("SELECT COALESCE(SUM(bonus_amount),0) AS paid FROM referral_logs")
        ref = cur.fetchone()
        cur.execute("SELECT COUNT(*) AS tasks FROM tasks WHERE is_active=1")
        tc = cur.fetchone()
        cur.execute("SELECT COUNT(*) AS completed FROM user_tasks WHERE status='verified'")
        comp = cur.fetchone()
        try:
            cur.execute("SELECT COALESCE(SUM(amount),0) as s FROM withdrawals WHERE status='approved'")
            wd_sum = val(cur.fetchone(), "s", 0)
        except Exception:
            wd_sum = 0
        return {
            "total_users": val(stats, "users", 0),
            "active_users": val(active_stats, "users", 0),
            "online_users": val(online_stats, "users", 0),
            "deposited_users": val(deposited_stats, "users", 0),
            "total_balance": val(stats, "balance", 0),
            "total_withdrawable": val(stats, "wd", 0),
            "total_deposits_all": val(stats, "tdep", 0),
            "total_verified_deposits": verified_sum,
            "total_withdrawals_all": wd_sum,
            "pending_deposits": pending_cnt,
            "verified_deposits": verified_cnt,
            "expired_deposits": expired_cnt,
            "pending_withdrawals": val(wd, "pending", 0),
            "total_ref_paid": val(ref, "paid", 0),
            "active_tasks": val(tc, "tasks", 0),
            "completed_tasks": val(comp, "completed", 0),
        }
    finally:
        safe_close(conn)


@app.get("/api/admin/deposits")
def admin_deposits(request: Request):
    require_admin(request)
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute("SELECT * FROM deposits ORDER BY id DESC LIMIT 500")
        return [{**x, "expected": x.get("expected_amount", x.get("amount", 0))} for x in rows_as_dicts(cur.fetchall())]
    finally:
        safe_close(conn)


@app.get("/api/admin/withdrawals")
def admin_withdrawals(request: Request):
    require_admin(request)
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute("SELECT * FROM withdrawals ORDER BY id DESC LIMIT 500")
        return rows_as_dicts(cur.fetchall())
    finally:
        safe_close(conn)


@app.get("/api/admin/referrals")
def admin_referrals(request: Request):
    require_admin(request)
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute("SELECT * FROM referral_logs ORDER BY id DESC LIMIT 500")
        return [{"from_user": x["from_user"], "to_user": x["to_user"], "level": x["level"], "deposit": x["deposit_amount"], "bonus": x["bonus_amount"], "percent": x["bonus_percent"]} for x in rows_as_dicts(cur.fetchall())]
    finally:
        safe_close(conn)


@app.get("/api/admin/users")
def admin_users(request: Request):
    require_admin(request)
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute("SELECT * FROM users ORDER BY created_at DESC")
        users = rows_as_dicts(cur.fetchall())
        for u in users:
            uid = u["user_id"]
            cur.execute(f"SELECT COUNT(*) as cnt FROM user_tasks WHERE user_id={ph()} AND reward_claimed=1", (uid,))
            u["tasks_completed"] = val(cur.fetchone(), "cnt", 0) or 0
            cur.execute(f"""SELECT COUNT(*) as cnt FROM user_tasks ut JOIN tasks t ON ut.task_id=t.id
                WHERE ut.user_id={ph()} AND t.is_mandatory=1 AND ut.reward_claimed=1""", (uid,))
            u["mandatory_completed"] = val(cur.fetchone(), "cnt", 0) or 0
            cur.execute(f"SELECT COUNT(*) as cnt FROM tasks WHERE is_mandatory=1 AND is_active=1")
            total_mandatory = val(cur.fetchone(), "cnt", 0) or 0
            u["mandatory_done"] = (u["mandatory_completed"] or 0) >= total_mandatory and total_mandatory > 0
        return users
    finally:
        safe_close(conn)


@app.get("/api/admin/tasks")
def admin_tasks_list(request: Request):
    require_admin(request)
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute("SELECT * FROM tasks ORDER BY sort_order ASC, id DESC")
        return rows_as_dicts(cur.fetchall())
    finally:
        safe_close(conn)


@app.post("/api/admin/tasks/create")
def admin_tasks_create(t: TaskCreate, request: Request):
    require_admin(request)
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute(
            f"INSERT INTO tasks (title,description,group_link,group_id,group_username,reward,reward_type,is_active,is_mandatory,icon,task_type,task_config,created_at) VALUES ({ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()})",
            (t.title, t.description, t.group_link, t.group_id, t.group_username, t.reward, t.reward_type, t.is_active, t.is_mandatory, t.icon, t.task_type, t.task_config, datetime.utcnow().isoformat()),
        )
        conn.commit()
        return {"ok": True}
    finally:
        safe_close(conn)


@app.post("/api/admin/tasks/action")
def admin_tasks_action(a: IdAction, request: Request):
    require_admin(request)
    conn = get_conn()
    try:
        cur = cursor(conn)
        if a.action == "delete":
            cur.execute(f"DELETE FROM tasks WHERE id={ph()}", (a.id,))
        elif a.action == "toggle_active":
            cur.execute(f"UPDATE tasks SET is_active = CASE WHEN is_active=1 THEN 0 ELSE 1 END WHERE id={ph()}", (a.id,))
        elif a.action == "toggle_mandatory":
            cur.execute(f"UPDATE tasks SET is_mandatory = CASE WHEN is_mandatory=1 THEN 0 ELSE 1 END WHERE id={ph()}", (a.id,))
        conn.commit()
        return {"ok": True}
    finally:
        safe_close(conn)


@app.post("/api/admin/deposit/action")
def admin_deposit_action(action: IdAction, request: Request):
    require_admin(request)
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute(f"SELECT * FROM deposits WHERE id={ph()}", (action.id,))
        dep = cur.fetchone()
        if not dep:
            return {"ok": False, "error": "Deposit not found"}
        if action.action == "approve":
            now = datetime.utcnow().isoformat()
            amt = float(val(dep, "expected_amount", 0) or val(dep, "amount", 0))
            cur.execute(
                f"UPDATE deposits SET status='verified', actual_amount={ph()}, verified_at={ph()} WHERE id={ph()}",
                (amt, now, action.id),
            )
            cur.execute(f"SELECT * FROM users WHERE user_id={ph()}", (val(dep, "user_id"),))
            user = cur.fetchone()
            if user:
                new_bal = float(val(user, "balance", 0) or 0) + amt
                new_total = float(val(user, "total_deposit", 0) or 0) + amt
                tier_idx, _, _ = get_tier(new_bal)
                ai_end = (datetime.utcnow() + timedelta(days=30)).isoformat()
                cur.execute(
                    f"UPDATE users SET balance={ph()}, total_deposit={ph()}, current_tier={ph()}, ai_start={ph()}, ai_end={ph()} WHERE user_id={ph()}",
                    (new_bal, new_total, tier_idx, now, ai_end, val(dep, "user_id")),
                )
            conn.commit()
            logger.info(f"Admin approved deposit {action.id}")
            return {"ok": True}
        elif action.action == "reject":
            cur.execute(f"UPDATE deposits SET status='rejected', admin_note={ph()} WHERE id={ph()}", (action.note or "Rejected", action.id))
            conn.commit()
            logger.info(f"Admin rejected deposit {action.id}")
            return {"ok": True}
        elif action.action == "expire":
            cur.execute(f"UPDATE deposits SET status='expired', admin_note={ph()} WHERE id={ph()}", (action.note or "Expired", action.id))
            conn.commit()
            logger.info(f"Admin expired deposit {action.id}")
            return {"ok": True}
        elif action.action == "edit_amount":
            amt = action.amount or 0
            cur.execute(f"UPDATE deposits SET expected_amount={ph()} WHERE id={ph()}", (amt, action.id))
            conn.commit()
            return {"ok": True}
        elif action.action == "delete":
            cur.execute(f"DELETE FROM deposits WHERE id={ph()}", (action.id,))
            conn.commit()
            return {"ok": True}
        else:
            return {"ok": False, "error": "Unsupported action"}
    except Exception as e:
        logger.error(f"Deposit action error: {e}", exc_info=True)
        return {"ok": False, "error": f"Server error: {str(e)[:200]}"}
    finally:
        safe_close(conn)


def _send_wd_notification(wd, tx_hash):
    import json as _json
    import urllib.request as _urllib
    import urllib.parse
    token = os.getenv("BOT_TOKEN", "")
    notify_chat = os.getenv("NOTIFY_CHANNEL", "").strip()
    if not token or not notify_chat:
        return
    uid = val(wd, "user_id")
    amount = val(wd, "amount", 0)
    network = val(wd, "network", "BEP-20")
    addr = val(wd, "address", "")
    short_addr = (addr[:8] + "..." + addr[-6:]) if addr and len(addr) > 16 else addr
    now_str = datetime.utcnow().strftime("%d %b %Y, %H:%M UTC")
    bscscan_link = f"https://bscscan.com/tx/{tx_hash}" if tx_hash else ""
    lines = [
        "<b>✅ Withdrawal Approved</b>",
        "",
        f"👤 User: <code>#{uid}</code>",
        f"💵 Amount: <b>${amount:.2f} USDT</b>",
        f"🔗 Network: {network}",
    ]
    if short_addr:
        lines.append(f"📬 To: <code>{short_addr}</code>")
    if tx_hash:
        lines.append(f"📝 Tx Hash: <code>{tx_hash}</code>")
        lines.append(f"🔍 <a href=\"{bscscan_link}\">View on BSCScan</a>")
    lines.append(f"🕐 {now_str}")
    lines.append(f"📊 Status: <b>Completed</b>")
    text = "\n".join(lines)
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = _json.dumps({"chat_id": notify_chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}).encode()
        req = _urllib.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with _urllib.urlopen(req, timeout=10) as r:
            logger.info(f"Withdrawal notification sent for wd #{val(wd, 'id')}")
    except Exception as e:
        logger.error(f"Failed to send wd notification: {e}")


@app.post("/api/admin/withdraw/action")
def admin_withdraw_action(action: IdAction, request: Request):
    require_admin(request)
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute(f"SELECT * FROM withdrawals WHERE id={ph()}", (action.id,))
        wd = cur.fetchone()
        if not wd:
            return {"ok": False, "error": "Not found"}
        if action.action == "approve":
            tx = action.tx_hash or ""
            cur.execute(f"UPDATE withdrawals SET status='approved', auto_approved=1, tx_hash={ph()} WHERE id={ph()}", (tx, action.id,))
            cur.execute(
                f"UPDATE users SET total_withdraw=COALESCE(total_withdraw,0)+{ph()} WHERE user_id={ph()}",
                (val(wd, "amount", 0), val(wd, "user_id")),
            )
            try:
                _send_wd_notification(wd, tx)
            except Exception as e:
                logger.error(f"Failed to send withdrawal notification: {e}")
        elif action.action == "reject":
            cur.execute(f"UPDATE withdrawals SET status='rejected' WHERE id={ph()}", (action.id,))
            cur.execute(
                f"UPDATE users SET withdrawable=COALESCE(withdrawable,0)+{ph()} WHERE user_id={ph()}",
                (val(wd, "amount", 0), val(wd, "user_id")),
            )
        elif action.action == "expire":
            cur.execute(f"UPDATE withdrawals SET status='expired' WHERE id={ph()}", (action.id,))
            cur.execute(
                f"UPDATE users SET withdrawable=COALESCE(withdrawable,0)+{ph()} WHERE user_id={ph()}",
                (val(wd, "amount", 0), val(wd, "user_id")),
            )
        elif action.action == "delete":
            if val(wd, "status") == "pending":
                cur.execute(
                    f"UPDATE users SET withdrawable=COALESCE(withdrawable,0)+{ph()} WHERE user_id={ph()}",
                    (val(wd, "amount", 0), val(wd, "user_id")),
                )
            cur.execute(f"DELETE FROM withdrawals WHERE id={ph()}", (action.id,))
        conn.commit()
        logger.info(f"Admin withdraw action {action.action} on {action.id}")
        return {"ok": True}
    finally:
        safe_close(conn)


@app.post("/api/admin/user/action")
def admin_user_action(action: AdminAction, request: Request):
    require_admin(request)
    conn = get_conn()
    try:
        cur = cursor(conn)
        act = action.action
        cur.execute(f"SELECT * FROM users WHERE user_id={ph()}", (action.user_id,))
        u = cur.fetchone()
        if not u and act != "delete":
            return {"ok": False, "error": "User not found"}
        amt = float(action.amount or 0)
        if act == "add_balance":
            cur.execute(f"UPDATE users SET balance=COALESCE(balance,0)+{ph()} WHERE user_id={ph()}", (amt, action.user_id))
        elif act == "deduct_balance":
            cur.execute(f"UPDATE users SET balance=GREATEST(0,COALESCE(balance,0)-{ph()}) WHERE user_id={ph()}", (amt, action.user_id))
        elif act == "set_balance":
            cur.execute(f"UPDATE users SET balance={ph()} WHERE user_id={ph()}", (amt, action.user_id))
        elif act == "add_withdrawable":
            cur.execute(f"UPDATE users SET withdrawable=COALESCE(withdrawable,0)+{ph()} WHERE user_id={ph()}", (amt, action.user_id))
        elif act == "deduct_withdrawable":
            cur.execute(f"UPDATE users SET withdrawable=GREATEST(0,COALESCE(withdrawable,0)-{ph()}) WHERE user_id={ph()}", (amt, action.user_id))
        elif act == "set_withdrawable":
            cur.execute(f"UPDATE users SET withdrawable={ph()} WHERE user_id={ph()}", (amt, action.user_id))
        elif act == "ban":
            cur.execute(f"UPDATE users SET is_banned=1 WHERE user_id={ph()}", (action.user_id,))
        elif act == "unban":
            cur.execute(f"UPDATE users SET is_banned=0 WHERE user_id={ph()}", (action.user_id,))
        elif act == "expire_now":
            cur.execute(
                f"UPDATE users SET balance=0, profit=0, ai_start=NULL, ai_end=NULL, current_tier={ph()} WHERE user_id={ph()}",
                (len(TIERS) - 1, action.user_id),
            )
        elif act == "reset_timer":
            now = datetime.utcnow()
            ai_end = (now + timedelta(days=30)).isoformat()
            cur.execute(f"UPDATE users SET ai_start={ph()}, ai_end={ph()} WHERE user_id={ph()}", (now.isoformat(), ai_end, action.user_id))
        elif act == "delete":
            cur.execute(f"DELETE FROM users WHERE user_id={ph()}", (action.user_id,))
        elif act == "clear_tasks":
            cur.execute(f"DELETE FROM user_tasks WHERE user_id={ph()}", (action.user_id,))
        elif act == "reset_profit":
            cur.execute(f"UPDATE users SET profit=0 WHERE user_id={ph()}", (action.user_id,))
        else:
            return {"ok": False, "error": f"Unknown action: {act}"}
        conn.commit()
        logger.info(f"Admin action {act} on user {action.user_id} amt={amt}")
        return {"ok": True}
    finally:
        safe_close(conn)


@app.post("/api/admin/bulk_action")
def admin_bulk_action(request: Request):
    require_admin(request)
    import asyncio
    body = asyncio.get_event_loop().run_until_complete(request.json()) if hasattr(request, "_body") else {}
    try:
        body = None
    except Exception:
        pass
    return {"ok": False, "error": "Use individual actions instead"}


@app.post("/api/admin/broadcast")
async def admin_broadcast(request: Request):
    require_admin(request)
    import json as _json
    import urllib.request as _urllib
    body = await request.json()
    message = body.get("message", "").strip()
    if not message:
        return {"ok": False, "error": "Message is required", "sent": 0}
    token = os.getenv("BOT_TOKEN", "")
    if not token:
        return {"ok": False, "error": "BOT_TOKEN not set", "sent": 0}
    conn = get_conn()
    sent = 0
    failed = 0
    try:
        cur = cursor(conn)
        cur.execute("SELECT user_id FROM users")
        users = cur.fetchall()
        for row in users:
            uid = row[0] if isinstance(row, tuple) else row.get("user_id", 0)
            if not uid:
                continue
            try:
                url = f"https://api.telegram.org/bot{token}/sendMessage"
                payload = _json.dumps({"chat_id": uid, "text": message, "parse_mode": "HTML"}).encode()
                req = _urllib.Request(url, data=payload, headers={"Content-Type": "application/json"})
                with _urllib.urlopen(req, timeout=10) as r:
                    resp = _json.loads(r.read().decode())
                    if resp.get("ok"):
                        sent += 1
                    else:
                        failed += 1
            except Exception:
                failed += 1
    finally:
        safe_close(conn)
    return {"ok": sent > 0, "sent": sent, "failed": failed}


@app.post("/api/admin/upload")
async def admin_upload(request: Request):
    require_admin(request)
    import uuid
    content_type = request.headers.get("content-type", "")
    if "multipart" not in content_type:
        return {"ok": False, "error": "Expected multipart/form-data"}
    form = await request.form()
    file = form.get("file")
    if not file:
        return {"ok": False, "error": "No file provided"}
    filename = getattr(file, "filename", "image.jpg") or "image.jpg"
    ext = os.path.splitext(filename)[1].lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"):
        return {"ok": False, "error": "Unsupported image format"}
    unique_name = f"{uuid.uuid4().hex[:12]}{ext}"
    save_path = os.path.join(UPLOAD_DIR, unique_name)
    data = await file.read()
    with open(save_path, "wb") as f:
        f.write(data)
    WEBAPP_URL = os.getenv("WEBAPP_URL", "").rstrip("/")
    url = f"{WEBAPP_URL}/uploads/{unique_name}"
    return {"ok": True, "url": url, "filename": unique_name}


class SavedMessage(BaseModel):
    title: str
    message: str
    photo_url: Optional[str] = ""


@app.get("/api/admin/saved-messages")
def admin_saved_messages(request: Request):
    require_admin(request)
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute("SELECT id, title, message, photo_url, created_at FROM saved_messages ORDER BY id DESC")
        return rows_as_dicts(cur.fetchall())
    finally:
        safe_close(conn)


@app.post("/api/admin/saved-messages")
def admin_create_saved_message(msg: SavedMessage, request: Request):
    require_admin(request)
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute(
            f"INSERT INTO saved_messages (title, message, photo_url, created_at) VALUES ({ph()},{ph()},{ph()},{ph()}) RETURNING id",
            (msg.title, msg.message, msg.photo_url, datetime.utcnow().isoformat()),
        )
        row = cur.fetchone()
        conn.commit()
        return {"ok": True, "id": val(row, "id", 0) if row else 0}
    finally:
        safe_close(conn)


@app.delete("/api/admin/saved-messages/{msg_id}")
def admin_delete_saved_message(msg_id: int, request: Request):
    require_admin(request)
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute(f"DELETE FROM saved_messages WHERE id={ph()}", (msg_id,))
        conn.commit()
        return {"ok": True}
    finally:
        safe_close(conn)


@app.get("/api/admin/groups")
def admin_groups(request: Request):
    require_admin(request)
    conn = get_conn()
    try:
        cur = cursor(conn)
        try:
            cur.execute("SELECT DISTINCT group_id, group_username, group_link FROM tasks WHERE task_type='join' AND group_id IS NOT NULL AND group_id != ''")
            groups = rows_as_dicts(cur.fetchall())
        except Exception:
            groups = []
        return {"groups": groups}
    finally:
        safe_close(conn)


@app.post("/api/admin/group/broadcast")
def admin_group_broadcast(req: GroupBroadcast, request: Request):
    require_admin(request)
    import json as _json
    import urllib.request as _urllib
    message = req.message.strip()
    group_ids = req.group_ids
    parse_mode = req.parse_mode

    if not message:
        return {"ok": False, "error": "Message is required"}
    if not group_ids:
        return {"ok": False, "error": "Select at least one group"}

    token = os.getenv("BOT_TOKEN", "")
    if not token:
        return {"ok": False, "error": "BOT_TOKEN not set"}

    results = []
    sent = 0
    has_photo = bool(req.photo_url and req.photo_url.strip())
    for gid in group_ids:
        try:
            if has_photo:
                tg_url = f"https://api.telegram.org/bot{token}/sendPhoto"
                payload = _json.dumps({"chat_id": gid, "photo": req.photo_url.strip(), "caption": message, "parse_mode": parse_mode}).encode()
            else:
                tg_url = f"https://api.telegram.org/bot{token}/sendMessage"
                payload = _json.dumps({"chat_id": gid, "text": message, "parse_mode": parse_mode}).encode()
            req_url = _urllib.Request(tg_url, data=payload, headers={"Content-Type": "application/json"})
            with _urllib.urlopen(req_url, timeout=15) as r:
                resp = _json.loads(r.read().decode())
                if resp.get("ok"):
                    sent += 1
                    results.append({"group_id": gid, "ok": True})
                else:
                    results.append({"group_id": gid, "ok": False, "error": resp.get("description", "Unknown error")})
        except Exception as e:
            results.append({"group_id": gid, "ok": False, "error": str(e)})

    return {"ok": sent > 0, "sent": sent, "results": results}


@app.post("/api/admin/group/bulk_add")
def admin_group_bulk_add(request: Request):
    require_admin(request)
    return {"ok": True, "added": 0, "logs": ["Use Telegram Bot API for group management"]}


@app.post("/api/admin/group/invite")
def admin_group_invite(request: Request):
    require_admin(request)
    return {"ok": False, "error": "Use Telegram Bot API directly"}


@app.get("/api/admin/group/members")
def admin_group_members(request: Request):
    require_admin(request)
    conn = get_conn()
    try:
        cur = cursor(conn)
        try:
            cur.execute("SELECT * FROM group_members ORDER BY id DESC LIMIT 100")
            return rows_as_dicts(cur.fetchall())
        except Exception:
            return []
    finally:
        safe_close(conn)


@app.get("/api/admin/env/status")
def admin_env_status(request: Request):
    require_admin(request)
    bt = os.getenv("BOT_TOKEN", "")
    nc = os.getenv("NOTIFY_CHANNEL", "").strip()
    return {
        "has_bot_token": bool(bt),
        "BOT_TOKEN": f"...{bt[-6:]}" if len(bt) > 6 else "NOT SET",
        "GROUP_ID": os.getenv("GROUP_ID", "NOT SET"),
        "WEBAPP_URL": os.getenv("WEBAPP_URL", "NOT SET"),
        "ADMIN_SECRET": "SET" if ADMIN_SECRET else "NOT SET (open)",
        "has_notify_channel": bool(nc),
        "NOTIFY_CHANNEL": nc or "Not set",
    }


@app.post("/api/admin/env/save")
def admin_env_save(request: Request):
    require_admin(request)
    return {"ok": True, "message": "Use Render dashboard to update env vars"}


@app.get("/api/admin/env/group_ids")
def admin_env_group_ids(request: Request):
    require_admin(request)
    return {"GROUP_ID": os.getenv("GROUP_ID", ""), "CHANNEL_ID": os.getenv("CHANNEL_ID", "")}


@app.get("/api/admin/user/{user_id}/profile")
def admin_user_profile(user_id: int, request: Request):
    require_admin(request)
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute(f"SELECT * FROM users WHERE user_id={ph()}", (user_id,))
        user = cur.fetchone()
        if not user:
            return {"ok": False, "error": "User not found"}
        u = dict(user) if not isinstance(user, dict) else user
        cur.execute(f"SELECT COUNT(*) as cnt FROM user_tasks WHERE user_id={ph()} AND reward_claimed=1", (user_id,))
        tasks_claimed = val(cur.fetchone(), "cnt", 0)
        cur.execute(f"SELECT COUNT(*) as cnt FROM user_tasks WHERE user_id={ph()}", (user_id,))
        tasks_total = val(cur.fetchone(), "cnt", 0)
        cur.execute(f"SELECT COUNT(*) as cnt FROM referral_logs WHERE from_user={ph()} OR to_user={ph()}", (user_id, user_id))
        ref_count = val(cur.fetchone(), "cnt", 0)
        cur.execute(f"SELECT COUNT(*) as cnt FROM game_history WHERE user_id={ph()}", (user_id,))
        games_played = val(cur.fetchone(), "cnt", 0)
        cur.execute(f"SELECT COUNT(*) as cnt FROM game_history WHERE user_id={ph()} AND result='won'", (user_id,))
        games_won = val(cur.fetchone(), "cnt", 0)
        cur.execute(f"SELECT COALESCE(SUM(bet),0) as total FROM game_history WHERE user_id={ph()}", (user_id,))
        games_total_bet = float(val(cur.fetchone(), "total", 0) or 0)
        cur.execute(f"SELECT COALESCE(SUM(payout),0) as total FROM game_history WHERE user_id={ph()} AND result='won'", (user_id,))
        games_total_payout = float(val(cur.fetchone(), "total", 0) or 0)
        return {
            "ok": True,
            "user": u,
            "tasks_claimed": int(tasks_claimed or 0),
            "tasks_total": int(tasks_total or 0),
            "ref_count": int(ref_count or 0),
            "games_played": int(games_played or 0),
            "games_won": int(games_won or 0),
            "games_total_bet": round(games_total_bet, 2),
            "games_total_payout": round(games_total_payout, 2),
            "games_net": round(games_total_payout - games_total_bet, 2),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        safe_close(conn)


@app.get("/api/admin/user/{user_id}/tasks")
def admin_user_tasks(user_id: int, request: Request):
    require_admin(request)
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute(f"""SELECT t.id, t.title, t.description, t.reward, t.reward_type, t.is_mandatory, t.task_type, t.task_config,
            COALESCE(ut.status,'pending') as user_status, COALESCE(ut.reward_claimed,0) as reward_claimed, ut.verified_at
            FROM tasks t LEFT JOIN user_tasks ut ON t.id=ut.task_id AND ut.user_id={ph()}
            WHERE t.is_active=1 ORDER BY t.sort_order, t.id""", (user_id,))
        tasks = rows_as_dicts(cur.fetchall())
        cur.execute(f"SELECT COUNT(*) as cnt FROM users WHERE referred_by={ph()}", (user_id,))
        ref_count = val(cur.fetchone(), "cnt", 0) or 0
        for t in tasks:
            tt = val(t, "task_type", "join") or "join"
            if tt == "referral":
                cfg_str = val(t, "task_config", "") or ""
                try:
                    cfg = json.loads(cfg_str) if cfg_str else {}
                except Exception:
                    cfg = {}
                ref_target = int(cfg.get("ref_count", 0))
                min_dep = float(cfg.get("min_deposit", 0) or 0)
                if min_dep > 0:
                    cur.execute(
                        f"SELECT COUNT(*) as cnt FROM users WHERE referred_by={ph()} AND total_deposit>={ph()}",
                        (user_id, min_dep),
                    )
                    actual = val(cur.fetchone(), "cnt", 0) or 0
                else:
                    actual = ref_count
                t["referral_current"] = actual
                t["referral_target"] = ref_target
                if actual >= ref_target and t["user_status"] == "pending":
                    t["user_status"] = "ready"
        return tasks
    except Exception:
        return []
    finally:
        safe_close(conn)


@app.get("/api/admin/user/{user_id}/games")
def admin_user_games(user_id: int, request: Request):
    require_admin(request)
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute(f"SELECT * FROM game_history WHERE user_id={ph()} ORDER BY id DESC LIMIT 200", (user_id,))
        history = rows_as_dicts(cur.fetchall())
        cur.execute(f"SELECT game_type, COUNT(*) as plays, SUM(bet) as total_bet, SUM(CASE WHEN result='won' THEN payout ELSE 0 END) as total_payout FROM game_history WHERE user_id={ph()} GROUP BY game_type", (user_id,))
        breakdown = rows_as_dicts(cur.fetchall())
        return {"history": history, "breakdown": breakdown}
    except Exception:
        return {"history": [], "breakdown": []}
    finally:
        safe_close(conn)


@app.get("/api/admin/user/{user_id}/referrals")
def admin_user_referrals(user_id: int, request: Request):
    require_admin(request)
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute(f"SELECT user_id, username, balance, total_deposit, created_at FROM users WHERE referred_by={ph()}", (user_id,))
        referred = rows_as_dicts(cur.fetchall())
        cur.execute(f"SELECT SUM(bonus_amount) as total_earned FROM referral_logs WHERE from_user={ph()}", (user_id,))
        row = cur.fetchone()
        total_earned = float(val(row, "total_earned", 0) or 0)
        return {"referred": referred, "total_earned": round(total_earned, 2)}
    except Exception:
        return {"referred": [], "total_earned": 0}
    finally:
        safe_close(conn)


@app.get("/api/admin/logs")
def admin_logs(request: Request):
    require_admin(request)
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute("SELECT * FROM admin_logs ORDER BY id DESC LIMIT 100")
        return rows_as_dicts(cur.fetchall())
    except Exception:
        return []
    finally:
        safe_close(conn)


@app.get("/")
def root():
    from fastapi.responses import HTMLResponse
    with open("index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read(), headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"})


@app.get("/admin")
def admin_page():
    from fastapi.responses import HTMLResponse
    with open("admin.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read(), headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"})


@app.get("/health")
def health():
    from bot import get_bot_username
    return {
        "ok": True,
        "db": "POSTGRES" if USE_POSTGRES else "SQLITE",
        "mode": "WEBHOOK",
        "bot_username": get_bot_username(),
        "timer": "D:H:M:S live",
        "expiry": "auto balance zero",
        "tier_reset": "on tier change",
        "admin_auth": "enabled" if ADMIN_SECRET else "disabled",
    }


@app.get("/bot_info")
def bot_info():
    from bot import get_bot_username
    uname = get_bot_username()
    return {
        "bot_username": uname,
        "referral_example": f"https://t.me/{uname}?start=123456",
    }


@app.get("/api/admin/auth/check")
def admin_auth_check():
    return {"auth_required": bool(ADMIN_SECRET), "secret_length": len(ADMIN_SECRET)}


@app.get("/api/debug/tasks")
def debug_tasks():
    conn = get_conn()
    try:
        cur = cursor(conn)
        try:
            cur.execute("SELECT id, title, task_type, task_config, sort_order, is_active FROM tasks ORDER BY sort_order ASC, id ASC")
            tasks = rows_as_dicts(cur.fetchall())
        except Exception as e:
            return {"error": str(e)}
        return {"tasks": tasks, "count": len(tasks)}
    finally:
        safe_close(conn)


@app.get("/api/debug/seed-referrals")
def debug_seed_referrals():
    conn = get_conn()
    errors = []
    try:
        cur = cursor(conn)
        cur.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS task_type TEXT DEFAULT 'join'")
        cur.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS task_config TEXT DEFAULT ''")
        cur.execute("ALTER TABLE tasks ADD COLUMN IF NOT EXISTS sort_order INTEGER DEFAULT 0")
        conn.commit()
    except Exception as e:
        errors.append(f"migrate: {e}")

    conn2 = get_conn()
    try:
        cur = cursor(conn2)
        now = datetime.utcnow().isoformat()
        inserted = 0
        seed_tasks = [
            ("Refer 1 Friend", "Invite 1 friend to join any task group", 0.5, '{"ref_count":1}', 100),
            ("Refer 3 Friends", "Invite 3 friends to join any task groups", 1.5, '{"ref_count":3}', 101),
            ("Refer 5 Friends", "Invite 5 friends to join any task groups", 3.0, '{"ref_count":5}', 102),
            ("Super Recruiter", "Refer 5 friends who each deposit \u226520 USDT", 25.0, '{"ref_count":5,"min_deposit":20}', 103),
        ]
        for title, desc, reward, config, sort_o in seed_tasks:
            try:
                cur.execute(f"SELECT id FROM tasks WHERE title={ph()} LIMIT 1", (title,))
                if cur.fetchone():
                    continue
                cur.execute(
                    f"INSERT INTO tasks (title,description,group_link,group_id,group_username,reward,reward_type,is_active,is_mandatory,icon,task_type,task_config,sort_order,created_at) VALUES ({ph()},{ph()},'','','',{ph()},'withdrawable',1,0,'','referral',{ph()},{ph()},{ph()})",
                    (title, desc, reward, config, sort_o, now),
                )
                inserted += 1
            except Exception as e:
                errors.append(f"insert '{title}': {e}")
        conn2.commit()
        cur.execute("SELECT id, title, task_type, sort_order FROM tasks ORDER BY sort_order ASC, id ASC")
        tasks = rows_as_dicts(cur.fetchall())
        return {"ok": True, "inserted": inserted, "tasks": tasks, "errors": errors}
    except Exception as e:
        errors.append(f"outer: {e}")
        return {"ok": False, "errors": errors}
    finally:
        safe_close(conn)
        safe_close(conn2)


@app.get("/api/display/activity")
def display_activity():
    now = datetime.utcnow()
    seed_val = int(now.strftime("%Y%m%d"))
    rng = random.Random(seed_val)
    time_slot = now.minute // 5
    slot_seed = seed_val * 100 + time_slot
    rng2 = random.Random(slot_seed)
    usernames = ["Alex_M", "CryptoRaj", "TradeKing", "USDT_Pro", "BullRunner", "DiamondHands", "MoonShot99", "SatoshiJr", "DeFiQueen", "WhaleAlert", "CoinMaster", "AlphaTrades", "BTCLover", "GainzFactory", "PumpHunter", "YieldMax", "StakeBoss", "PortfolioX", "NetWorthUp", "FuturesKing"]
    deposit_amts = [20, 25, 30, 40, 50, 75, 100, 150, 200, 250, 300, 500]
    withdraw_amts = [10, 15, 20, 25, 30, 40, 50, 75, 100, 150]
    trade_profits = [0.5, 0.8, 1.2, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0, 8.0, 10.0]
    activities = []
    for i in range(8):
        mins_ago = rng2.randint(1, 4)
        if i > 0:
            mins_ago += i * rng2.randint(4, 9)
        t = now - timedelta(minutes=mins_ago)
        name = rng.choice(usernames) + str(rng.randint(10, 99))
        action_type = rng2.choice(["deposit", "withdraw", "deposit", "deposit", "deposit", "trade_win"])
        if action_type == "deposit":
            amt = rng2.choice(deposit_amts)
            net = rng2.choice(["BEP-20", "TRC-20"])
            activities.append({"user": name, "action": f"Deposited {amt} USDT", "network": net, "time": t.strftime("%H:%M IST"), "mins_ago": mins_ago, "type": "deposit"})
        elif action_type == "withdraw":
            amt = rng2.choice(withdraw_amts)
            activities.append({"user": name, "action": f"Withdrew {amt} USDT", "network": "BEP-20", "time": t.strftime("%H:%M IST"), "mins_ago": mins_ago, "type": "withdraw"})
        else:
            amt = rng2.choice(trade_profits)
            activities.append({"user": name, "action": f"AI trade profit +${amt:.2f}", "network": "", "time": t.strftime("%H:%M IST"), "mins_ago": mins_ago, "type": "trade"})
    activities.sort(key=lambda x: x["mins_ago"])
    return {"activities": activities}


try:
    import blockchain_monitor
    logger.info("Blockchain monitor loaded")
except Exception as e:
    logger.warning(f"Monitor load fail: {e}")
