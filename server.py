
from datetime import datetime, timedelta
import hashlib, json, os, random, string, urllib.request, urllib.parse
from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Optional, List

from database import USE_POSTGRES, get_conn, get_cursor, init_db, put_conn

app = FastAPI(title="PT_AI Trading ULTRA V5 - FINAL FIX")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
init_db()

try:
    import blockchain_monitor
    print("✅ Blockchain monitor loaded")
except Exception as e:
    print(f"⚠️ Monitor load fail: {e}")

DEPOSIT_ADDR = {
    "TRC20": "TAFHf1pxsXRCSnhn8jRU5UcU4STK6u9tAC",
    "BEP20": "0xDD190484827BB976acEB975C94d5c58fc8c87Cfd",
    "ERC20": "0xDD190484827BB976acEB975C94d5c58fc8c87Cfd",
    "TON": "UQBlNeJ90El3LxBhikC2HUG3mqS16k1q177AjcNAaURVa_zw",
    "SOL": "87fwXKMuH8wyayeMJ74eRUq3knQ3UXmFQPj9g87A4se7",
}
TIERS = [(15000, 14.9), (6000, 13.6), (2500, 11.8), (1200, 10.9), (500, 9.6), (120, 8.9), (20, 7.6), (0, 0.0)]
REF_BONUS = {1: 7, **{level: 1 for level in range(2, 11)}}
SYMBOLS = ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","DOGEUSDT","AVAXUSDT","LINKUSDT","LTCUSDT","ADAUSDT","PEPEUSDT","SHIBUSDT","MATICUSDT","DOTUSDT","ARBUSDT"]
BASE_PRICES = {"BTCUSDT":67200,"ETHUSDT":3400,"SOLUSDT":178,"BNBUSDT":610,"XRPUSDT":.62,"DOGEUSDT":.16,"AVAXUSDT":42,"LINKUSDT":18.5,"LTCUSDT":84,"ADAUSDT":.48,"PEPEUSDT":.000009,"SHIBUSDT":.000027,"MATICUSDT":.89,"DOTUSDT":7.2,"ARBUSDT":1.12}

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

class TaskCreate(BaseModel):
    title: str
    description: Optional[str] = ""
    group_link: str
    group_id: str
    group_username: Optional[str] = ""
    reward: float = 1.0
    reward_type: str = "withdrawable"
    is_active: int = 1
    is_mandatory: int = 1
    icon: str = "🚀"

class GroupBulkAdd(BaseModel):
    user_ids: List[str]
    group: str
    method: str = "direct"

def ph(): return "%s" if USE_POSTGRES else "?"
def cursor(conn): return get_cursor(conn)
def val(row,key,default=None):
    if row is None: return default
    try: return row[key] if row[key] is not None else default
    except: return default
def rows_as_dicts(rows): return [dict(r) for r in rows]
def get_tier(balance):
    for idx,(minimum,pct) in enumerate(TIERS):
        if balance>=minimum: return idx,minimum,pct
    return len(TIERS)-1,0,0
def invoice_id(): return "".join(random.choices(string.ascii_uppercase+string.digits,k=8))

def ensure_user(user_id:int, username:str="", referred_by=None):
    user_id=int(user_id or 123456789)
    if user_id<1: user_id=123456789
    conn=get_conn()
    try:
        cur=cursor(conn)
        cur.execute(f"SELECT * FROM users WHERE user_id={ph()}",(user_id,))
        row=cur.fetchone()
        now=datetime.utcnow().isoformat()
        if not row:
            ref=None
            try:
                cand=int(referred_by) if referred_by else None
                if cand and cand!=user_id:
                    cur.execute(f"SELECT user_id FROM users WHERE user_id={ph()}",(cand,))
                    ref=cand if cur.fetchone() else None
            except: pass
            cur.execute(f"INSERT INTO users (user_id,username,referred_by,created_at,last_claim,last_auto_claim,current_tier) VALUES ({ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()})",(user_id, username or f"user_{user_id}", ref, now, now, now, len(TIERS)-1))
            conn.commit()
        elif username and username!=val(row,"username",""):
            cur.execute(f"UPDATE users SET username={ph()} WHERE user_id={ph()}",(username,user_id)); conn.commit()
        cur.execute(f"SELECT * FROM users WHERE user_id={ph()}",(user_id,))
        return cur.fetchone()
    finally: put_conn(conn)

