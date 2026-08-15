"""PT_AI Trading API.

The API uses database.py for both PostgreSQL and SQLite so every route operates on
the same persistent store.
"""
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_DOWN
import hashlib
import json
import os
import random
import string
import urllib.request

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from database import USE_POSTGRES, SQLITE_PATH, get_conn, get_cursor, init_db, put_conn

app = FastAPI(title="PT_AI Trading")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])
init_db()

DEPOSIT_ADDR = {
    "TRC20": "TAFHf1pxsXRCSnhn8jRU5UcU4STK6u9tAC",
    "BEP20": "0xDD190484827BB976acEB975C94d5c58fc8c87Cfd",
    "ERC20": "0xDD190484827BB976acEB975C94d5c58fc8c87Cfd",
    "TON": "UQBlNeJ90El3LxBhikC2HUG3mqS16k1q177AjcNAaURVa_zw",
    "SOL": "87fwXKMuH8wyayeMJ74eRUq3knQ3UXmFQPj9g87A4se7",
}
TIERS = [(15000, 14.9), (6000, 13.6), (2500, 11.8), (1200, 10.9),
         (500, 9.6), (120, 8.9), (20, 7.6), (0, 0.0)]
REF_BONUS = {1: 7, **{level: 1 for level in range(2, 11)}}
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT",
           "AVAXUSDT", "LINKUSDT", "LTCUSDT", "ADAUSDT", "PEPEUSDT", "SHIBUSDT",
           "MATICUSDT", "DOTUSDT", "ARBUSDT"]
BASE_PRICES = {"BTCUSDT": 67200, "ETHUSDT": 3400, "SOLUSDT": 178, "BNBUSDT": 610,
               "XRPUSDT": .62, "DOGEUSDT": .16, "AVAXUSDT": 42, "LINKUSDT": 18.5,
               "LTCUSDT": 84, "ADAUSDT": .48, "PEPEUSDT": .000009, "SHIBUSDT": .000027,
               "MATICUSDT": .89, "DOTUSDT": 7.2, "ARBUSDT": 1.12}


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


def ph():
    return "%s" if USE_POSTGRES else "?"


def cursor(conn):
    return get_cursor(conn)


def val(row, key, default=None):
    if row is None:
        return default
    try:
        return row[key] if row[key] is not None else default
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
                f"INSERT INTO users (user_id,username,referred_by,created_at,last_claim,last_auto_claim,current_tier) "
                f"VALUES ({ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()})",
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
    """Accrue elapsed profit and perform the existing daily wallet transfer."""
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
            cur.execute(f"UPDATE users SET ai_start={ph()}, ai_end={ph()}, current_tier={ph()} WHERE user_id={ph()}",
                        (ai_start, ai_end, tier_index, user_id))
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
        cur.execute(f"UPDATE users SET profit={ph()}, profit_per_hour={ph()}, daily_percent={ph()}, last_claim={ph()} WHERE user_id={ph()}",
                    (profit, per_hour, daily_percent, now.isoformat(), user_id))
        last_auto = val(user, "last_auto_claim")
        try:
            due = not last_auto or (now - datetime.fromisoformat(last_auto)).total_seconds() >= 86400
        except (TypeError, ValueError):
            due = True
        if due and profit > .01:
            cur.execute(f"UPDATE users SET withdrawable=COALESCE(withdrawable,0)+{ph()}, profit=0, last_auto_claim={ph()} WHERE user_id={ph()}",
                        (profit, now.isoformat(), user_id))
        conn.commit()
        cur.execute(f"SELECT * FROM users WHERE user_id={ph()}", (user_id,))
        return cur.fetchone()
    finally:
        put_conn(conn)


def distribute_referral(depositor_id: int, amount: float):
    conn = get_conn()
    try:
        cur = cursor(conn)
        current = depositor_id
        now = datetime.utcnow().isoformat()
        for level in range(1, 11):
            cur.execute(f"SELECT referred_by FROM users WHERE user_id={ph()}", (current,))
            row = cur.fetchone()
            referrer = val(row, "referred_by")
            if not referrer:
                break
            bonus = round(amount * REF_BONUS[level] / 100, 8)
            cur.execute(f"UPDATE users SET withdrawable=COALESCE(withdrawable,0)+{ph()}, referral_earnings=COALESCE(referral_earnings,0)+{ph()} WHERE user_id={ph()}",
                        (bonus, bonus, referrer))
            cur.execute(f"INSERT INTO referral_logs (from_user,to_user,level,deposit_amount,bonus_amount,bonus_percent,created_at) VALUES ({ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()})",
                        (depositor_id, referrer, level, amount, bonus, REF_BONUS[level], now))
            current = referrer
        conn.commit()
    finally:
        put_conn(conn)


