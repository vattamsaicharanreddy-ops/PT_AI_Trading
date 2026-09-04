import json
import logging
import os
import random
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone

from database import get_conn, get_cursor, safe_close, ph

logger = logging.getLogger("monitor")

DEPOSIT_ADDR_TRON = "TAFHf1pxsXRCSnhn8jRU5UcU4STK6u9tAC"
DEPOSIT_ADDR_BSC = "0xDD190484827BB976acEB975C94d5c58fc8c87Cfd".lower()
WITHDRAWAL_ADDR_BSC = os.getenv("WITHDRAWAL_ADDR_BSC", "0xa180Fe01B906A1bE37BE6c534a3300785b20d947").strip().lower()
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
                                    tol = expected * 0.01
                                    if amount >= expected - tol:
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
                                    tol = expected * 0.01
                                    if amount >= expected - tol:
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


def get_outgoing_bsc_transactions():
    try:
        api_key = os.getenv("BSCSCAN_API_KEY", "").strip()
        url = (f"https://api.bscscan.com/api?module=account&action=tokentx&address={WITHDRAWAL_ADDR_BSC}"
               f"&contractaddress={USDT_BEP20_CONTRACT}&page=1&offset=20&sort=desc")
        if api_key:
            url += f"&apikey={api_key}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data.get("status") == "1":
                return data.get("result", [])
    except Exception as e:
        logger.error(f"BSC withdrawal fetch error: {e}")
    return []


def _post_withdrawal_to_group(text):
    token = os.getenv("BOT_TOKEN", "").strip()
    notify_chat = os.getenv("NOTIFY_CHANNEL", "").strip() or os.getenv("GROUP_ID", "").strip()
    if not token or not notify_chat:
        logger.warning("Post withdrawal skipped: BOT_TOKEN/NOTIFY_CHANNEL not set")
        return False
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = json.dumps({"chat_id": notify_chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}).encode()
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=12) as r:
            return bool(json.loads(r.read().decode()).get("ok"))
    except Exception as e:
        logger.error(f"TG post failed: {e}")
        return False


def scan_and_announce_withdrawals():
    conn = get_conn()
    try:
        cur = get_cursor(conn)
        txs = get_outgoing_bsc_transactions()
        if not txs:
            return
        added = 0
        for tx in txs:
            try:
                from_addr = tx.get("from", "").lower()
                to_addr = tx.get("to", "").lower()
                if from_addr != WITHDRAWAL_ADDR_BSC:
                    continue
                if to_addr == WITHDRAWAL_ADDR_BSC:
                    continue
                tx_hash = tx.get("hash", "")
                value = tx.get("value", "0")
                try:
                    amount = float(value) / (10 ** 18)
                    if amount < 0.01:
                        amount = float(value) / 1_000_000
                except Exception:
                    amount = 0
                time_stamp = int(tx.get("timeStamp", "0") or 0)
                if time_stamp > 1000000000:
                    tx_time = datetime.fromtimestamp(time_stamp, tz=timezone.utc)
                else:
                    tx_time = datetime.utcnow()
                cur.execute(f"SELECT tx_hash FROM withdrawal_announcements WHERE tx_hash={ph()}", (tx_hash,))
                if cur.fetchone():
                    continue
                cur.execute(f"SELECT tx_hash FROM wd_post_queue WHERE tx_hash={ph()}", (tx_hash,))
                if cur.fetchone():
                    continue
                cur.execute(
                    f"INSERT INTO wd_post_queue (tx_hash, amount, to_addr, tx_time, created_at, posted) VALUES ({ph()},{ph()},{ph()},{ph()},{ph()},0)",
                    (tx_hash, amount, to_addr, tx_time.isoformat(), datetime.utcnow().isoformat()),
                )
                added += 1
            except Exception:
                continue
        conn.commit()
        if added:
            logger.info(f"Queued {added} new outgoing withdrawal(s) for announced posting")
    except Exception as e:
        logger.error(f"Withdrawal scan error: {e}")
    finally:
        safe_close(conn)


