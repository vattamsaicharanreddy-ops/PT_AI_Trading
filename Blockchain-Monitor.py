
import threading
import time
import urllib.request
import json
from datetime import datetime, timedelta
from database import get_conn, get_cursor

# Your correct addresses
DEPOSIT_ADDR_TRON = "TAFHf1pxsXRCSnhn8jRU5UcU4STK6u9tAC"
DEPOSIT_ADDR_BSC = "0xDD190484827BB976acEB975C94d5c58fc8c87Cfd".lower()

# USDT contract addresses
USDT_TRC20_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"  # USDT TRC20
USDT_BEP20_CONTRACT = "0x55d398326f99059fF775485246999027B3197955".lower()  # USDT BEP20 on BSC

def get_tron_transactions():
    """Fetch recent TRC20 USDT transactions to your address via TronScan API"""
    try:
        # TronGrid API - get TRC20 transactions
        url = f"https://api.trongrid.io/v1/accounts/{DEPOSIT_ADDR_TRON}/transactions/trc20?limit=20&contract_address={USDT_TRC20_CONTRACT}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data.get("data", [])
    except Exception as e:
        print(f"[Blockchain Monitor] Tron fetch error: {e}")
        # Fallback to TronScan API
        try:
            url = f"https://apilist.tronscanapi.com/api/token_trc20/transfers?limit=20&toAddress={DEPOSIT_ADDR_TRON}&contract_address={USDT_TRC20_CONTRACT}&confirm=true"
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                return data.get("token_transfers", [])
        except Exception as e2:
            print(f"[Blockchain Monitor] TronScan fallback error: {e2}")
            return []

def get_bsc_transactions():
    """Fetch BEP20 USDT transactions via BscScan API - requires API key, using public endpoint"""
    try:
        # Public BSC endpoint without API key (limited)
        url = f"https://api.bscscan.com/api?module=account&action=tokentx&address={DEPOSIT_ADDR_BSC}&contractaddress={USDT_BEP20_CONTRACT}&page=1&offset=20&sort=desc"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data.get("status") == "1":
                return data.get("result", [])
            return []
    except Exception as e:
        print(f"[Blockchain Monitor] BSC fetch error: {e}")
        return []