def recalc_profit(user_id:int):
    conn=get_conn()
    try:
        cur=cursor(conn)
        cur.execute(f"SELECT * FROM users WHERE user_id={ph()}",(user_id,))
        user=cur.fetchone()
        if not user: return None
        now=datetime.utcnow()
        balance=float(val(user,"balance",0) or 0)
        tier_index,_,daily_percent=get_tier(balance)
        ai_end_str=val(user,"ai_end")
        ai_start_str=val(user,"ai_start")
        current_tier=val(user,"current_tier",len(TIERS)-1)
        end_dt=None
        try:
            end_dt=datetime.fromisoformat(ai_end_str) if ai_end_str else None
        except: end_dt=None
        # Expiry check
        if end_dt and now>=end_dt and balance>0:
            expired_amount=balance
            cur.execute(f"UPDATE users SET balance=0, profit=0, ai_start=NULL, ai_end=NULL, current_tier={ph()}, profit_per_hour=0 WHERE user_id={ph()}",(len(TIERS)-1,user_id))
            try:
                cur.execute(f"INSERT INTO admin_logs (admin_action,target_user_id,details) VALUES ('ai_expired',{ph()},{ph()})",(user_id,f"Expired {expired_amount} USDT after 30d - {ai_end_str}"))
            except: pass
            conn.commit()
            cur.execute(f"SELECT * FROM users WHERE user_id={ph()}",(user_id,))
            user=cur.fetchone()
            balance=0
            tier_index,_,daily_percent=get_tier(0)
            end_dt=None
            ai_end_str=None
        # Start timer
        if balance>=20 and not ai_end_str:
            ai_start=now.isoformat()
            ai_end=(now+timedelta(days=30)).isoformat()
            cur.execute(f"UPDATE users SET ai_start={ph()}, ai_end={ph()}, current_tier={ph()} WHERE user_id={ph()}",(ai_start,ai_end,tier_index,user_id))
            ai_end_str=ai_end
            try: end_dt=datetime.fromisoformat(ai_end)
            except: end_dt=now+timedelta(days=30)
        # Tier change reset
        elif current_tier!=tier_index and balance>=20:
            ai_start=now.isoformat()
            ai_end=(now+timedelta(days=30)).isoformat()
            cur.execute(f"UPDATE users SET ai_start={ph()}, ai_end={ph()}, current_tier={ph()} WHERE user_id={ph()}",(ai_start,ai_end,tier_index,user_id))
            ai_end_str=ai_end
            try: end_dt=datetime.fromisoformat(ai_end)
            except: end_dt=now+timedelta(days=30)
            try:
                cur.execute(f"INSERT INTO admin_logs (admin_action,target_user_id,details) VALUES ('tier_change_reset',{ph()},{ph()})",(user_id,f"Tier {current_tier}->{tier_index}, timer reset to 30d"))
            except: pass
        elif current_tier!=tier_index:
            cur.execute(f"UPDATE users SET current_tier={ph()} WHERE user_id={ph()}",(tier_index,user_id))
        profit=float(val(user,"profit",0) or 0)
        per_hour=balance*daily_percent/2400 if balance>0 else 0
        last_claim=val(user,"last_claim")
        active=False
        try:
            active=bool(end_dt and now<end_dt and balance>=20)
            if active and last_claim:
                hours=max(0,(now-datetime.fromisoformat(last_claim)).total_seconds()/3600)
                profit+=hours*per_hour
        except: active=False
        cur.execute(f"UPDATE users SET profit={ph()}, profit_per_hour={ph()}, daily_percent={ph()}, last_claim={ph()} WHERE user_id={ph()}",(profit,per_hour,daily_percent,now.isoformat(),user_id))
        last_auto=val(user,"last_auto_claim")
        try:
            due=not last_auto or (now-datetime.fromisoformat(last_auto)).total_seconds()>=86400
        except: due=True
        if due and profit>.01 and active:
            cur.execute(f"UPDATE users SET withdrawable=COALESCE(withdrawable,0)+{ph()}, profit=0, last_auto_claim={ph()} WHERE user_id={ph()}",(profit,now.isoformat(),user_id))
        conn.commit()
        cur.execute(f"SELECT * FROM users WHERE user_id={ph()}",(user_id,))
        return cur.fetchone()
    finally: put_conn(conn)