def process_invoice_payment(invoice: str, tx_hash: str, actual_amount: float):
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute(f"SELECT * FROM deposits WHERE invoice_id={ph()}", (invoice,))
        deposit = cur.fetchone()
        if not deposit or val(deposit, "status") != "awaiting_payment":
            return False, "Invoice is unavailable"
        try:
            if datetime.utcnow() > datetime.fromisoformat(val(deposit, "expires_at")):
                cur.execute(f"UPDATE deposits SET status='expired' WHERE invoice_id={ph()}", (invoice,))
                conn.commit(); return False, "Invoice expired"
        except (TypeError, ValueError):
            return False, "Invoice expiry is invalid"
        expected = float(val(deposit, "expected_amount", val(deposit, "amount", 0)) or 0)
        if actual_amount + 0.000001 < expected:
            return False, "Payment amount is below the invoice amount"
        if tx_hash:
            cur.execute(f"SELECT tx_hash FROM used_tx_hashes WHERE tx_hash={ph()}", (tx_hash,))
            if cur.fetchone():
                return False, "Transaction was already used"
            cur.execute(f"INSERT INTO used_tx_hashes (tx_hash,used_at) VALUES ({ph()},{ph()})", (tx_hash, datetime.utcnow().isoformat()))
        user_id = int(val(deposit, "user_id"))
        cur.execute(f"UPDATE deposits SET status='verified',actual_amount={ph()},tx_hash={ph()},verified_at={ph()} WHERE invoice_id={ph()}",
                    (actual_amount, tx_hash, datetime.utcnow().isoformat(), invoice))
        cur.execute(f"UPDATE users SET balance=COALESCE(balance,0)+{ph()},total_deposit=COALESCE(total_deposit,0)+{ph()} WHERE user_id={ph()}",
                    (actual_amount, actual_amount, user_id))
        conn.commit()
    finally:
        put_conn(conn)
    distribute_referral(user_id, actual_amount)
    recalc_profit(user_id)
    return True, "Payment verified"


def trc20_payment_for_invoice(deposit):
    if val(deposit, "network") != "TRC20":
        return None
    try:
        url = "https://apilist.tronscanapi.com/api/token_trc20/transfers?limit=50&sort=-timestamp&toAddress=" + DEPOSIT_ADDR["TRC20"] + "&contract_address=TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
        request = urllib.request.Request(url, headers={"User-Agent": "PT-AI-Trading"})
        with urllib.request.urlopen(request, timeout=10) as response:
            transfers = json.loads(response.read().decode()).get("token_transfers", [])
        expected = float(val(deposit, "expected_amount", 0) or 0)
        created = datetime.fromisoformat(val(deposit, "created_at"))
        for transfer in transfers:
            amount = float(transfer.get("quant", 0)) / (10 ** int(transfer.get("tokenInfo", {}).get("tokenDecimal", 6)))
            stamp = datetime.utcfromtimestamp(int(transfer.get("block_ts", 0)) / 1000)
            if amount + .000001 >= expected and stamp >= created - timedelta(minutes=2):
                return transfer.get("transaction_id"), amount
    except Exception:
        pass
    return None


def invoice_status(invoice: str):
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute(f"SELECT * FROM deposits WHERE invoice_id={ph()}", (invoice,))
        deposit = cur.fetchone()
        if not deposit:
            return None
        if val(deposit, "status") == "awaiting_payment":
            try:
                if datetime.utcnow() >= datetime.fromisoformat(val(deposit, "expires_at")):
                    cur.execute(f"UPDATE deposits SET status='expired' WHERE invoice_id={ph()}", (invoice,)); conn.commit()
                    cur.execute(f"SELECT * FROM deposits WHERE invoice_id={ph()}", (invoice,)); deposit = cur.fetchone()
            except (TypeError, ValueError):
                pass
        seconds = 0
        try: seconds = max(0, int((datetime.fromisoformat(val(deposit, "expires_at")) - datetime.utcnow()).total_seconds()))
        except (TypeError, ValueError): pass
        return {"invoice_id": invoice, "status": val(deposit, "status"), "amount": val(deposit, "amount", 0),
                "expected_amount": val(deposit, "expected_amount", val(deposit, "amount", 0)), "actual_amount": val(deposit, "actual_amount", 0),
                "network": val(deposit, "network"), "address": DEPOSIT_ADDR.get(val(deposit, "network"), ""), "tx_hash": val(deposit, "tx_hash", ""),
                "expires_at": val(deposit, "expires_at"), "time_left_seconds": seconds,
                "time_left_formatted": f"{seconds//60:02d}:{seconds%60:02d}"}
    finally:
        put_conn(conn)


