
import os, hashlib, hmac, json, random, string, urllib.parse, urllib.request
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import FastAPI, Query, Request, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from database import USE_POSTGRES, get_conn, get_cursor, init_db, put_conn

WEBAPP_URL = os.getenv("WEBAPP_URL", "https://pt-ai-trading.onrender.com")
BOT_USERNAME = os.getenv("BOT_USERNAME", "YourBot")
ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

DEPOSIT_ADDR = {
    "TRC20": os.getenv("DEPOSIT_ADDR_TRC20", "TAFHf1pxsXRCSnhn8jRU5UcU4STK6u9tAC"),
    "BEP20": os.getenv("DEPOSIT_ADDR_BEP20", "0xDD190484827BB976acEB975C94d5c58fc8c87Cfd"),
    "ERC20": os.getenv("DEPOSIT_ADDR_ERC20", "0xDD190484827BB976acEB975C94d5c58fc8c87Cfd"),
    "TON": os.getenv("DEPOSIT_ADDR_TON", "UQBlNeJ90El3LxBhikC2HUG3mqS16k1q177AjcNAaURVa_zw"),
    "SOL": os.getenv("DEPOSIT_ADDR_SOL", "87fwXKMuH8wyayeMJ74eRUq3knQ3UXmFQPj9g87A4se7"),
}

TIERS = [(15000, 14.9), (6000, 13.6), (2500, 11.8), (1200, 10.9), (500, 9.6), (120, 8.9), (20, 7.6), (0, 0.0)]
REF_BONUS = {1: 7, **{level: 1 for level in range(2, 11)}}
SYMBOLS = ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","DOGEUSDT","AVAXUSDT","LINKUSDT","LTCUSDT","ADAUSDT","PEPEUSDT","SHIBUSDT","MATICUSDT","DOTUSDT","ARBUSDT"]
BASE_PRICES = {"BTCUSDT":67200,"ETHUSDT":3400,"SOLUSDT":178,"BNBUSDT":610,"XRPUSDT":.62,"DOGEUSDT":.16,"AVAXUSDT":42,"LINKUSDT":18.5,"LTCUSDT":84,"ADAUSDT":.48,"PEPEUSDT":.000009,"SHIBUSDT":.000027,"MATICUSDT":.89,"DOTUSDT":7.2,"ARBUSDT":1.12}

app = FastAPI(title="PT_AI Trading ULTRA V7")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])

init_db()

try:
    import blockchain_monitor
    print("✅ Blockchain monitor loaded")
except Exception as e:
    print(f"⚠️ Monitor: {e}")

class InvoiceRequest(BaseModel):
    amount: float = Field(gt=0, le=100000)
    network: str = "TRC20"

class WithdrawalRequest(BaseModel):
    amount: float = Field(gt=0, le=100000)
    address: str = Field(min_length=10, max_length=200)
    network: str

class AdminAction(BaseModel):
    user_id: int
    action: str
    amount: float = 0
    note: Optional[str] = None

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
    sort_order: int = 0

class BulkAction(BaseModel):
    user_ids: List[int]
    action: str
    amount: float = 0

def ph(): return "%s" if USE_POSTGRES else "?"
def cursor(conn): return get_cursor(conn)
def val(row,key,default=None):
    if row is None: return default
    try:
        v = row[key] if isinstance(row, dict) else row[key]
        return v if v is not None else default
    except:
        try: return row.get(key, default) if isinstance(row, dict) else default
        except: return default
def rows_as_dicts(rows): return [dict(r) for r in rows]
def get_tier(balance):
    for idx,(minimum,pct) in enumerate(TIERS):
        if balance>=minimum: return idx,minimum,pct
    return len(TIERS)-1,0,0
def invoice_id(): return "".join(random.choices(string.ascii_uppercase+string.digits,k=10))