def check_telegram_membership(bot_token, chat_id, user_id):
    try:
        url = f"https://api.telegram.org/bot{bot_token}/getChatMember?chat_id={urllib.parse.quote(str(chat_id))}&user_id={user_id}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=8) as r:
            data=json.loads(r.read().decode())
            if not data.get("ok"): return False, data
            status=data["result"]["status"]
            return status in ["member","administrator","creator","restricted"], data
    except Exception as e:
        return False, {"error": str(e)}

# WEBHOOK
@app.post("/webhook/{token}")
async def webhook_handler(token: str, request: Request):
    BOT_TOKEN_ENV = os.getenv("BOT_TOKEN","")
    if token != BOT_TOKEN_ENV:
        return {"ok": False, "error": "Invalid token"}
    try:
        data = await request.json()
        from telegram import Update
        from telegram.ext import Application, CommandHandler, CallbackQueryHandler
        from bot import BOT_TOKEN, start, callback_handler
        application = Application.builder().token(BOT_TOKEN).build()
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CallbackQueryHandler(callback_handler))
        async with application:
            update = Update.de_json(data, application.bot)
            await application.process_update(update)
        return {"ok": True}
    except Exception as e:
        print(f"Webhook error: {e}")
        import traceback; traceback.print_exc()
        return {"ok": False, "error": str(e)}

@app.get("/webhook/{token}")
def webhook_get(token: str):
    return {"ok": True, "message": "Webhook active"}

# CORE API
@app.get("/api/me/{user_id}")
def api_me(user_id:int, username: Optional[str] = Query(None), referred_by: Optional[str] = Query(None)):
    u=ensure_user(user_id, username or "", referred_by)
    u=recalc_profit(user_id)
    d=dict(u)
    tier_idx,_,pct=get_tier(float(d.get("balance",0)))
    conn=get_conn()
    try:
        cur=cursor(conn)
        cur.execute(f"SELECT COUNT(*) as cnt FROM tasks WHERE is_mandatory=1 AND is_active=1")
        mand_cnt=val(cur.fetchone(),"cnt",0) or 0
        cur.execute(f"SELECT COUNT(*) as cnt FROM user_tasks WHERE user_id={ph()} AND status='verified'",(user_id,))
        verified_cnt=val(cur.fetchone(),"cnt",0) or 0
        d["mandatory_tasks_total"]=mand_cnt
        d["mandatory_tasks_done"]=verified_cnt
        d["all_tasks_done"]= mand_cnt==0 or verified_cnt>=mand_cnt
    finally: put_conn(conn)
    d["tier"]=tier_idx
    d["daily_percent"]=pct
    d["is_banned"]=bool(d.get("is_banned",0))
    return d

@app.get("/api/user/{user_id}")
def api_user_alias(user_id:int, username: Optional[str] = Query(None), referred_by: Optional[str] = Query(None)):
    return api_me(user_id, username, referred_by)

@app.get("/api/deposit-addresses")
def deposit_addresses():
    return DEPOSIT_ADDR

@app.post("/api/deposit/invoice/{user_id}")
@app.post("/api/deposit/create_invoice/{user_id}")
def create_invoice(user_id:int, req:InvoiceRequest):
    ensure_user(user_id)
    conn=get_conn()
    try:
        cur=cursor(conn)
        inv=invoice_id()
        now=datetime.utcnow()
        exp=now+timedelta(minutes=15)
        if req.network not in DEPOSIT_ADDR: req.network="TRC20"
        cur.execute(f"INSERT INTO deposits (user_id,amount,network,status,created_at,expires_at,invoice_id,expected_amount) VALUES ({ph()},{ph()},{ph()},'awaiting_payment',{ph()},{ph()},{ph()},{ph()})",(user_id,req.amount,req.network,now.isoformat(),exp.isoformat(),inv,req.amount))
        conn.commit()
        addr=DEPOSIT_ADDR.get(req.network, DEPOSIT_ADDR["TRC20"])
        return {"invoice_id":inv,"address":addr,"amount":req.amount,"network":req.network,"expires_at":exp.isoformat(),"qr":addr,"expected_amount":req.amount}
    finally: put_conn(conn)