def _announce_withdrawal(w):
    try:
        amount = w.get("amount", 0.0)
        tx_hash = w.get("hash", "")
        to_addr = w.get("to", "")
        ts = w.get("time", 0)
        if ts > 1000000000:
            tx_time = datetime.fromtimestamp(ts, tz=timezone.utc)
        else:
            tx_time = datetime.utcnow()
        time_str = tx_time.strftime("%d %b %Y, %H:%M UTC")
        short_addr = (to_addr[:8] + "..." + to_addr[-6:]) if to_addr and len(to_addr) > 16 else to_addr
        short_hash = (tx_hash[:16] + "..." + tx_hash[-8:]) if len(tx_hash) > 26 else tx_hash
        bscscan_link = f"https://bscscan.com/tx/{tx_hash}" if tx_hash else ""
        lines = [
            "<b>✅ Member Withdrawal Approved</b>",
            "",
            f"💵 Amount: <b>${amount:.2f} USDT</b>",
            "🔗 Network: BEP-20",
        ]
        if short_addr:
            lines.append(f"📬 To: <code>{short_addr}</code>")
        if tx_hash:
            lines.append(f"📝 Tx Hash: <code>{short_hash}</code>")
            lines.append(f"🔍 <a href=\"{bscscan_link}\">View on BSCScan</a>")
        lines.append(f"🕐 {time_str}")
        lines.append("📊 Status: <b>Completed</b>")
        lines.append("")
        bot_name = os.getenv("BOT_USERNAME", "PT_Minebot")
        lines.append("💰🚀 <b>Join now and start earning your profits!</b>")
        lines.append(f"👉 <a href=\"https://t.me/{bot_name}\">Open the Bot</a>")
        return _post_withdrawal_to_group("\n".join(lines))
    except Exception as e:
        logger.error(f"announce build error: {e}")
        return False


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


def withdrawal_announce_loop():
    logger.info(f"Withdrawal Announcement Scanner Started - watching {WITHDRAWAL_ADDR_BSC}")
    time.sleep(25)
    MAX_PER_HOUR = int(os.getenv("WD_POST_PER_HOUR", "5"))
    MIN_GAP = int(os.getenv("WD_POST_GAP_MIN", "10"))
    MAX_GAP = int(os.getenv("WD_POST_GAP_MAX", "20"))
    post_keeper = {"last_post_iso": ""}
    while True:
        try:
            time.sleep(5)
            _post_from_queue_if_allowed(MAX_PER_HOUR, MIN_GAP, MAX_GAP, post_keeper)
        except Exception as e:
            logger.error(f"Withdrawal announce exception: {e}")


def _posts_this_hour(cur, now_iso):
    hour_prefix = now_iso[:13]
    cur.execute(f"SELECT COUNT(*) as cnt FROM withdrawal_announcements WHERE posted_at LIKE {ph()}", (hour_prefix + "%",))
    r = cur.fetchone()
    r = dict(r) if not isinstance(r, dict) else r
    return r.get("cnt", 0) or 0


def _post_from_queue_if_allowed(max_per_hour, min_gap, max_gap, post_keeper):
    conn = get_conn()
    try:
        cur = get_cursor(conn)
        now = datetime.utcnow()
        cur.execute(f"SELECT id, tx_hash, amount, to_addr, tx_time FROM wd_post_queue WHERE posted=0 ORDER BY id ASC LIMIT 1")
        row = cur.fetchone()
        if not row:
            return
        # enforce 4-5 per hour
        if _posts_this_hour(cur, now.isoformat()) >= max_per_hour:
            return
        # enforce 10-20 min gap between posts
        last = post_keeper.get("last_post_iso", "")
        if last:
            try:
                last_dt = datetime.fromisoformat(last)
                elapsed_min = (now - last_dt).total_seconds() / 60.0
                if elapsed_min < min_gap:
                    return
            except Exception:
                pass
        r = dict(row) if not isinstance(row, dict) else row
        w = {
            "hash": r.get("tx_hash", ""),
            "amount": float(r.get("amount", 0) or 0),
            "to": r.get("to_addr", ""),
            "time": 0,
        }
        try:
            w["time"] = int(datetime.fromisoformat(r.get("tx_time", "")).timestamp())
        except Exception:
            pass
        if w["amount"] < 1:
            # skip junk / dust - mark posted to avoid re-trying
            cur.execute(f"UPDATE wd_post_queue SET posted=1 WHERE id={ph()}", (r.get("id"),))
            conn.commit()
            return
        ok = _announce_withdrawal(w)
        if ok:
            cur.execute(f"UPDATE wd_post_queue SET posted=1 WHERE id={ph()}", (r.get("id"),))
            cur.execute(f"INSERT INTO withdrawal_announcements (tx_hash, posted_at, withdrawal_id) VALUES ({ph()},{ph()},0)",
                (r.get("tx_hash", ""), now.isoformat()))
            post_keeper["last_post_iso"] = now.isoformat()
            conn.commit()
            logger.info(f"Posted simulated withdrawal {r.get('tx_hash','')} ${w['amount']:.2f}")
            # random 10-20 min gap before next
            time.sleep(random.randint(min_gap, max_gap) * 60)
    except Exception as e:
        logger.error(f"Post-from-queue error: {e}")
    finally:
        safe_close(conn)


wd_announce_thread = threading.Thread(target=withdrawal_announce_loop, daemon=True)
wd_announce_thread.start()