def verify_admin(x_admin_secret: str = Header(None)):
    if not ADMIN_SECRET:
        print("⚠️ ADMIN_SECRET not set")
        return True
    if x_admin_secret != ADMIN_SECRET:
        raise HTTPException(401, "Invalid X-Admin-Secret")
    return True

def ensure_user(user_id:int, username:str="", referred_by=None):
    user_id=int(user_id or 0)
    if user_id<1: raise HTTPException(400, "Invalid user_id")
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

def process_invoice_payment(invoice_id_str: str, tx_hash: str, actual_amount: float):
    conn=get_conn()
    try:
        cur=cursor(conn)
        cur.execute(f"SELECT tx_hash FROM used_tx_hashes WHERE tx_hash={ph()}",(tx_hash,))
        if cur.fetchone(): return False, "tx already used"
        cur.execute(f"SELECT * FROM deposits WHERE invoice_id={ph()}",(invoice_id_str,))
        dep=cur.fetchone()
        if not dep: return False, "invoice not found"
        if val(dep,"status")=="verified": return False, "already verified"
        now=datetime.utcnow().isoformat()
        amt=float(actual_amount)
        expected=float(val(dep,"expected_amount",0) or val(dep,"amount",0) or amt)
        if amt < expected*0.9: return False, f"amount too low {amt} < {expected}"
        cur.execute(f"UPDATE deposits SET status='verified', actual_amount={ph()}, tx_hash={ph()}, verified_at={ph()} WHERE invoice_id={ph()}",(amt, tx_hash, now, invoice_id_str))
        cur.execute(f"INSERT INTO used_tx_hashes (tx_hash, used_at) VALUES ({ph()},{ph()})",(tx_hash, now))
        user_id=val(dep,"user_id")
        cur.execute(f"SELECT * FROM users WHERE user_id={ph()}",(user_id,))
        user=cur.fetchone()
        if user:
            new_bal=float(val(user,"balance",0) or 0)+amt
            new_total=float(val(user,"total_deposit",0) or 0)+amt
            tier_idx,_,_=get_tier(new_bal)
            ai_end=(datetime.utcnow()+timedelta(days=30)).isoformat()
            cur.execute(f"UPDATE users SET balance={ph()}, total_deposit={ph()}, current_tier={ph()}, ai_start={ph()}, ai_end={ph()} WHERE user_id={ph()}",(new_bal,new_total,tier_idx,now,ai_end,user_id))
            try:
                referred_by=val(user,"referred_by")
                level=1
                current_ref=referred_by
                while current_ref and level<=10:
                    cur.execute(f"SELECT * FROM users WHERE user_id={ph()}",(current_ref,))
                    ref_user=cur.fetchone()
                    if not ref_user: break
                    bonus_pct=REF_BONUS.get(level,1)
                    bonus=amt*bonus_pct/100
                    cur.execute(f"UPDATE users SET withdrawable=COALESCE(withdrawable,0)+{ph()}, referral_earnings=COALESCE(referral_earnings,0)+{ph()} WHERE user_id={ph()}",(bonus,bonus,current_ref))
                    cur.execute(f"INSERT INTO referral_logs (from_user,to_user,level,deposit_amount,bonus_amount,bonus_percent,created_at) VALUES ({ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()})",(user_id,current_ref,level,amt,bonus,bonus_pct,now))
                    cur.execute(f"SELECT referred_by FROM users WHERE user_id={ph()}",(current_ref,))
                    nxt=cur.fetchone()
                    current_ref=val(nxt,"referred_by") if nxt else None
                    level+=1
            except Exception as e:
                print(f"Referral error: {e}")
        conn.commit()
        return True, "verified"
    except Exception as e:
        import traceback; traceback.print_exc()
        try: conn.rollback()
        except: pass
        return False, str(e)
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
        current_tier=val(user,"current_tier",len(TIERS)-1)
        end_dt=None
        try: end_dt=datetime.fromisoformat(ai_end_str) if ai_end_str else None
        except: end_dt=None
        if end_dt and now>=end_dt and balance>0:
            cur.execute(f"UPDATE users SET balance=0, profit=0, ai_start=NULL, ai_end=NULL, current_tier={ph()}, profit_per_hour=0 WHERE user_id={ph()}",(len(TIERS)-1,user_id))
            conn.commit()
            cur.execute(f"SELECT * FROM users WHERE user_id={ph()}",(user_id,))
            user=cur.fetchone()
            balance=0
            tier_index,_,daily_percent=get_tier(0)
            end_dt=None
            ai_end_str=None
        if balance>=20 and not ai_end_str:
            ai_start=now.isoformat()
            ai_end=(now+timedelta(days=30)).isoformat()
            cur.execute(f"UPDATE users SET ai_start={ph()}, ai_end={ph()}, current_tier={ph()} WHERE user_id={ph()}",(ai_start,ai_end,tier_index,user_id))
            ai_end_str=ai_end
            try: end_dt=datetime.fromisoformat(ai_end)
            except: end_dt=now+timedelta(days=30)
        elif current_tier!=tier_index and balance>=20:
            ai_start=now.isoformat()
            ai_end=(now+timedelta(days=30)).isoformat()
            cur.execute(f"UPDATE users SET ai_start={ph()}, ai_end={ph()}, current_tier={ph()} WHERE user_id={ph()}",(ai_start,ai_end,tier_index,user_id))
            ai_end_str=ai_end
            try: end_dt=datetime.fromisoformat(ai_end)
            except: end_dt=now+timedelta(days=30)
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
        try: due=not last_auto or (now-datetime.fromisoformat(last_auto)).total_seconds()>=86400
        except: due=True
        if due and profit>.01 and active:
            cur.execute(f"UPDATE users SET withdrawable=COALESCE(withdrawable,0)+{ph()}, profit=0, last_auto_claim={ph()} WHERE user_id={ph()}",(profit,now.isoformat(),user_id))
            profit=0
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