@app.get("/api/deposit/invoice_status/{invoice_id}")
def invoice_status(invoice_id:str):
    conn=get_conn()
    try:
        cur=cursor(conn); cur.execute(f"SELECT * FROM deposits WHERE invoice_id={ph()}",(invoice_id,)); d=cur.fetchone()
        if not d: return {"error":"not found"}
        return dict(d)
    finally: put_conn(conn)

@app.post("/api/withdraw/{user_id}")
@app.post("/api/withdraw/request/{user_id}")
def withdraw(user_id:int, req:WithdrawalRequest):
    u=ensure_user(user_id); u=recalc_profit(user_id)
    if float(val(u,"withdrawable",0) or 0) < req.amount: return {"ok":False,"error":"Insufficient withdrawable balance"}
    conn=get_conn()
    try:
        cur=cursor(conn)
        cur.execute(f"SELECT COUNT(*) as cnt FROM tasks WHERE is_mandatory=1 AND is_active=1")
        mand=val(cur.fetchone(),"cnt",0) or 0
        if mand>0:
            cur.execute(f"SELECT COUNT(*) as cnt FROM user_tasks WHERE user_id={ph()} AND status='verified'",(user_id,))
            done=val(cur.fetchone(),"cnt",0) or 0
            if done<mand:
                return {"ok":False,"error":f"Complete {mand} mandatory join tasks first! Go to Tasks tab"}
        cur.execute(f"UPDATE users SET withdrawable=COALESCE(withdrawable,0)-{ph()} WHERE user_id={ph()}",(req.amount,user_id))
        cur.execute(f"INSERT INTO withdrawals (user_id,amount,address,network,status,created_at) VALUES ({ph()},{ph()},{ph()},{ph()},'pending',{ph()})",(user_id,req.amount,req.address,req.network,datetime.utcnow().isoformat()))
        conn.commit()
        return {"ok":True,"message":"Withdrawal requested"}
    finally: put_conn(conn)

@app.get("/api/history/{user_id}")
def history(user_id:int):
    conn=get_conn()
    try:
        cur=cursor(conn)
        cur.execute(f"SELECT * FROM deposits WHERE user_id={ph()} ORDER BY id DESC LIMIT 100",(user_id,)); deps=rows_as_dicts(cur.fetchall())
        cur.execute(f"SELECT * FROM withdrawals WHERE user_id={ph()} ORDER BY id DESC LIMIT 100",(user_id,)); wds=rows_as_dicts(cur.fetchall())
        return {"deposits":deps,"withdrawals":wds}
    finally: put_conn(conn)

@app.get("/api/referral/{user_id}")
def referral(user_id:int):
    conn=get_conn()
    try:
        cur=cursor(conn)
        bot_name=os.getenv("BOT_USERNAME","PT_Minebot")
        cur.execute(f"SELECT user_id,username,balance,total_deposit FROM users WHERE referred_by={ph()} ORDER BY created_at DESC",(user_id,)); direct=rows_as_dicts(cur.fetchall())
        cur.execute(f"SELECT SUM(bonus_amount) as total FROM referral_logs WHERE to_user={ph()}",(user_id,)); tot=cur.fetchone()
        try:
            cur.execute(f"SELECT COALESCE(SUM(total_deposit),0) as td FROM users WHERE referred_by={ph()}",(user_id,))
            team_dep=val(cur.fetchone(),"td",0)
        except: team_dep=0
        cur.execute(f"SELECT * FROM referral_logs WHERE to_user={ph()} ORDER BY id DESC LIMIT 100",(user_id,)); logs=rows_as_dicts(cur.fetchall())
        return {"ref_link":f"https://t.me/{bot_name}?start={user_id}","direct_count":len(direct),"total_earnings":val(tot,"total",0) or 0,"total_team_deposit":team_dep or 0,"direct_refs":[{"user_id":r["user_id"],"username":r.get("username"),"balance":r.get("balance",0),"deposit":r.get("total_deposit",0)} for r in direct],"logs":[{"from":l["from_user"],"level":l["level"],"deposit":l["deposit_amount"],"bonus":l["bonus_amount"],"percent":l["bonus_percent"],"at":l["created_at"]} for l in logs]}
    finally: put_conn(conn)