@app.get("/api/user/{user_id}")
def api_user(user_id: int, ref: int | None = None, username: str | None = None):
    user_id = user_id or 123456789
    ensure_user(user_id, username or "", ref)
    user = recalc_profit(user_id)
    now = datetime.utcnow()
    ai_end = val(user, "ai_end")
    days_left = hours_left = 0; active = False
    try:
        remaining = datetime.fromisoformat(ai_end) - now
        active = remaining.total_seconds() > 0; days_left = max(0, remaining.days); hours_left = max(0, int(remaining.total_seconds() // 3600) % 24)
    except (TypeError, ValueError): pass
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute(f"SELECT COUNT(*) AS count FROM users WHERE referred_by={ph()}", (user_id,)); direct_count = val(cur.fetchone(), "count", 0)
        cur.execute(f"SELECT COALESCE(SUM(amount),0) AS total FROM withdrawals WHERE user_id={ph()} AND status='approved'", (user_id,)); total_withdraw = val(cur.fetchone(), "total", 0)
    finally: put_conn(conn)
    return {"user_id": user_id, "username": val(user,"username",f"user_{user_id}"), "balance": val(user,"balance",0), "withdrawable": val(user,"withdrawable",0),
            "profit": val(user,"profit",0), "profit_per_hour": val(user,"profit_per_hour",0), "daily_percent": val(user,"daily_percent",0),
            "ai_end": ai_end, "days_left": days_left, "hours_left": hours_left, "ai_active": active, "total_deposit": val(user,"total_deposit",0),
            "total_withdraw": total_withdraw, "tiers": [{"min": item[0], "pct": item[1]} for item in TIERS], "referral_earnings": val(user,"referral_earnings",0),
            "created_at": val(user,"created_at",now.isoformat()), "can_withdraw_today": val(user,"last_withdraw_date","") != now.date().isoformat(),
            "referred_by": val(user,"referred_by"), "direct_referrals": direct_count, "is_banned": val(user,"is_banned",0)}


@app.get("/api/referral/{user_id}")
def api_referral(user_id: int):
    ensure_user(user_id)
    conn = get_conn()
    try:
        cur = cursor(conn)
        cur.execute(f"SELECT user_id,username,balance,total_deposit FROM users WHERE referred_by={ph()}", (user_id,)); direct = rows_as_dicts(cur.fetchall())
        cur.execute(f"SELECT COALESCE(SUM(bonus_amount),0) AS total FROM referral_logs WHERE to_user={ph()}", (user_id,)); earned = val(cur.fetchone(),"total",0)
        cur.execute(f"SELECT from_user,level,deposit_amount,bonus_amount,bonus_percent,created_at FROM referral_logs WHERE to_user={ph()} ORDER BY id DESC LIMIT 20", (user_id,)); logs = rows_as_dicts(cur.fetchall())
        level_counts, seen, queue, team_deposit = {}, {user_id}, [(user_id, 0)], 0.0
        while queue:
            parent, level = queue.pop(0)
            if level >= 10: continue
            cur.execute(f"SELECT user_id,total_deposit FROM users WHERE referred_by={ph()}", (parent,))
            for child in cur.fetchall():
                child_id = val(child,"user_id")
                if child_id in seen: continue
                seen.add(child_id); next_level = level + 1; level_counts[next_level] = level_counts.get(next_level, 0) + 1
                team_deposit += float(val(child,"total_deposit",0) or 0); queue.append((child_id,next_level))
    finally: put_conn(conn)
    return {"ref_link": f"https://t.me/{os.getenv('BOT_USERNAME','YourBot')}?start={user_id}", "direct_count": len(direct), "direct_refs": [{"user_id":x["user_id"],"username":x.get("username"),"balance":x.get("balance",0),"deposit":x.get("total_deposit",0)} for x in direct],
            "level_counts":level_counts,"total_team_deposit":team_deposit,"total_earnings":earned,"bonus_structure":REF_BONUS,
            "logs":[{"from":x["from_user"],"level":x["level"],"deposit":x["deposit_amount"],"bonus":x["bonus_amount"],"percent":x["bonus_percent"],"at":x["created_at"]} for x in logs]}


@app.get("/api/deposit-addresses")
def deposit_addresses(): return DEPOSIT_ADDR


@app.post("/api/deposit/create_invoice/{user_id}")
def create_invoice(user_id: int, request: InvoiceRequest):
    ensure_user(user_id)
    network = request.network.upper()
    if request.amount < 20: return {"error":"Min deposit 20 USDT required"}
    if network not in DEPOSIT_ADDR: return {"error":"Unsupported network"}
    amount = float(Decimal(str(request.amount)).quantize(Decimal("0.000001"), rounding=ROUND_DOWN))
    conn = get_conn()
    try:
        cur = cursor(conn); now = datetime.utcnow(); expires = now + timedelta(minutes=15)
        cur.execute(f"SELECT invoice_id FROM deposits WHERE user_id={ph()} AND status='awaiting_payment' AND expires_at>{ph()} ORDER BY id DESC LIMIT 1", (user_id, now.isoformat()))
        existing = cur.fetchone()
        if existing: return {"ok":True,"invoice_id":val(existing,"invoice_id"),"existing":True}
        code = invoice_id()
        cur.execute(f"INSERT INTO deposits (user_id,amount,network,status,created_at,expires_at,invoice_id,expected_amount) VALUES ({ph()},{ph()},{ph()},'awaiting_payment',{ph()},{ph()},{ph()},{ph()})", (user_id,amount,network,now.isoformat(),expires.isoformat(),code,amount))
        conn.commit(); return {"ok":True,"invoice_id":code,"address":DEPOSIT_ADDR[network],"expected_amount":amount,"network":network,"expires_at":expires.isoformat()}
    finally: put_conn(conn)


@app.get("/api/deposit/invoice_status/{invoice}")
def get_invoice_status(invoice: str):
    status = invoice_status(invoice)
    return status or {"error":"Invoice not found"}


@app.post("/api/deposit/check_now/{invoice}")
def check_now(invoice: str):
    status = invoice_status(invoice)
    if not status: return {"ok":False,"error":"Invoice not found"}
    if status["status"] != "awaiting_payment": return {"ok": status["status"] == "verified", "status":status["status"], "amount":status["actual_amount"], "message":status["status"]}
    conn = get_conn()
    try:
        cur = cursor(conn); cur.execute(f"SELECT * FROM deposits WHERE invoice_id={ph()}",(invoice,)); deposit=cur.fetchone()
    finally: put_conn(conn)
    found = trc20_payment_for_invoice(deposit)
    if not found: return {"ok":False,"status":"awaiting_payment","message":"No matching on-chain payment found yet."}
    ok, message = process_invoice_payment(invoice, found[0], found[1])
    return {"ok":ok,"status":"verified" if ok else "awaiting_payment","amount":found[1],"message":message}


@app.post("/api/withdraw/request/{user_id}")
def request_withdrawal(user_id: int, request: WithdrawalRequest):
    if request.amount < 10: return {"error":"Min 10 USDT"}
    if request.network.upper() not in DEPOSIT_ADDR: return {"error":"Unsupported network"}
    user = recalc_profit(user_id)
    if val(user,"is_banned",0): return {"error":"Account suspended"}
    if float(val(user,"withdrawable",0) or 0) < request.amount: return {"error":"Insufficient withdrawable balance"}
    today = datetime.utcnow().date().isoformat(); conn=get_conn()
    try:
        cur=cursor(conn)
        if val(user,"last_withdraw_date","") == today: return {"error":"Only one withdrawal request is allowed per day"}
        cur.execute(f"UPDATE users SET withdrawable=withdrawable-{ph()},last_withdraw_date={ph()} WHERE user_id={ph()}",(request.amount,today,user_id))
        cur.execute(f"INSERT INTO withdrawals (user_id,amount,address,network,status,created_at) VALUES ({ph()},{ph()},{ph()},{ph()},'pending',{ph()})",(user_id,request.amount,request.address,request.network.upper(),datetime.utcnow().isoformat()))
        conn.commit(); return {"ok":True,"message":"Withdrawal request submitted for approval."}
    finally: put_conn(conn)


@app.get("/api/history/{user_id}")
def history(user_id: int):
    conn=get_conn()
    try:
        cur=cursor(conn); cur.execute(f"SELECT * FROM deposits WHERE user_id={ph()} ORDER BY id DESC LIMIT 50",(user_id,)); deposits=rows_as_dicts(cur.fetchall())
        cur.execute(f"SELECT * FROM withdrawals WHERE user_id={ph()} ORDER BY id DESC LIMIT 50",(user_id,)); withdrawals=rows_as_dicts(cur.fetchall())
        return {"deposits":deposits,"withdrawals":withdrawals}
    finally: put_conn(conn)


def generate_trades():
    today=datetime.utcnow().date().isoformat(); seed=int(hashlib.md5(today.encode()).hexdigest()[:8],16); rng=random.Random(seed); count=12+seed%4; pnls=[round((4.5+rng.random()*4)*(1 if i<int(count*.71) else -.25),2) for i in range(count)]
    trades=[]
    for i,pnl in enumerate(pnls):
        symbol=SYMBOLS[i%len(SYMBOLS)]; entry=BASE_PRICES[symbol]*(1+(rng.random()-.5)*.02); side=rng.choice(["LONG","SHORT"]); exit_price=entry*(1+(pnl/100 if side=="LONG" else -pnl/100)); amount=round(800+rng.random()*1200,2)
        trades.append({"id":i+1,"pair":symbol.replace("USDT","/USDT"),"symbol":symbol,"side":side,"leverage":rng.choice([5,10,15,20]),"usdt_amount":amount,"entry_price":round(entry,6 if entry<1 else 2),"exit_price":round(exit_price,6 if exit_price<1 else 2),"pnl_percent":pnl,"pnl_usdt":round(amount*pnl/100,2),"is_profit":pnl>0,"time":f"{6+i:02d}:{rng.randint(0,59):02d}","status":"CLOSED","date":today})
    return trades


@app.get("/api/binance/trades")
def binance_trades():
    trades=generate_trades(); prices=BASE_PRICES.copy(); source="fallback"
    try:
        request=urllib.request.Request("https://api.binance.com/api/v3/ticker/price",headers={"User-Agent":"PT-AI-Trading"})
        with urllib.request.urlopen(request,timeout=4) as response: prices.update({x["symbol"]:float(x["price"]) for x in json.loads(response.read().decode()) if x["symbol"] in SYMBOLS}); source="binance"
    except Exception: pass
    return {"trades":trades,"summary":{"total_trades":len(trades),"profit_trades":sum(t["is_profit"] for t in trades),"loss_trades":sum(not t["is_profit"] for t in trades),"total_pnl_percent":round(sum(t["pnl_percent"] for t in trades),2),"total_pnl_usdt":round(sum(t["pnl_usdt"] for t in trades),2),"funds_in_market":round(sum(t["usdt_amount"] for t in trades),2),"date":datetime.utcnow().date().isoformat()},"prices_source":source,"live_prices":prices}


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
        cur=cursor(conn);cur.execute("SELECT * FROM referral_logs ORDER BY id DESC LIMIT 200");return [{"from_user":x["from_user"],"to_user":x["to_user"],"level":x["level"],"deposit":x["deposit_amount"],"bonus":x["bonus_amount"],"percent":x["bonus_percent"]} for x in rows_as_dicts(cur.fetchall())]
    finally:put_conn(conn)


@app.get("/api/admin/users")
def admin_users():
    conn=get_conn()
    try:
        cur=cursor(conn);cur.execute("SELECT * FROM users ORDER BY created_at DESC");return [{**x,"ref_earn":x.get("referral_earnings",0)} for x in rows_as_dicts(cur.fetchall())]
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


@app.get("/")
def root(): return FileResponse("index.html")

@app.get("/admin")
def admin_page(): return FileResponse("admin.html")

@app.get("/health")
def health(): return {"ok":True,"db":"POSTGRES" if USE_POSTGRES else "SQLITE","path":None if USE_POSTGRES else SQLITE_PATH}