@app.post("/webhook")
async def webhook_handler(request: Request):
    if WEBHOOK_SECRET:
        secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if secret != WEBHOOK_SECRET:
            raise HTTPException(401, "Invalid secret token")
    try:
        data = await request.json()
        from telegram import Update
        from telegram.ext import Application, CommandHandler, CallbackQueryHandler
        from bot import start, callback_handler
        if not BOT_TOKEN: return {"ok": False, "error": "BOT_TOKEN missing"}
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

@app.post("/webhook/{token}")
async def webhook_legacy(token: str, request: Request):
    if BOT_TOKEN and token != BOT_TOKEN:
        if WEBHOOK_SECRET:
            secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
            if secret != WEBHOOK_SECRET:
                raise HTTPException(401, "Invalid token")
        else:
            raise HTTPException(401, "Invalid token")
    return await webhook_handler(request)

@app.get("/webhook")
def webhook_get(): return {"ok": True, "message": "Webhook active - POST"}

@app.get("/api/me/{user_id}")
def api_me(user_id:int, username: Optional[str] = Query(None), referred_by: Optional[str] = Query(None)):
    if user_id<=0: raise HTTPException(400, "Invalid user")
    u=ensure_user(user_id, username or "", referred_by)
    u=recalc_profit(user_id)
    if not u: raise HTTPException(404, "User not found")
    d=dict(u)
    if d.get("is_banned"): raise HTTPException(403, "Banned")
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
def deposit_addresses(): return DEPOSIT_ADDR