@app.get("/api/tasks/list/{user_id}")
def tasks_list(user_id:int):
    conn=get_conn()
    try:
        cur=cursor(conn)
        cur.execute(f"SELECT * FROM tasks WHERE is_active=1 ORDER BY sort_order ASC, id ASC")
        tasks=rows_as_dicts(cur.fetchall())
        cur.execute(f"SELECT task_id,status,reward_claimed FROM user_tasks WHERE user_id={ph()}",(user_id,))
        ut={r["task_id"]: r for r in rows_as_dicts(cur.fetchall())}
        out=[]
        for t in tasks:
            s=ut.get(t["id"])
            out.append({**t, "user_status": s["status"] if s else "pending", "reward_claimed": s["reward_claimed"] if s else 0})
        return out
    finally: put_conn(conn)

@app.post("/api/tasks/verify/{user_id}/{task_id}")
def tasks_verify(user_id:int, task_id:int):
    conn=get_conn()
    try:
        cur=cursor(conn)
        cur.execute(f"SELECT * FROM tasks WHERE id={ph()}",(task_id,))
        task=cur.fetchone()
        if not task: return {"ok":False,"error":"Task not found"}
        bot_token=os.getenv("BOT_TOKEN","")
        if not bot_token: return {"ok":False,"error":"BOT_TOKEN not set in server env"}
        chat_id=val(task,"group_id")
        is_member, details = check_telegram_membership(bot_token, chat_id, user_id)
        if not is_member:
            return {"ok":False,"error":"Not joined yet. Please JOIN the group/channel first, then click Verify","details":details}
        cur.execute(f"SELECT * FROM user_tasks WHERE user_id={ph()} AND task_id={ph()}",(user_id,task_id))
        existing=cur.fetchone()
        now=datetime.utcnow().isoformat()
        if existing:
            cur.execute(f"UPDATE user_tasks SET status='verified', verified_at={ph()} WHERE user_id={ph()} AND task_id={ph()}",(now,user_id,task_id))
        else:
            cur.execute(f"INSERT INTO user_tasks (user_id,task_id,status,verified_at,reward_claimed) VALUES ({ph()},{ph()},'verified',{ph()},0)",(user_id,task_id,now))
        reward=float(val(task,"reward",1.0) or 1.0)
        cur.execute(f"SELECT reward_claimed FROM user_tasks WHERE user_id={ph()} AND task_id={ph()}",(user_id,task_id))
        rw=cur.fetchone()
        if not val(rw,"reward_claimed",0):
            rtype=val(task,"reward_type","withdrawable")
            if rtype=="withdrawable":
                cur.execute(f"UPDATE users SET withdrawable=COALESCE(withdrawable,0)+{ph()} WHERE user_id={ph()}",(reward,user_id))
            else:
                cur.execute(f"UPDATE users SET balance=COALESCE(balance,0)+{ph()} WHERE user_id={ph()}",(reward,user_id))
            cur.execute(f"UPDATE user_tasks SET reward_claimed=1 WHERE user_id={ph()} AND task_id={ph()}",(user_id,task_id))
        conn.commit()
        return {"ok":True,"reward":reward,"message":f"✅ Verified! +{reward} USDT added to withdrawable balance"}
    except Exception as e:
        import traceback; traceback.print_exc()
        return {"ok":False,"error":str(e)}
    finally: put_conn(conn)

@app.post("/api/tasks/join/{user_id}/{task_id}")
def tasks_join_click(user_id:int, task_id:int):
    conn=get_conn()
    try:
        cur=cursor(conn)
        cur.execute(f"SELECT * FROM tasks WHERE id={ph()}",(task_id,))
        if not cur.fetchone(): return {"ok":False}
        try:
            if USE_POSTGRES:
                cur.execute(f"INSERT INTO user_tasks (user_id,task_id,status) VALUES ({ph()},{ph()},'joined') ON CONFLICT (user_id,task_id) DO NOTHING",(user_id,task_id))
            else:
                cur.execute(f"INSERT OR IGNORE INTO user_tasks (user_id,task_id,status) VALUES ({ph()},{ph()},'joined')",(user_id,task_id))
            conn.commit()
        except: conn.commit()
        return {"ok":True}
    finally: put_conn(conn)