def verify_pending_deposits():
    """Main verification loop - checks all awaiting_payment invoices"""
    from database import USE_POSTGRES
    def ph(): return "%s" if USE_POSTGRES else "?"
    
    conn = get_conn()
    try:
        from database import get_cursor
        cur = get_cursor(conn)
        # Get all pending invoices not expired
        cur.execute(f"SELECT * FROM deposits WHERE status='awaiting_payment' ORDER BY created_at DESC LIMIT 50")
        pending = cur.fetchall()
        if not pending:
            return
        
        print(f"[Blockchain Monitor] Checking {len(pending)} pending invoices...")
        
        # Fetch blockchain transactions
        tron_txs = get_tron_transactions()
        bsc_txs = get_bsc_transactions()
        
        print(f"[Blockchain Monitor] Found {len(tron_txs)} Tron txs, {len(bsc_txs)} BSC txs")
        
        for dep in pending:
            try:
                dep_dict = dict(dep)
                invoice_id = dep_dict.get("invoice_id")
                user_id = dep_dict.get("user_id")
                expected = float(dep_dict.get("expected_amount", 0) or dep_dict.get("amount", 0) or 0)
                network = dep_dict.get("network", "TRC20")
                created_at_str = dep_dict.get("created_at")
                expires_at_str = dep_dict.get("expires_at")
                
                # Check if expired
                try:
                    exp_dt = datetime.fromisoformat(expires_at_str) if expires_at_str else datetime.utcnow()
                    if datetime.utcnow() > exp_dt:
                        cur.execute(f"UPDATE deposits SET status='expired' WHERE invoice_id={ph()}", (invoice_id,))
                        conn.commit()
                        print(f"[Monitor] Expired invoice {invoice_id}")
                        continue
                except: pass
                
                # Check creation time window (only check txs after invoice creation)
                try:
                    created_dt = datetime.fromisoformat(created_at_str) if created_at_str else datetime.utcnow() - timedelta(minutes=16)
                except:
                    created_dt = datetime.utcnow() - timedelta(minutes=16)
                
                matched_tx = None
                matched_amount = 0
                
                if network == "TRC20":
                    for tx in tron_txs:
                        try:
                            # TronGrid format
                            to_addr = tx.get("to", "")
                            from_addr = tx.get("from", "")
                            value = tx.get("value", "0")
                            tx_id = tx.get("transaction_id", "") or tx.get("transactionHash", "")
                            timestamp = tx.get("block_timestamp", 0) or tx.get("timestamp", 0)
                            
                            # TronScan format compatibility
                            if not to_addr:
                                to_addr = tx.get("to_address", "")
                            if not value:
                                value = tx.get("quant", "0")
                            if not tx_id:
                                tx_id = tx.get("transactionHash", "")
                            
                            # Convert value (TRC20 USDT has 6 decimals)
                            try:
                                amount = float(value) / 1_000_000  # 6 decimals
                            except:
                                amount = 0
                            
                            # Check if to our address and amount matches expected (±0.5 USDT tolerance for fees)
                            if to_addr.lower() == DEPOSIT_ADDR_TRON.lower() if hasattr(to_addr, 'lower') else to_addr == DEPOSIT_ADDR_TRON:
                                # Check timestamp is after invoice creation
                                tx_time = datetime.fromtimestamp(timestamp/1000) if timestamp > 1000000000000 else datetime.fromtimestamp(timestamp) if timestamp > 1000000000 else datetime.utcnow()
                                if tx_time >= created_dt - timedelta(minutes=2):  # 2 min buffer
                                    # Amount check with small tolerance
                                    if abs(amount - expected) < 0.5 or amount >= expected - 0.01:
                                        # Check if tx already used
                                        cur.execute(f"SELECT tx_hash FROM used_tx_hashes WHERE tx_hash={ph()}", (tx_id,))
                                        if not cur.fetchone():
                                            matched_tx = tx_id
                                            matched_amount = amount
                                            print(f"[Monitor] MATCH TRC20: invoice {invoice_id} expected {expected} found {amount} tx {tx_id}")
                                            break
                        except Exception as e:
                            continue
                
                elif network in ["BEP20", "ERC20"]:
                    for tx in bsc_txs:
                        try:
                            to_addr = tx.get("to", "").lower()
                            value = tx.get("value", "0")
                            tx_hash = tx.get("hash", "")
                            time_stamp = int(tx.get("timeStamp", "0"))
                            
                            try:
                                # BEP20 USDT has 18 decimals but USDT on BSC uses 18? Actually 18 decimals, but we check
                                amount = float(value) / (10 ** 18)
                                # For USDT BEP20, it's 18 decimals, but some use 6 - try both
                                if amount < 0.01:
                                    amount = float(value) / 1_000_000
                            except:
                                amount = 0
                            
                            if to_addr == DEPOSIT_ADDR_BSC:
                                tx_time = datetime.fromtimestamp(time_stamp) if time_stamp > 0 else datetime.utcnow()
                                if tx_time >= created_dt - timedelta(minutes=2):
                                    if abs(amount - expected) < 0.5 or amount >= expected - 0.01:
                                        cur.execute(f"SELECT tx_hash FROM used_tx_hashes WHERE tx_hash={ph()}", (tx_hash,))
                                        if not cur.fetchone():
                                            matched_tx = tx_hash
                                            matched_amount = amount
                                            print(f"[Monitor] MATCH BEP20: invoice {invoice_id} expected {expected} found {amount} tx {tx_hash}")
                                            break
                        except: continue
                
                if matched_tx:
                    # Auto-verify and credit user
                    from server import process_invoice_payment
                    ok, msg = process_invoice_payment(invoice_id, matched_tx, matched_amount or expected)
                    if ok:
                        print(f"[Monitor] ✅ AUTO-VERIFIED invoice {invoice_id} tx {matched_tx} amount {matched_amount} -> user {user_id} credited!")
                        # Send Telegram notification to user if bot token exists
                        try:
                            import os, urllib.request, json
                            bot_token = os.getenv("BOT_TOKEN", "")
                            if not bot_token and os.path.exists("bot_token.txt"):
                                with open("bot_token.txt") as f: bot_token = f.read().strip()
                            if bot_token:
                                url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                                payload = {"chat_id": user_id, "text": f"✅ Deposit Verified!\n\nAmount: {matched_amount} USDT ({network})\nInvoice: {invoice_id}\nTX: {matched_tx[:20]}...\n\nYour balance credited and AI ACTIVE now! 🚀", "parse_mode": "HTML"}
                                req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type":"application/json"})
                                with urllib.request.urlopen(req, timeout=5) as r: r.read()
                        except Exception as e:
                            print(f"[Monitor] Notification failed: {e}")
                    else:
                        print(f"[Monitor] Failed to credit {invoice_id}: {msg}")
            
            except Exception as e:
                print(f"[Monitor] Error processing deposit {dep}: {e}")
                import traceback
                traceback.print_exc()
        
        conn.commit()
    except Exception as e:
        print(f"[Monitor] Loop error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        try:
            from database import put_conn
            put_conn(conn)
        except: pass

def blockchain_monitor_loop():
    """Background thread that runs every 15 seconds"""
    print("🔍 Blockchain Auto-Verifier Started - Checking every 15s")
    print(f"   Monitoring TRC20 address: {DEPOSIT_ADDR_TRON}")
    print(f"   Monitoring BEP20 address: {DEPOSIT_ADDR_BSC}")
    time.sleep(10)  # Wait for API to start
    while True:
        try:
            verify_pending_deposits()
        except Exception as e:
            print(f"[Monitor] Loop exception: {e}")
        time.sleep(15)  # Check every 15 seconds as promised in UI

# Start monitor in background thread when module imported
monitor_thread = threading.Thread(target=blockchain_monitor_loop, daemon=True)
monitor_thread.start()