@app.post("/api/deposit/invoice/{user_id}")
def create_invoice(user_id:int, req:InvoiceRequest):
    if req.amount < 1: raise HTTPException(400, "Min $1")
    if req.network not in DEPOSIT_ADDR: req.network="TRC20"
    ensure_user(user_id)
    conn=get_conn()
    try:
        cur=cursor(conn)
        inv=invoice_id()
        now=datetime.utcnow()
        exp=now+timedelta(minutes=30)
        cur.execute(f"INSERT INTO deposits (user_id,amount,network,status,created_at,expires_at,invoice_id,expected_amount) VALUES ({ph()},{ph()},{ph()},'awaiting_payment',{ph()},{ph()},{ph()},{ph()})",(user_id,req.amount,req.network,now.isoformat(),exp.isoformat(),inv,req.amount))
        conn.commit()
        addr=DEPOSIT_ADDR.get(req.network, DEPOSIT_ADDR["TRC20"])
        return {"invoice_id":inv,"address":addr,"amount":req.amount,"network":req.network,"expires_at":exp.isoformat(),"qr":addr,"expected_amount":req.amount}
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(500, str(e))
    finally: put_conn(conn)

@app.get("/api/deposit/invoice_status/{invoice_id}")
def invoice_status(invoice_id:str):
    conn=get_conn()
    try:
        cur=cursor(conn); cur.execute(f"SELECT * FROM deposits WHERE invoice_id={ph()}",(invoice_id,)); d=cur.fetchone()
        if not d: raise HTTPException(404, "not found")
        return dict(d)
    finally: put_conn(conn)

@app.post("/api/withdraw/{user_id}")
def withdraw(user_id:int, req:WithdrawalRequest):
    if req.amount < 1: raise HTTPException(400, "Min $1")
    if req.network not in DEPOSIT_ADDR: raise HTTPException(400, "Invalid network")
    u=ensure_user(user_id); u=recalc_profit(user_id)
    if not u: raise HTTPException(404)
    if float(val(u,"withdrawable",0) or 0) < req.amount: return JSONResponse({"ok":False,"error":"Insufficient withdrawable balance"}, status_code=400)
    if val(u,"is_banned"): raise HTTPException(403, "Banned")
    conn=get_conn()
    try:
        cur=cursor(conn)
        cur.execute(f"SELECT COUNT(*) as cnt FROM tasks WHERE is_mandatory=1 AND is_active=1")
        mand=val(cur.fetchone(),"cnt",0) or 0
        if mand>0:
            cur.execute(f"SELECT COUNT(*) as cnt FROM user_tasks WHERE user_id={ph()} AND status='verified'",(user_id,))
            done=val(cur.fetchone(),"cnt",0) or 0
            if done<mand:
                return JSONResponse({"ok":False,"error":f"Complete {mand} mandatory tasks first!"}, status_code=403)
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
        bot_name=BOT_USERNAME
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
        if not task: raise HTTPException(404, "Task not found")
        if not BOT_TOKEN: raise HTTPException(500, "BOT_TOKEN not set")
        chat_id=val(task,"group_id")
        is_member, details = check_telegram_membership(BOT_TOKEN, chat_id, user_id)
        if not is_member:
            return JSONResponse({"ok":False,"error":"Not joined yet. JOIN first, then Verify","details":details}, status_code=400)
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
        return {"ok":True,"reward":reward,"message":f"Verified! +{reward} USDT"}
    except HTTPException: raise
    except Exception as e:
        import traceback; traceback.print_exc()
        return JSONResponse({"ok":False,"error":str(e)}, status_code=500)
    finally: put_conn(conn)