@app.get("/api/binance/trades")
def binance_trades():
    import random, hashlib
    from datetime import datetime, timedelta, timezone
    utc_now = datetime.now(timezone.utc)
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
        exitp = entry * (1 + pnl/100) if side == "LONG" else entry * (1 - pnl/100)
        amount = round(rng.uniform(300, 1800), 2)
        trades_all.append({
            "id": i+1,
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
            "date": today_str
        })
    current_minutes = ist_now.hour * 60 + ist_now.minute
    visible_trades = [t for t in trades_all if t["minutes"] <= current_minutes]
    for t in visible_trades: t.pop("minutes", None)
    for t in trades_all: t.pop("minutes", None)
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
            "funds_in_market": round(sum(t["usdt_amount"] for t in visible_trades), 2),
            "date": today_str,
            "current_ist": ist_now.strftime("%H:%M IST"),
            "win_rate": round((profit_count / len(visible_trades) * 100) if visible_trades else 0, 1),
            "next_trade_in": f"{trades_all[len(visible_trades)]['time'] if len(visible_trades) < len(trades_all) else 'Tomorrow 00:30'} IST" if len(visible_trades) < len(trades_all) else "All trades done for today"
        },
        "prices_source": "deterministic_daily",
        "live_prices": prices
    }

@app.get("/api/admin/stats")
def admin_stats():
    conn=get_conn()
    try:
        cur=cursor(conn)
        cur.execute("SELECT COUNT(*) AS users, COALESCE(SUM(balance),0) AS balance, COALESCE(SUM(withdrawable),0) AS wd, COALESCE(SUM(total_deposit),0) AS tdep FROM users")
        stats=cur.fetchone()
        try:
            cur.execute("SELECT COUNT(*) as total FROM deposits WHERE status='awaiting_payment'"); pending_cnt=val(cur.fetchone(),"total",0)
        except: pending_cnt=0
        try:
            cur.execute("SELECT COUNT(*) as total FROM deposits WHERE status='verified'"); verified_cnt=val(cur.fetchone(),"total",0)
        except: verified_cnt=0
        try:
            cur.execute("SELECT COUNT(*) as total FROM deposits WHERE status='expired'"); expired_cnt=val(cur.fetchone(),"total",0)
        except: expired_cnt=0
        try:
            cur.execute("SELECT COALESCE(SUM(actual_amount),0) as s FROM deposits WHERE status='verified'"); verified_sum=val(cur.fetchone(),"s",0)
        except: verified_sum=0
        cur.execute("SELECT COUNT(*) AS pending FROM withdrawals WHERE status='pending'"); wd=cur.fetchone()
        cur.execute("SELECT COALESCE(SUM(bonus_amount),0) AS paid FROM referral_logs"); ref=cur.fetchone()
        cur.execute("SELECT COUNT(*) AS tasks FROM tasks WHERE is_active=1"); tc=cur.fetchone()
        cur.execute("SELECT COUNT(*) AS completed FROM user_tasks WHERE status='verified'"); comp=cur.fetchone()
        return {"total_users":val(stats,"users",0),"total_balance":val(stats,"balance",0),"total_withdrawable":val(stats,"wd",0),"total_deposits_all":val(stats,"tdep",0),"total_verified_deposits":verified_sum,"pending_deposits":pending_cnt,"verified_deposits":verified_cnt,"expired_deposits":expired_cnt,"pending_withdrawals":val(wd,"pending",0),"total_ref_paid":val(ref,"paid",0),"active_tasks":val(tc,"tasks",0),"completed_tasks":val(comp,"completed",0)}
    finally: put_conn(conn)

@app.get("/api/admin/deposits")
def admin_deposits():
    conn=get_conn()
    try:
        cur=cursor(conn); cur.execute("SELECT * FROM deposits ORDER BY id DESC LIMIT 500"); return [{**x,"expected":x.get("expected_amount",x.get("amount",0))} for x in rows_as_dicts(cur.fetchall())]
    finally: put_conn(conn)

@app.get("/api/admin/withdrawals")
def admin_withdrawals():
    conn=get_conn()
    try:
        cur=cursor(conn); cur.execute("SELECT * FROM withdrawals ORDER BY id DESC LIMIT 500"); return rows_as_dicts(cur.fetchall())
    finally: put_conn(conn)

@app.get("/api/admin/referrals")
def admin_referrals():
    conn=get_conn()
    try:
        cur=cursor(conn); cur.execute("SELECT * FROM referral_logs ORDER BY id DESC LIMIT 500"); return [{"from_user":x["from_user"],"to_user":x["to_user"],"level":x["level"],"deposit":x["deposit_amount"],"bonus":x["bonus_amount"],"percent":x["bonus_percent"]} for x in rows_as_dicts(cur.fetchall())]
    finally: put_conn(conn)

