
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel
import sqlite3, datetime, os, json, urllib.request, urllib.error
import random

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
 from_user INTEGER,
 to_user INTEGER,
 level INTEGER,
 deposit_amount REAL,
 bonus_amount REAL,
 created_at TEXT
)""")

conn.commit()

for sql in [
    "ALTER TABLE users ADD COLUMN created_at TEXT",
    "ALTER TABLE users ADD COLUMN last_withdraw_date TEXT",
    "ALTER TABLE users ADD COLUMN referred_by INTEGER",
    "ALTER TABLE users ADD COLUMN referral_earnings REAL DEFAULT 0",
    "ALTER TABLE withdrawals ADD COLUMN auto_approved INTEGER DEFAULT 0"
]:
    try:
        conn.execute(sql)
    except:
        pass
conn.commit()

DEPOSIT_ADDR = {
 "TRC20": "TYourTronAddressHere",
 "BEP20": "0xYourBSCAddressHere",
 "ERC20": "0xYourETHAddressHere",
 "TON": "UQYourTonAddress",
 "SOL": "YourSolAddress"
}

TIERS = [
 (15000, 14.9),
 (6000, 13.6),
 (2500, 11.8),
 (1200, 10.9),
 (500, 9.6),
 (120, 8.9),
 (20, 7.6),
 (0, 0.0)
]

REF_BONUS = {1: 7, 2: 1, 3: 1, 4: 1, 5: 1, 6: 1, 7: 1, 8: 1, 9: 1, 10: 1}

def get_tier_index(balance: float):
    for i, (min_bal, pct) in enumerate(TIERS):
        if balance >= min_bal:
            return i, min_bal, pct
    return len(TIERS)-1, 0, 0.0

def ensure_user(user_id: int, username="", referred_by=None):
    row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    now = datetime.datetime.utcnow()
    if not row:
        ref = None
        if referred_by:
            try:
                ref_id = int(referred_by)
                if ref_id != user_id and conn.execute("SELECT 1 FROM users WHERE user_id=?", (ref_id,)).fetchone():
                    ref = ref_id
            except:
                pass
        conn.execute("INSERT INTO users (user_id, username, referred_by, created_at, last_claim, last_auto_claim, current_tier) VALUES (?,?,?,?,?,?,?)",
                     (user_id, username or f"user_{user_id}", ref, now.isoformat(), now.isoformat(), now.isoformat(), len(TIERS)-1))
        conn.commit()
        return conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    if len(row) > 15 and row[15] is None:
        conn.execute("UPDATE users SET created_at=? WHERE user_id=?", (now.isoformat(), user_id))
        conn.commit()
    return conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()

def recalc_profit(user_id: int):
    row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    if not row:
        return None
    balance = row[2] or 0
    ai_end_str = row[7]
    last_claim_str = row[8]
    last_auto_str = row[9]
    current_tier_idx = row[12] if len(row) > 12 and row[12] is not None else len(TIERS)-1
    now = datetime.datetime.utcnow()
    tier_idx, tier_min, daily_pct = get_tier_index(balance)
    if tier_idx < current_tier_idx and balance >= 20:
        ai_start = now.isoformat()
        ai_end = (now + datetime.timedelta(days=30)).isoformat()
        conn.execute("UPDATE users SET ai_start=?, ai_end=?, current_tier=? WHERE user_id=?", (ai_start, ai_end, tier_idx, user_id))
        ai_end_str = ai_end
    else:
        if (not ai_end_str) and balance >= 20:
            ai_start = now.isoformat()
            ai_end = (now + datetime.timedelta(days=30)).isoformat()
            conn.execute("UPDATE users SET ai_start=?, ai_end=?, current_tier=? WHERE user_id=?", (ai_start, ai_end, tier_idx, user_id))
            ai_end_str = ai_end
        elif tier_idx != current_tier_idx:
            conn.execute("UPDATE users SET current_tier=? WHERE user_id=?", (tier_idx, user_id))
    per_hour = (balance * daily_pct / 100) / 24 if daily_pct>0 else 0
    profit = row[4] or 0
    if ai_end_str:
        try:
            ai_end_dt = datetime.datetime.fromisoformat(ai_end_str)
            if now < ai_end_dt and per_hour>0 and last_claim_str:
                last_claim = datetime.datetime.fromisoformat(last_claim_str)
                hours = (now - last_claim).total_seconds()/3600
                if hours>0:
                    inc = hours * per_hour
                    profit += inc
                    conn.execute("UPDATE users SET profit=?, last_claim=?, profit_per_hour=?, daily_percent=? WHERE user_id=?",
                                 (profit, now.isoformat(), per_hour, daily_pct, user_id))
            else:
                conn.execute("UPDATE users SET profit_per_hour=?, daily_percent=? WHERE user_id=?", (per_hour, daily_pct, user_id))
        except:
            pass
    try:
        if last_auto_str:
            last_auto = datetime.datetime.fromisoformat(last_auto_str)
            if (now - last_auto).total_seconds() >= 24*3600:
                if profit > 0.01:
                    withdrawable = (conn.execute("SELECT withdrawable FROM users WHERE user_id=?", (user_id,)).fetchone()[0] or 0) + profit
                    conn.execute("UPDATE users SET withdrawable=?, profit=0, last_auto_claim=? WHERE user_id=?", (withdrawable, now.isoformat(), user_id))
                    profit = 0
                else:
                    conn.execute("UPDATE users SET last_auto_claim=? WHERE user_id=?", (now.isoformat(), user_id))
    except:
        pass
    conn.commit()
    return conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()

def distribute_referral(depositor_id: int, deposit_amount: float):
    now = datetime.datetime.utcnow().isoformat()
    current_id = depositor_id
    for level in range(1, 11):
        ref_row = conn.execute("SELECT referred_by FROM users WHERE user_id=?", (current_id,)).fetchone()
        if not ref_row or not ref_row[0]:
            break
        referrer_id = ref_row[0]
        if not conn.execute("SELECT 1 FROM users WHERE user_id=?", (referrer_id,)).fetchone():
            break
        bonus_pct = REF_BONUS.get(level, 0)
        if bonus_pct > 0:
            bonus = deposit_amount * bonus_pct / 100
            conn.execute("UPDATE users SET withdrawable=withdrawable+?, referral_earnings=referral_earnings+? WHERE user_id=?", (bonus, bonus, referrer_id))
            conn.execute("INSERT INTO referral_logs (from_user, to_user, level, deposit_amount, bonus_amount, created_at) VALUES (?,?,?,?,?,?)",
                         (depositor_id, referrer_id, level, deposit_amount, bonus, now))
        current_id = referrer_id
    conn.commit()

# ===== REAL BINANCE PRICES ENDPOINT =====
BINANCE_SYMBOLS = ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","DOGEUSDT","AVAXUSDT","LINKUSDT","LTCUSDT","ADAUSDT","PEPEUSDT","SHIBUSDT","MATICUSDT","DOTUSDT","ARBUSDT"]

@app.get("/api/binance/prices")
def binance_prices():
    """Fetch real Binance prices - proxy to avoid CORS"""
    try:
        url = "https://api.binance.com/api/v3/ticker/price"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            # Filter only our symbols
            filtered = {item['symbol']: float(item['price']) for item in data if item['symbol'] in BINANCE_SYMBOLS}
            # If Binance fails to return some (like PEPE, SHIB), use fallback
            fallback = {
                "BTCUSDT": 67500, "ETHUSDT": 3450, "SOLUSDT": 175, "BNBUSDT": 610,
                "XRPUSDT": 0.62, "DOGEUSDT": 0.16, "AVAXUSDT": 42, "LINKUSDT": 18.5,
                "LTCUSDT": 84, "ADAUSDT": 0.48, "PEPEUSDT": 0.000009, "SHIBUSDT": 0.000027,
                "MATICUSDT": 0.89, "DOTUSDT": 7.2, "ARBUSDT": 1.12
            }
            for sym in BINANCE_SYMBOLS:
                if sym not in filtered:
                    filtered[sym] = fallback.get(sym, 100)
            return {"success": True, "prices": filtered, "source": "binance", "timestamp": datetime.datetime.utcnow().isoformat()}
    except Exception as e:
        # Fallback prices if Binance API fails
        fallback_prices = {
            "BTCUSDT": 67500 + random.uniform(-500,500),
            "ETHUSDT": 3450 + random.uniform(-50,50),
            "SOLUSDT": 175 + random.uniform(-5,5),
            "BNBUSDT": 610 + random.uniform(-10,10),
            "XRPUSDT": 0.62 + random.uniform(-0.02,0.02),
            "DOGEUSDT": 0.16 + random.uniform(-0.01,0.01),
            "AVAXUSDT": 42 + random.uniform(-1,1),
            "LINKUSDT": 18.5 + random.uniform(-0.5,0.5),
            "LTCUSDT": 84 + random.uniform(-2,2),
            "ADAUSDT": 0.48 + random.uniform(-0.02,0.02),
            "PEPEUSDT": 0.000009 + random.uniform(-0.0000005,0.0000005),
            "SHIBUSDT": 0.000027 + random.uniform(-0.000001,0.000001),
            "MATICUSDT": 0.89 + random.uniform(-0.03,0.03),
            "DOTUSDT": 7.2 + random.uniform(-0.2,0.2),
            "ARBUSDT": 1.12 + random.uniform(-0.05,0.05)
        }
        return {"success": True, "prices": fallback_prices, "source": "fallback", "timestamp": datetime.datetime.utcnow().isoformat()}

@app.get("/api/binance/trades")
def binance_trades_all():
    """Same trades for all users - 12-15 trades, 50-70% total PnL, deterministic per day"""
    import hashlib
    today = datetime.date.today().isoformat()
    seed = int(hashlib.md5(today.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    
    prices_data = binance_prices()
    prices = prices_data["prices"]
    
    count = 12 + (seed % 4)  # 12-15
    target_total = 50 + (seed % 21)  # 50-70%
    
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
    
    trades = []
    total_usdt = 0
    for i in range(count):
        sym = symbols[i % len(symbols)]
        pair = sym.replace("USDT","/USDT")
        pnl = all_pnls[i]
        side = rng.choice(["LONG","SHORT"])
        leverage = rng.choice([5,10,15,20])
        usdt = round(800 + rng.random()*1200,2)
        total_usdt += usdt
        time_h = (6 + i*1 + rng.randint(0,2)) % 24
        time_m = rng.randint(0,59)
        time_str = f"{time_h:02d}:{time_m:02d}"
        status = "OPEN" if i < 3 else "CLOSED"
        curr_price = prices.get(sym, 100)
        if side == "LONG":
            entry = curr_price / (1 + pnl/100)
        else:
            entry = curr_price / (1 - pnl/100)
        
        trades.append({
            "id": i+1,
            "pair": pair,
            "symbol": sym,
            "side": side,
            "entry_price": round(entry, 6 if entry < 1 else 2),
            "current_price": round(curr_price, 6 if curr_price < 1 else 2),
            "leverage": leverage,
            "usdt_amount": usdt,
            "pnl_percent": pnl,
            "pnl_usdt": round(usdt*pnl/100,2),
            "is_profit": pnl>0,
            "time": time_str,
            "status": status,
            "date": today
        })
    
    trades.sort(key=lambda x: x["time"], reverse=True)
    total_pnl = round(sum(t["pnl_percent"] for t in trades),2)
    
    return {
        "trades": trades,
        "summary": {
            "total_trades": count,
            "profit_trades": len([t for t in trades if t["pnl_percent"]>0]),
            "loss_trades": len([t for t in trades if t["pnl_percent"]<0]),
            "total_pnl_percent": total_pnl,
            "total_pnl_usdt": round(sum(t["pnl_usdt"] for t in trades),2),
            "funds_in_market": round(total_usdt,2),
            "date": today
        },
        "prices_source": prices_data["source"]
    }

# Cache for daily trades per user - to keep consistent on refresh
DAILY_TRADES_CACHE = {}

@app.get("/api/binance/trades/{user_id}")
def binance_trades(user_id: int):
    """Generate FIXED 12-15 trades per day per user - consistent on refresh, 50-70% total PnL"""
    ensure_user(user_id)
    user_row = conn.execute("SELECT balance FROM users WHERE user_id=?", (user_id,)).fetchone()
    balance = user_row[0] if user_row else 0
    
    # Get real prices
    prices_data = binance_prices()
    prices = prices_data["prices"]
    
    today = datetime.datetime.utcnow().date().isoformat()
    cache_key = f"{user_id}_{today}"
    
    # If cached and same day, return cached trades but update current prices
    if cache_key in DAILY_TRADES_CACHE:
        cached = DAILY_TRADES_CACHE[cache_key]
        # Update current prices with live Binance prices
        for trade in cached["trades"]:
            sym = trade["symbol"]
            if sym in prices:
                live_price = prices[sym]
                trade["current_price"] = round(live_price, 6 if live_price < 1 else 2)
                # Recalculate PnL for OPEN trades based on live price
                if trade["status"] == "OPEN":
                    if trade["side"] == "LONG":
                        new_pnl = ((live_price - trade["entry_price"]) / trade["entry_price"]) * 100
                    else:
                        new_pnl = ((trade["entry_price"] - live_price) / trade["entry_price"]) * 100
                    trade["pnl_percent"] = round(new_pnl, 2)
                    trade["pnl_usdt"] = round(trade["usdt_amount"] * new_pnl / 100, 2)
                    trade["is_profit"] = new_pnl > 0
        # Recalculate summary
        total_pnl = sum(t["pnl_percent"] for t in cached["trades"])
        profit_cnt = sum(1 for t in cached["trades"] if t["pnl_percent"] > 0)
        loss_cnt = len(cached["trades"]) - profit_cnt
        cached["summary"]["total_pnl_percent"] = round(total_pnl, 2)
        cached["summary"]["profit_trades"] = profit_cnt
        cached["summary"]["loss_trades"] = loss_cnt
        cached["summary"]["total_pnl_usdt"] = round(sum(t["pnl_usdt"] for t in cached["trades"]), 2)
        return cached
    
    # Generate NEW trades for today - deterministic seed for consistency
    seed_str = f"{user_id}_{today}"
    seed = hash(seed_str) % (2**32)
    random.seed(seed)
    
    symbols = list(prices.keys())
    # Fixed count 12-15 based on seed - same for whole day
    count = 12 + (seed % 4)  # 12,13,14,15
    # Target total PnL 50-70% for the day
    target_total_pnl = 50 + (seed % 21)  # 50-70%
    # Distribute PnL across trades - 70% winning trades
    winning_count = int(count * 0.7)  # 70% win rate = 8-10 wins
    losing_count = count - winning_count
    
    trades = []
    total_pnl_percent = 0
    profit_count = 0
    loss_count = 0
    now = datetime.datetime.utcnow()
    
    # Generate winning PnLs that sum to ~60-75% minus small losses
    # Winning trades: 5-9% each, losing: -0.5 to -1.5% each
    win_pnls = []
    lose_pnls = []
    # Reserve 10% for losses, 90% for wins to reach 50-70% net
    net_target = target_total_pnl
    loss_budget = - (losing_count * 1.0)  # average -1% per loss
    win_budget = net_target - loss_budget  # need this much from wins
    
    for i in range(winning_count):
        pnl = win_budget / winning_count + random.uniform(-1, 1)
        pnl = max(3.0, min(9.0, pnl))  # clamp 3-9%
        win_pnls.append(round(pnl, 2))
    
    for i in range(losing_count):
        pnl = -random.uniform(0.5, 1.8)
        lose_pnls.append(round(pnl, 2))
    
    all_pnls = win_pnls + lose_pnls
    random.shuffle(all_pnls)
    
    for i in range(count):
        symbol = random.choice(symbols)
        pair = symbol.replace("USDT","/USDT")
        current_price = prices[symbol]
        target_pnl = all_pnls[i]
        is_profit = target_pnl > 0
        side = "LONG" if random.random() > 0.5 else "SHORT"
        
        if side == "LONG":
            entry_price = current_price / (1 + target_pnl/100)
        else:
            entry_price = current_price / (1 - target_pnl/100)
        
        leverage = random.choice([5,10,15,20])
        usdt_amount = round((balance*0.08 + random.random()*balance*0.04) if balance>20 else (20 + random.random()*60), 2)
        pnl_usdt = round(usdt_amount * target_pnl / 100, 2)
        
        trade_time = now - datetime.timedelta(hours=random.randint(0,23), minutes=random.randint(0,59))
        time_str = trade_time.strftime("%H:%M")
        
        status = "OPEN" if i < 3 else "CLOSED"
        
        if is_profit:
            profit_count+=1
        else:
            loss_count+=1
        total_pnl_percent+=target_pnl
        
        trades.append({
            "id": i+1,
            "pair": pair,
            "symbol": symbol,
            "side": side,
            "entry_price": round(entry_price, 6 if entry_price < 1 else 2),
            "current_price": round(current_price, 6 if current_price < 1 else 2),
            "leverage": leverage,
            "usdt_amount": usdt_amount,
            "pnl_percent": target_pnl,
            "pnl_usdt": pnl_usdt,
            "is_profit": is_profit,
            "time": time_str,
            "status": status,
            "timestamp": trade_time.isoformat()
        })
    
    trades.sort(key=lambda x: x["time"], reverse=True)
    
    result = {
        "trades": trades,
        "summary": {
            "total_trades": count,
            "profit_trades": profit_count,
            "loss_trades": loss_count,
            "total_pnl_percent": round(total_pnl_percent, 2),
            "total_pnl_usdt": round(sum(t["pnl_usdt"] for t in trades), 2),
            "funds_in_market": round(balance*0.75, 2) if balance>0 else 0,
            "target_pnl": target_total_pnl,
            "date": today
        },
        "prices_source": prices_data["source"]
    }
    
    DAILY_TRADES_CACHE[cache_key] = result
    random.seed()  # Reset random seed
    return result

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
        "ai_end": row[7],
        "days_left": days_left,
        "hours_left": hours_left,
        "ai_active": active,
        "total_deposit": row[10] or 0,
        "total_withdraw": row[11] or 0,
        "tier_min": get_tier_index(row[2] or 0)[1],
        "referral_earnings": row[14] if len(row) > 14 and row[14] else 0,
        "referred_by": row[13] if len(row) > 13 else None,
        "created_at": created_str,
        "days_since_join": days_since,
        "can_withdraw_today": can_withdraw_today,
        "last_withdraw_date": last_wd_date,
        "tiers": [{"min": t[0], "pct": t[1]} for t in TIERS]
    }

@app.get("/api/referral/{user_id}")
def api_referral(user_id: int):
    ensure_user(user_id)
    total_earnings = conn.execute("SELECT COALESCE(SUM(bonus_amount),0) FROM referral_logs WHERE to_user=?", (user_id,)).fetchone()[0] or 0
    level_counts = {i:0 for i in range(1,11)}
    total_team_deposit = 0
    direct_refs = []
    current_level_ids = [user_id]
    visited = set()
    for lvl in range(1,11):
        next_ids = []
        for uid in current_level_ids:
            refs = conn.execute("SELECT user_id, balance, total_deposit FROM users WHERE referred_by=?", (uid,)).fetchall()
            for r in refs:
                if r[0] not in visited:
                    visited.add(r[0])
                    next_ids.append(r[0])
                    level_counts[lvl]+=1
                    total_team_deposit += (r[2] or 0)
                    if lvl==1:
                        direct_refs.append({"user_id": r[0], "balance": r[1], "total_deposit": r[2]})
        current_level_ids = next_ids
        if not current_level_ids:
            break
    import os
    bot_username = os.getenv("BOT_USERNAME", "YourBot")
    ref_link = f"https://t.me/{bot_username}?start={user_id}"
    return {
        "ref_link": ref_link,
        "direct_count": len(direct_refs),
        "direct_refs": direct_refs,
        "level_counts": level_counts,
        "total_team_deposit": total_team_deposit,
        "total_earnings": total_earnings,
        "bonus_structure": REF_BONUS
    }

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
    if old_bal < 20 and new_bal >= 20:
        should_reset = True
    elif tier_idx < old_tier_idx:
        should_reset = True
    if should_reset:
        ai_start = now.isoformat()
        ai_end = (now + datetime.timedelta(days=30)).isoformat()
    else:
        row = conn.execute("SELECT ai_start, ai_end FROM users WHERE user_id=?", (user_id,)).fetchone()
        ai_start = row[0]
        ai_end = row[1]
        if not ai_end and new_bal >=20:
            ai_start = now.isoformat()
            ai_end = (now + datetime.timedelta(days=30)).isoformat()
    conn.execute("INSERT INTO deposits (user_id, amount, network, tx_hash, status, created_at) VALUES (?,?,?,?,?,?)",
                 (user_id, r.amount, r.network, r.tx_hash, "approved", now.isoformat()))
    conn.execute("""UPDATE users SET balance=?, profit_per_hour=?, daily_percent=?, 
                 total_deposit=total_deposit+?, ai_start=?, ai_end=?, current_tier=?, last_claim=?
                 WHERE user_id=?""",
                 (new_bal, per_hour, daily_pct, r.amount, ai_start, ai_end, tier_idx, now.isoformat(), user_id))
    conn.commit()
    distribute_referral(user_id, r.amount)
    return {"ok": True, "auto_approved": True, "new_balance": new_bal, "daily_percent": daily_pct, "ai_reset": should_reset, "ai_end": ai_end}

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
    if not user_row:
        return {"error": "User not found"}
    withdrawable = user_row[0] or 0
    created_str = user_row[1]
    last_wd_date = user_row[2] or ""
    if last_wd_date == today_str:
        return {"error": "Withdrawal limit: Once per day only. Try tomorrow."}
    today_count = conn.execute("SELECT COUNT(*) FROM withdrawals WHERE user_id=? AND DATE(created_at)=DATE('now')", (user_id,)).fetchone()[0]
    if today_count > 0:
        return {"error": "Withdrawal limit: Once per day only. Try tomorrow."}
    if r.amount < 10:
        return {"error": "Min withdraw 10 USDT"}
    if withdrawable < r.amount:
        return {"error": f"Insufficient withdrawable USDT. You have {withdrawable:.2f} USDT"}
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

@app.get("/api/admin/deposits")
def admin_deps():
    rows = conn.execute("SELECT id, user_id, amount, network, tx_hash, status, created_at FROM deposits ORDER BY id DESC LIMIT 100").fetchall()
    return [{"id":r[0],"user_id":r[1],"amount":r[2],"network":r[3],"tx_hash":r[4],"status":r[5],"created_at":r[6]} for r in rows]

@app.get("/api/admin/withdrawals")
def admin_wds():
    rows = conn.execute("SELECT id, user_id, amount, address, network, status, created_at, auto_approved FROM withdrawals ORDER BY id DESC LIMIT 100").fetchall()
    return [{"id":r[0],"user_id":r[1],"amount":r[2],"address":r[3],"network":r[4],"status":r[5],"created_at":r[6],"auto":r[7]} for r in rows]

@app.get("/api/admin/referrals")
def admin_refs():
    rows = conn.execute("SELECT id, from_user, to_user, level, deposit_amount, bonus_amount, created_at FROM referral_logs ORDER BY id DESC LIMIT 200").fetchall()
    return [{"id":r[0],"from_user":r[1],"to_user":r[2],"level":r[3],"deposit":r[4],"bonus":r[5],"at":r[6]} for r in rows]

class ApproveReq(BaseModel):
    id: int; action: str

@app.post("/api/admin/withdraw/action")
def wd_action(r: ApproveReq):
    wd = conn.execute("SELECT user_id, amount FROM withdrawals WHERE id=?", (r.id,)).fetchone()
    if not wd: return {"error":"not found"}
    if r.action=="approve":
        conn.execute("UPDATE withdrawals SET status='approved' WHERE id=?", (r.id,))
        conn.execute("UPDATE users SET total_withdraw=total_withdraw+? WHERE user_id=?", (wd[1], wd[0]))
    else:
        conn.execute("UPDATE withdrawals SET status='rejected' WHERE id=?", (r.id,))
        conn.execute("UPDATE users SET withdrawable=withdrawable+? WHERE user_id=?", (wd[1], wd[0]))
    conn.commit()
    return {"ok":True}

@app.get("/")
def root(): return FileResponse("index.html")
@app.get("/admin")
def admin_page(): return FileResponse("admin.html")
@app.get("/health")
def health(): return {"ok": True}
