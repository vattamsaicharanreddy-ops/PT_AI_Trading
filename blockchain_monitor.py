import json
import logging
import threading
import time
import urllib.request
from datetime import datetime, timedelta

from database import get_conn, get_cursor, safe_close, ph

logger = logging.getLogger("monitor")

DEPOSIT_ADDR_TRON = "TAFHf1pxsXRCSnhn8jRU5UcU4STK6u9tAC"
DEPOSIT_ADDR_BSC = "0xDD190484827BB976acEB975C94d5c58fc8c87Cfd".lower()
USDT_TRC20_CONTRACT = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
USDT_BEP20_CONTRACT = "0x55d398326f99059fF775485246999027B3197955".lower()


def get_tron_transactions():
    try:
        url = f"https://api.trongrid.io/v1/accounts/{DEPOSIT_ADDR_TRON}/transactions/trc20?limit=20&contract_address={USDT_TRC20_CONTRACT}"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data.get("data", [])
    except Exception as e:
        logger.error(f"Tron fetch error: {e}")
        return []


def get_bsc_transactions():
    try:
        url = f"https://api.bscscan.com/api?module=account&action=tokentx&address={DEPOSIT_ADDR_BSC}&contractaddress={USDT_BEP20_CONTRACT}&page=1&offset=20&sort=desc"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data.get("status") == "1":
                return data.get("result", [])
            return []
    except Exception as e:
        logger.error(f"BSC error: {e}")
        return []


def verify_pending_deposits():
    from database import USE_POSTGRES
    conn = get_conn()
    try:
        cur = get_cursor(conn)
        cur.execute("SELECT * FROM deposits WHERE status='awaiting_payment' ORDER BY created_at DESC LIMIT 50")
        pending = cur.fetchall()
        if not pending:
            return
        logger.info(f"Checking {len(pending)} pending deposits")
        tron_txs = get_tron_transactions()
        bsc_txs = get_bsc_transactions()
        for dep in pending:
            try:
                d = dict(dep)
                inv = d.get("invoice_id")
                user_id = d.get("user_id")
                expected = float(d.get("expected_amount", 0) or d.get("amount", 0) or 0)
                network = d.get("network", "TRC20")
                exp_str = d.get("expires_at")
                created_str = d.get("created_at")
                try:
                    exp_dt = datetime.fromisoformat(exp_str) if exp_str else datetime.utcnow()
                    if datetime.utcnow() > exp_dt:
                        cur.execute(f"UPDATE deposits SET status='expired' WHERE invoice_id={ph()}", (inv,))
                        conn.commit()
                        logger.info(f"Expired {inv}")
                        continue
                except Exception:
                    pass
                try:
                    created_dt = datetime.fromisoformat(created_str) if created_str else datetime.utcnow() - timedelta(minutes=16)
                except Exception:
                    created_dt = datetime.utcnow() - timedelta(minutes=16)
                matched_tx = None
                matched_amount = 0
                if network == "TRC20":
                    for tx in tron_txs:
                        try:
                            to_addr = tx.get("to", "") or tx.get("to_address", "")
                            value = tx.get("value", "0") or tx.get("quant", "0")
                            tx_id = tx.get("transaction_id", "") or tx.get("transactionHash", "")
                            timestamp = tx.get("block_timestamp", 0) or tx.get("timestamp", 0)
                            try:
                                amount = float(value) / 1_000_000
                            except Exception:
                                amount = 0
                            if str(to_addr).lower() == DEPOSIT_ADDR_TRON.lower():
                                tx_time = datetime.fromtimestamp(timestamp / 1000) if timestamp > 1000000000000 else datetime.fromtimestamp(timestamp) if timestamp > 1000000000 else datetime.utcnow()
                                if tx_time >= created_dt - timedelta(minutes=2):
                                    if abs(amount - expected) < 0.5 or amount >= expected - 0.01:
                                        cur.execute(f"SELECT tx_hash FROM used_tx_hashes WHERE tx_hash={ph()}", (tx_id,))
                                        if not cur.fetchone():
                                            matched_tx = tx_id
                                            matched_amount = amount
                                            break
                        except Exception:
                            continue
                elif network in ["BEP20", "ERC20"]:
                    for tx in bsc_txs:
                        try:
                            to_addr = tx.get("to", "").lower()
                            value = tx.get("value", "0")
                            tx_hash = tx.get("hash", "")
                            time_stamp = int(tx.get("timeStamp", "0"))
                            try:
                                amount = float(value) / (10**18)
                                if amount < 0.01:
                                    amount = float(value) / 1_000_000
                            except Exception:
                                amount = 0
                            if to_addr == DEPOSIT_ADDR_BSC:
                                tx_time = datetime.fromtimestamp(time_stamp) if time_stamp > 0 else datetime.utcnow()
                                if tx_time >= created_dt - timedelta(minutes=2):
                                    if abs(amount - expected) < 0.5 or amount >= expected - 0.01:
                                        cur.execute(f"SELECT tx_hash FROM used_tx_hashes WHERE tx_hash={ph()}", (tx_hash,))
                                        if not cur.fetchone():
                                            matched_tx = tx_hash
                                            matched_amount = amount
                                            break
                        except Exception:
                            continue
                if matched_tx:
                    from server import process_invoice_payment
                    ok, msg = process_invoice_payment(inv, matched_tx, matched_amount or expected)
                    if ok:
                        logger.info(f"AUTO-VERIFIED {inv} {matched_tx} {matched_amount} user {user_id}")
            except Exception as e:
                logger.error(f"Monitor dep error: {e}")
        conn.commit()
    except Exception as e:
        logger.error(f"Monitor loop error: {e}")
    finally:
        safe_close(conn)


def blockchain_monitor_loop():
    logger.info("Blockchain Auto-Verifier Started - 15s interval")
    time.sleep(10)
    while True:
        try:
            verify_pending_deposits()
        except Exception as e:
            logger.error(f"Monitor exception: {e}")
        time.sleep(15)


monitor_thread = threading.Thread(target=blockchain_monitor_loop, daemon=True)
monitor_thread.start()