@app.get("/api/admin/users")
def admin_users():
    conn=get_conn()
    try:
        cur=cursor(conn); cur.execute("SELECT * FROM users ORDER BY created_at DESC"); return [{**x,"ref_earn":x.get("referral_earnings",0)} for x in rows_as_dicts(cur.fetchall())]
    finally: put_conn(conn)

@app.get("/api/admin/tasks")
def admin_tasks_list():
    conn=get_conn()
    try:
        cur=cursor(conn); cur.execute("SELECT * FROM tasks ORDER BY sort_order ASC, id DESC"); return rows_as_dicts(cur.fetchall())
    finally: put_conn(conn)

@app.post("/api/admin/tasks/create")
def admin_tasks_create(t: TaskCreate):
    conn=get_conn()
    try:
        cur=cursor(conn)
        cur.execute(f"INSERT INTO tasks (title,description,group_link,group_id,group_username,reward,reward_type,is_active,is_mandatory,icon,created_at) VALUES ({ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()})",(t.title,t.description,t.group_link,t.group_id,t.group_username,t.reward,t.reward_type,t.is_active,t.is_mandatory,t.icon,datetime.utcnow().isoformat()))
        conn.commit()
        return {"ok":True}
    finally: put_conn(conn)

@app.post("/api/admin/tasks/action")
def admin_tasks_action(a: IdAction):
    conn=get_conn()
    try:
        cur=cursor(conn)
        if a.action=="delete":
            cur.execute(f"DELETE FROM tasks WHERE id={ph()}",(a.id,))
        elif a.action=="toggle_active":
            cur.execute(f"UPDATE tasks SET is_active = CASE WHEN is_active=1 THEN 0 ELSE 1 END WHERE id={ph()}",(a.id,))
        elif a.action=="toggle_mandatory":
            cur.execute(f"UPDATE tasks SET is_mandatory = CASE WHEN is_mandatory=1 THEN 0 ELSE 1 END WHERE id={ph()}",(a.id,))
        conn.commit()
        return {"ok":True}
    finally: put_conn(conn)

@app.post("/api/admin/deposit/action")
def admin_deposit_action(action: IdAction):
    conn=get_conn()
    try:
        cur=cursor(conn)
        cur.execute(f"SELECT * FROM deposits WHERE id={ph()}",(action.id,))
        dep=cur.fetchone()
        if not dep: return {"ok":False,"error":"Deposit not found"}
        if action.action=="approve":
            from database import get_conn as gc
            # manual approve
            now=datetime.utcnow().isoformat()
            amt=float(val(dep,"expected_amount",0) or val(dep,"amount",0))
            cur.execute(f"UPDATE deposits SET status='verified', actual_amount={ph()}, verified_at={ph()} WHERE id={ph()}",(amt,now,action.id))
            cur.execute(f"SELECT * FROM users WHERE user_id={ph()}",(val(dep,"user_id"),))
            user=cur.fetchone()
            if user:
                new_bal=float(val(user,"balance",0) or 0)+amt
                new_total=float(val(user,"total_deposit",0) or 0)+amt
                tier_idx,_,_=get_tier(new_bal)
                ai_end=(datetime.utcnow()+timedelta(days=30)).isoformat()
                cur.execute(f"UPDATE users SET balance={ph()}, total_deposit={ph()}, current_tier={ph()}, ai_start={ph()}, ai_end={ph()} WHERE user_id={ph()}",(new_bal,new_total,tier_idx,now,ai_end,val(dep,"user_id")))
            conn.commit()
            return {"ok":True}
        elif action.action=="reject":
            cur.execute(f"UPDATE deposits SET status='rejected', admin_note={ph()} WHERE id={ph()}",(action.note or "Rejected", action.id)); conn.commit(); return {"ok":True}
        elif action.action=="delete":
            cur.execute(f"DELETE FROM deposits WHERE id={ph()}",(action.id,)); conn.commit(); return {"ok":True}
        else: return {"ok":False,"error":"Unsupported"}
    finally: put_conn(conn)