@app.post("/api/tasks/join/{user_id}/{task_id}")
def tasks_join_click(user_id:int, task_id:int):
    conn=get_conn()
    try:
        cur=cursor(conn)
        cur.execute(f"SELECT * FROM tasks WHERE id={ph()}",(task_id,))
        if not cur.fetchone(): raise HTTPException(404)
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
    from datetime import timezone
    utc_now = datetime.now(timezone.utc)
    ist_now = utc_now + timedelta(hours=5, minutes=30)
    today_str = ist_now.date().isoformat()
    seed = int(hashlib.md5(today_str.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    total_trades_for_day = 16 + (seed % 3)
    trades_all = []
    for i in range(total_trades_for_day):
        if i == 0: trade_minutes = rng.randint(5, 25)
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
        if i < total_trades_for_day * 0.65: is_win = rng.random() < 0.78
        else: is_win = rng.random() < 0.45
        pnl = round(rng.uniform(1.2, 6.8),2) if is_win else round(rng.uniform(-2.5, -0.3),2)
        exitp = entry * (1 + pnl/100) if side == "LONG" else entry * (1 - pnl/100)
        amount = round(rng.uniform(300, 1800),2)
        trades_all.append({"id":i+1,"pair":sym.replace("USDT","/USDT"),"symbol":sym,"side":side,"leverage":rng.choice([5,10,15,20]),"usdt_amount":amount,"entry_price":round(entry,6 if entry<1 else 2),"exit_price":round(exitp,6 if exitp<1 else 2),"pnl_percent":pnl,"pnl_usdt":round(amount*pnl/100,2),"is_profit":pnl>0,"time":time_str,"minutes":trade_minutes,"status":"CLOSED","date":today_str})
    current_minutes = ist_now.hour*60+ist_now.minute
    visible_trades = [t for t in trades_all if t["minutes"]<=current_minutes]
    for t in visible_trades: t.pop("minutes",None)
    for t in trades_all: t.pop("minutes",None)
    return {"trades":visible_trades,"all_trades_count":len(trades_all),"summary":{"total_trades":len(visible_trades),"expected_total":len(trades_all),"profit_trades":sum(1 for t in visible_trades if t["is_profit"]),"loss_trades":len(visible_trades)-sum(1 for t in visible_trades if t["is_profit"]),"total_pnl_percent":round(sum(t["pnl_percent"] for t in visible_trades),2),"total_pnl_usdt":round(sum(t["pnl_usdt"] for t in visible_trades),2),"funds_in_market":round(sum(t["usdt_amount"] for t in visible_trades),2),"date":today_str,"current_ist":ist_now.strftime("%H:%M IST"),"win_rate":round((sum(1 for t in visible_trades if t["is_profit"])/len(visible_trades)*100) if visible_trades else 0,1),"next_trade_in":f"{trades_all[len(visible_trades)]['time'] if len(visible_trades)<len(trades_all) else 'Tomorrow 00:30'} IST" if len(visible_trades)<len(trades_all) else "All trades done"},"prices_source":"deterministic_daily","live_prices":BASE_PRICES.copy()}

# --- ADMIN ---
@app.get("/api/admin/stats")
def admin_stats(_=Depends(verify_admin)):
    conn=get_conn()
    try:
        cur=cursor(conn)
        cur.execute("SELECT COUNT(*) AS users, COALESCE(SUM(balance),0) AS balance, COALESCE(SUM(withdrawable),0) AS wd, COALESCE(SUM(total_deposit),0) AS tdep FROM users")
        stats=cur.fetchone()
        cur.execute("SELECT COUNT(*) as total FROM deposits WHERE status='awaiting_payment'"); pending_cnt=val(cur.fetchone(),"total",0)
        cur.execute("SELECT COUNT(*) as total FROM deposits WHERE status='verified'"); verified_cnt=val(cur.fetchone(),"total",0)
        cur.execute("SELECT COUNT(*) as total FROM deposits WHERE status='expired'"); expired_cnt=val(cur.fetchone(),"total",0)
        cur.execute("SELECT COALESCE(SUM(actual_amount),0) as s FROM deposits WHERE status='verified'"); verified_sum=val(cur.fetchone(),"s",0)
        cur.execute("SELECT COUNT(*) AS pending FROM withdrawals WHERE status='pending'"); wd=cur.fetchone()
        cur.execute("SELECT COALESCE(SUM(bonus_amount),0) AS paid FROM referral_logs"); ref=cur.fetchone()
        cur.execute("SELECT COUNT(*) AS tasks FROM tasks WHERE is_active=1"); tc=cur.fetchone()
        cur.execute("SELECT COUNT(*) AS completed FROM user_tasks WHERE status='verified'"); comp=cur.fetchone()
        return {"total_users":val(stats,"users",0),"total_balance":val(stats,"balance",0),"total_withdrawable":val(stats,"wd",0),"total_deposits_all":val(stats,"tdep",0),"total_verified_deposits":verified_sum,"pending_deposits":pending_cnt,"verified_deposits":verified_cnt,"expired_deposits":expired_cnt,"pending_withdrawals":val(wd,"pending",0),"total_ref_paid":val(ref,"paid",0),"active_tasks":val(tc,"tasks",0),"completed_tasks":val(comp,"completed",0)}
    finally: put_conn(conn)

@app.get("/api/admin/deposits")
def admin_deposits(_=Depends(verify_admin)):
    conn=get_conn()
    try: cur=cursor(conn); cur.execute("SELECT * FROM deposits ORDER BY id DESC LIMIT 500"); return rows_as_dicts(cur.fetchall())
    finally: put_conn(conn)

@app.get("/api/admin/withdrawals")
def admin_withdrawals(_=Depends(verify_admin)):
    conn=get_conn()
    try: cur=cursor(conn); cur.execute("SELECT * FROM withdrawals ORDER BY id DESC LIMIT 500"); return rows_as_dicts(cur.fetchall())
    finally: put_conn(conn)

@app.get("/api/admin/referrals")
def admin_referrals(_=Depends(verify_admin)):
    conn=get_conn()
    try: cur=cursor(conn); cur.execute("SELECT * FROM referral_logs ORDER BY id DESC LIMIT 500"); return rows_as_dicts(cur.fetchall())
    finally: put_conn(conn)

@app.get("/api/admin/users")
def admin_users(_=Depends(verify_admin)):
    conn=get_conn()
    try: cur=cursor(conn); cur.execute("SELECT * FROM users ORDER BY created_at DESC LIMIT 1000"); return rows_as_dicts(cur.fetchall())
    finally: put_conn(conn)

@app.get("/api/admin/tasks")
def admin_tasks_list(_=Depends(verify_admin)):
    conn=get_conn()
    try: cur=cursor(conn); cur.execute("SELECT * FROM tasks ORDER BY sort_order ASC, id DESC"); return rows_as_dicts(cur.fetchall())
    finally: put_conn(conn)

@app.post("/api/admin/tasks/create")
def admin_tasks_create(t: TaskCreate, _=Depends(verify_admin)):
    conn=get_conn()
    try:
        cur=cursor(conn)
        cur.execute(f"INSERT INTO tasks (title,description,group_link,group_id,group_username,reward,reward_type,is_active,is_mandatory,icon,sort_order,created_at) VALUES ({ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()})",(t.title,t.description,t.group_link,t.group_id,t.group_username,t.reward,t.reward_type,t.is_active,t.is_mandatory,t.icon,t.sort_order,datetime.utcnow().isoformat()))
        conn.commit()
        return {"ok":True}
    finally: put_conn(conn)

@app.post("/api/admin/tasks/action")
def admin_tasks_action(a: IdAction, _=Depends(verify_admin)):
    conn=get_conn()
    try:
        cur=cursor(conn)
        if a.action=="delete": cur.execute(f"DELETE FROM tasks WHERE id={ph()}",(a.id,))
        elif a.action=="toggle_active": cur.execute(f"UPDATE tasks SET is_active = CASE WHEN is_active=1 THEN 0 ELSE 1 END WHERE id={ph()}",(a.id,))
        elif a.action=="toggle_mandatory": cur.execute(f"UPDATE tasks SET is_mandatory = CASE WHEN is_mandatory=1 THEN 0 ELSE 1 END WHERE id={ph()}",(a.id,))
        conn.commit()
        return {"ok":True}
    finally: put_conn(conn)

@app.post("/api/admin/deposit/action")
def admin_deposit_action(action: IdAction, _=Depends(verify_admin)):
    conn=get_conn()
    try:
        cur=cursor(conn)
        cur.execute(f"SELECT * FROM deposits WHERE id={ph()}",(action.id,))
        dep=cur.fetchone()
        if not dep: return {"ok":False,"error":"Deposit not found"}
        if action.action=="approve":
            ok,msg=process_invoice_payment(val(dep,"invoice_id"), f"manual_{action.id}_{datetime.utcnow().isoformat()}", float(val(dep,"expected_amount",0) or val(dep,"amount",0)))
            return {"ok":ok, "msg":msg}
        elif action.action=="reject":
            cur.execute(f"UPDATE deposits SET status='rejected', admin_note={ph()} WHERE id={ph()}",(action.note or "Rejected", action.id)); conn.commit(); return {"ok":True}
        elif action.action=="delete":
            cur.execute(f"DELETE FROM deposits WHERE id={ph()}",(action.id,)); conn.commit(); return {"ok":True}
        else: return {"ok":False,"error":"Unsupported"}
    finally: put_conn(conn)

@app.post("/api/admin/withdraw/action")
def admin_withdraw_action(action: IdAction, _=Depends(verify_admin)):
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
def admin_user_action(action: AdminAction, _=Depends(verify_admin)):
    conn=get_conn()
    try:
        cur=cursor(conn)
        act=action.action
        cur.execute(f"SELECT * FROM users WHERE user_id={ph()}",(action.user_id,))
        u=cur.fetchone()
        if not u and act!="delete": return {"ok":False,"error":"User not found"}
        amt=float(action.amount or 0)
        if act=="add_balance": cur.execute(f"UPDATE users SET balance=COALESCE(balance,0)+{ph()} WHERE user_id={ph()}",(amt,action.user_id))
        elif act=="deduct_balance": cur.execute(f"UPDATE users SET balance=GREATEST(0,COALESCE(balance,0)-{ph()}) WHERE user_id={ph()}",(amt,action.user_id))
        elif act=="set_balance": cur.execute(f"UPDATE users SET balance={ph()} WHERE user_id={ph()}",(amt,action.user_id))
        elif act=="add_withdrawable": cur.execute(f"UPDATE users SET withdrawable=COALESCE(withdrawable,0)+{ph()} WHERE user_id={ph()}",(amt,action.user_id))
        elif act=="set_withdrawable": cur.execute(f"UPDATE users SET withdrawable={ph()} WHERE user_id={ph()}",(amt,action.user_id))
        elif act=="ban": cur.execute(f"UPDATE users SET is_banned=1 WHERE user_id={ph()}",(action.user_id,))
        elif act=="unban": cur.execute(f"UPDATE users SET is_banned=0 WHERE user_id={ph()}",(action.user_id,))
        elif act=="expire_now": cur.execute(f"UPDATE users SET balance=0, profit=0, ai_start=NULL, ai_end=NULL, current_tier={ph()} WHERE user_id={ph()}",(len(TIERS)-1,action.user_id))
        elif act=="reset_timer":
            now=datetime.utcnow(); ai_end=(now+timedelta(days=30)).isoformat()
            cur.execute(f"UPDATE users SET ai_start={ph()}, ai_end={ph()} WHERE user_id={ph()}",(now.isoformat(),ai_end,action.user_id))
        elif act=="delete": cur.execute(f"DELETE FROM users WHERE user_id={ph()}",(action.user_id,))
        else: return {"ok":False,"error":"unknown action"}
        conn.commit()
        return {"ok":True}
    finally: put_conn(conn)

@app.post("/api/admin/bulk_action")
def admin_bulk_action(data: BulkAction, _=Depends(verify_admin)):
    conn=get_conn()
    try:
        cur=cursor(conn); count=0
        for uid in data.user_ids:
            try:
                if data.action=="add_withdrawable": cur.execute(f"UPDATE users SET withdrawable=COALESCE(withdrawable,0)+{ph()} WHERE user_id={ph()}",(data.amount, uid)); count+=1
                elif data.action=="add_balance": cur.execute(f"UPDATE users SET balance=COALESCE(balance,0)+{ph()} WHERE user_id={ph()}",(data.amount, uid)); count+=1
                elif data.action=="ban": cur.execute(f"UPDATE users SET is_banned=1 WHERE user_id={ph()}",(uid,)); count+=1
                elif data.action=="unban": cur.execute(f"UPDATE users SET is_banned=0 WHERE user_id={ph()}",(uid,)); count+=1
            except: pass
        conn.commit()
        return {"ok":True,"count":count}
    finally: put_conn(conn)

@app.get("/api/debug/db")
def debug_db(_=Depends(verify_admin)):
    conn=get_conn()
    try:
        cur=cursor(conn)
        tables=[]; counts={}
        if USE_POSTGRES:
            cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
            tables=[r['table_name'] for r in cur.fetchall()]
            for t in ['users','deposits','withdrawals','tasks','user_tasks','referral_logs','used_tx_hashes']:
                try: cur.execute(f"SELECT COUNT(*) as c FROM {t}"); counts[t]=cur.fetchone()['c']
                except Exception as e: counts[t]=f"error: {e}"
        else:
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'"); tables=[r[0] for r in cur.fetchall()]
            for t in ['users','deposits','withdrawals','tasks','user_tasks']:
                try: cur.execute(f"SELECT COUNT(*) FROM {t}"); counts[t]=cur.fetchone()[0]
                except Exception as e: counts[t]=f"error: {e}"
        return {"tables":tables,"counts":counts,"db": "POSTGRES" if USE_POSTGRES else "SQLITE", "database_url_prefix": os.getenv("DATABASE_URL","")[:30]+"..."}
    finally: put_conn(conn)

@app.post("/api/admin/tasks/restore_defaults")
def restore_defaults(_=Depends(verify_admin)):
    conn=get_conn()
    try:
        cur=cursor(conn)
        cur.execute("SELECT COUNT(*) as c FROM tasks")
        r=cur.fetchone()
        cnt = r['c'] if isinstance(r, dict) else r[0]
        if cnt>0: return {"ok":False,"msg":f"tasks already exist: {cnt}"}
        defaults=[
            ("Join Main Trading Group","Join PT_AI Trading Group and earn 1 USDT instantly","https://t.me/PT_AI_Trading_Group","@PT_AI_Trading_Group","PT_AI_Trading_Group",1,"withdrawable",1,1,"🚀",0),
            ("Join Trading Channel","Join official channel for signals","https://t.me/PT_AI_Trading","@PT_AI_Trading","PT_AI_Trading",1,"withdrawable",1,1,"📢",1),
            ("Join Support Group","Join support and earn bonus","https://t.me/PT_AI_Support","@PT_AI_Support","PT_AI_Support",1,"withdrawable",0,1,"💬",2)
        ]
        for d in defaults:
            cur.execute(f"INSERT INTO tasks (title,description,group_link,group_id,group_username,reward,reward_type,is_active,is_mandatory,icon,sort_order,created_at) VALUES ({ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()},{ph()})",(*d,datetime.utcnow().isoformat()))
        conn.commit()
        return {"ok":True,"created":len(defaults)}
    finally: put_conn(conn)

@app.get("/")
def root(): return FileResponse("index.html")
@app.get("/admin")
def admin_page(): return FileResponse("admin.html")
@app.get("/health")
def health(): return {"ok":True,"db":"POSTGRES" if USE_POSTGRES else "SQLITE","version":"V7_FINAL"}
@app.get("/api/admin/logs")
def admin_logs(_=Depends(verify_admin)):
    conn=get_conn()
    try: cur=cursor(conn); cur.execute("SELECT * FROM admin_logs ORDER BY id DESC LIMIT 100"); return rows_as_dicts(cur.fetchall())
    finally: put_conn(conn)