@app.post("/api/admin/withdraw/action")
def admin_withdraw_action(action: IdAction):
    conn=get_conn()
    try:
        cur=cursor(conn)
        cur.execute(f"SELECT * FROM withdrawals WHERE id={ph()}",(action.id,))
        wd=cur.fetchone()
        if not wd: return {"ok":False,"error":"Not found"}
        if action.action=="approve":
            cur.execute(f"UPDATE withdrawals SET status='approved', auto_approved=1 WHERE id={ph()}",(action.id,))
            cur.execute(f"UPDATE users SET total_withdraw=COALESCE(total_withdraw,0)+{ph()} WHERE user_id={ph()}",(val(wd,"amount",0), val(wd,"user_id")))
        elif action.action=="reject":
            cur.execute(f"UPDATE withdrawals SET status='rejected' WHERE id={ph()}",(action.id,))
            cur.execute(f"UPDATE users SET withdrawable=COALESCE(withdrawable,0)+{ph()} WHERE user_id={ph()}",(val(wd,"amount",0), val(wd,"user_id")))
        elif action.action=="delete":
            if val(wd,"status")=="pending":
                cur.execute(f"UPDATE users SET withdrawable=COALESCE(withdrawable,0)+{ph()} WHERE user_id={ph()}",(val(wd,"amount",0), val(wd,"user_id")))
            cur.execute(f"DELETE FROM withdrawals WHERE id={ph()}",(action.id,))
        conn.commit()
        return {"ok":True}
    finally: put_conn(conn)

@app.post("/api/admin/user/action")
def admin_user_action(action: AdminAction):
    conn=get_conn()
    try:
        cur=cursor(conn)
        act=action.action
        cur.execute(f"SELECT * FROM users WHERE user_id={ph()}",(action.user_id,))
        u=cur.fetchone()
        if not u and act!="delete": return {"ok":False,"error":"User not found"}
        amt=float(action.amount or 0)
        if act=="add_balance":
            cur.execute(f"UPDATE users SET balance=COALESCE(balance,0)+{ph()} WHERE user_id={ph()}",(amt,action.user_id))
        elif act=="deduct_balance":
            cur.execute(f"UPDATE users SET balance=GREATEST(0,COALESCE(balance,0)-{ph()}) WHERE user_id={ph()}",(amt,action.user_id))
        elif act=="set_balance":
            cur.execute(f"UPDATE users SET balance={ph()} WHERE user_id={ph()}",(amt,action.user_id))
        elif act=="add_withdrawable":
            cur.execute(f"UPDATE users SET withdrawable=COALESCE(withdrawable,0)+{ph()} WHERE user_id={ph()}",(amt,action.user_id))
        elif act=="set_withdrawable":
            cur.execute(f"UPDATE users SET withdrawable={ph()} WHERE user_id={ph()}",(amt,action.user_id))
        elif act=="ban":
            cur.execute(f"UPDATE users SET is_banned=1 WHERE user_id={ph()}",(action.user_id,))
        elif act=="unban":
            cur.execute(f"UPDATE users SET is_banned=0 WHERE user_id={ph()}",(action.user_id,))
        elif act=="expire_now":
            cur.execute(f"UPDATE users SET balance=0, profit=0, ai_start=NULL, ai_end=NULL, current_tier={ph()} WHERE user_id={ph()}",(len(TIERS)-1,action.user_id))
        elif act=="reset_timer":
            now=datetime.utcnow()
            ai_end=(now+timedelta(days=30)).isoformat()
            cur.execute(f"UPDATE users SET ai_start={ph()}, ai_end={ph()} WHERE user_id={ph()}",(now.isoformat(),ai_end,action.user_id))
        elif act=="delete":
            cur.execute(f"DELETE FROM users WHERE user_id={ph()}",(action.user_id,))
        conn.commit()
        return {"ok":True}
    finally: put_conn(conn)

@app.get("/")
def root():
    return FileResponse("index.html")

@app.get("/admin")
def admin_page():
    return FileResponse("admin.html")

@app.get("/health")
def health():
    return {"ok":True,"db":"POSTGRES" if USE_POSTGRES else "SQLITE","mode":"WEBHOOK","timer":"D:H:M:S live","expiry":"auto balance zero","tier_reset":"on tier change"}

@app.get("/api/admin/logs")
def admin_logs():
    conn=get_conn()
    try:
        cur=cursor(conn); cur.execute("SELECT * FROM admin_logs ORDER BY id DESC LIMIT 100"); return rows_as_dicts(cur.fetchall())
    finally: put_conn(conn)
