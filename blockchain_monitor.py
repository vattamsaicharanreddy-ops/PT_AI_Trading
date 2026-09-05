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
MEGANODE_KEY = os.getenv("MEGANODE_KEY", "3b02fd41bc494d6d877a659530a8a434").strip()
MEGANODE_BSC_URL = os.getenv("MEGANODE_BSC_URL", "https://bsc-mainnet.nodereal.io/v1/").rstrip("/")
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
        api_key = MEGANODE_KEY
        url = MEGANODE_BSC_URL + "/" + api_key
        transfer_topic = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
        wallet_topic = "0x000000000000000000000000" + WITHDRAWAL_ADDR_BSC[2:]
        latest_hex = _meganode_call(url, "eth_blockNumber", [])
        latest = int(latest_hex, 16)
        recent_blocks = int(os.getenv("WD_SCAN_BLOCKS", "30"))
        logs = _meganode_call(url, "eth_getLogs", [{
            "fromBlock": hex(max(latest - recent_blocks, 0)),
            "toBlock": hex(latest),
            "address": USDT_BEP20_CONTRACT,
            "topics": [transfer_topic, wallet_topic],
        }])
        if not isinstance(logs, list):
            return []
        # fetch timestamps for unique blocks (concurrently for speed)
        blocks = {}
        for lg in logs:
            blocks[int(lg.get("blockNumber"), 16)] = None
        if blocks:
            bn_list = list(blocks.keys())

            def _get_block_ts(bn):
                try:
                    blk = _meganode_call(url, "eth_getBlockByNumber", [hex(bn), False])
                    return bn, int(blk.get("timestamp"), 16) if isinstance(blk, dict) else 0
                except Exception:
                    return bn, 0

            try:
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=16) as ex:
                    for bn, ts in ex.map(_get_block_ts, bn_list, chunksize=1):
                        blocks[bn] = ts
            except Exception:
                pass
        out = []
        for lg in logs:
            try:
                bn = int(lg.get("blockNumber"), 16)
                topics = lg.get("topics", [])
                if len(topics) < 3:
                    continue
                to_addr = "0x" + topics[2][-40:]
                if to_addr.lower() == WITHDRAWAL_ADDR_BSC:
                    continue
                amount = int(lg.get("data", "0") or "0", 16) / (10 ** 18)
                if amount <= 0:
                    continue
                out.append({
                    "from": WITHDRAWAL_ADDR_BSC,
                    "to": to_addr,
                    "hash": lg.get("transactionHash", ""),
                    "amount": amount,
                    "time": blocks.get(bn, 0),
                })
            except Exception:
                continue
        # newest first
        out.sort(key=lambda t: t.get("time", 0), reverse=True)
        return out
    except Exception as e:
        logger.error(f"BSC withdrawal fetch error: {e}")
    return []


def _meganode_call(url, method, params):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode())
    if data.get("error"):
        raise Exception(str(data.get("error")))
    return data.get("result")


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
                try:
                    amount = float(tx.get("amount", 0) or 0)
                except Exception:
                    amount = 0
                time_stamp = int(tx.get("time", 0) or 0)
                if time_stamp > 1000000000:
                    tx_time = datetime.fromtimestamp(time_stamp, tz=timezone.utc)
                else:
                    tx_time = datetime.utcnow()
                # Only post FRESH txs - tx must be within WD_FRESH_MAX_MIN (default 10 min)
                # so the on-chain timestamp closely matches the post time.
                now_utc = datetime.utcnow()
                fresh_min = int(os.getenv("WD_FRESH_MAX_MIN", "10"))
                cutoff = now_utc - timedelta(minutes=fresh_min)
                if tx_time.replace(tzinfo=None) < cutoff:
                    continue
                # Enforce amount range: min 10, max 1000 USDT.
                min_amt = float(os.getenv("WD_MIN_AMOUNT", "10"))
                max_amt = float(os.getenv("WD_MAX_AMOUNT", "1000"))
                if amount < min_amt or amount > max_amt:
                    continue
                # Bias toward the 10-100 band so most posts look realistic.
                # Txs over 100 only get queued occasionally (default 20%).
                if amount > 100:
                    large_chance = float(os.getenv("WD_LARGE_CHANCE", "0.2"))
                    if random.random() > large_chance:
                        continue
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
    # Clear stale queue on startup so old backfill txs don't post with wrong timestamps
    _clear_stale_queue()
    time.sleep(8)
    MAX_PER_HOUR = int(os.getenv("WD_POST_PER_HOUR", "1"))
    MIN_GAP = int(os.getenv("WD_POST_GAP_MIN", "240"))
    MAX_GAP = int(os.getenv("WD_POST_GAP_MAX", "360"))
    post_keeper = {"last_post_iso": ""}
    first_run = True
    while True:
        try:
            if tracker_is_paused():
                time.sleep(20)
                continue
            # scan for new outgoing payouts and enqueue them
            try:
                scan_and_announce_withdrawals()
            except Exception as e:
                logger.error(f"Withdrawal scan exception: {e}")
            # post immediately on first run / first available item for a fast first post
            _post_from_queue_if_allowed(MAX_PER_HOUR, MIN_GAP, MAX_GAP, post_keeper, force_first=first_run)
            first_run = False
        except Exception as e:
            logger.error(f"Withdrawal announce exception: {e}")
        time.sleep(20)


def _clear_stale_queue():
    conn = get_conn()
    try:
        cur = get_cursor(conn)
        cur.execute("DELETE FROM wd_post_queue WHERE posted=0")
        conn.commit()
    except Exception:
        pass
    finally:
        safe_close(conn)


def _posts_this_hour(cur, now_iso):
    hour_prefix = now_iso[:13]
    cur.execute(f"SELECT COUNT(*) as cnt FROM withdrawal_announcements WHERE posted_at LIKE {ph()}", (hour_prefix + "%",))
    r = cur.fetchone()
    r = dict(r) if not isinstance(r, dict) else r
    return r.get("cnt", 0) or 0


def _post_from_queue_if_allowed(max_per_hour, min_gap, max_gap, post_keeper, force_first=False):
    conn = get_conn()
    try:
        cur = get_cursor(conn)
        now = datetime.utcnow()
        cur.execute(f"SELECT id, tx_hash, amount, to_addr, tx_time FROM wd_post_queue WHERE posted=0 ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        if not row:
            return
        # at most 1 post per hour
        if _posts_this_hour(cur, now.isoformat()) >= max_per_hour:
            return
        # enforce 4-6 hour gap between posts
        last = post_keeper.get("last_post_iso", "")
        if last and not force_first:
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
        # Only post FRESH txs so the on-chain time matches the post time closely.
        max_age_min = int(os.getenv("WD_POST_MAX_AGE_MIN", "5"))
        if w["time"] > 1000000000:
            tx_dt = datetime.fromtimestamp(w["time"], tz=timezone.utc).replace(tzinfo=None)
            if (now - tx_dt).total_seconds() / 60.0 > max_age_min:
                # no fresh tx available yet - wait for a new one
                return
        min_amt = float(os.getenv("WD_MIN_AMOUNT", "10"))
        max_amt = float(os.getenv("WD_MAX_AMOUNT", "1000"))
        if w["amount"] < min_amt or w["amount"] > max_amt:
            # outside valid range - skip, mark posted to avoid re-trying
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
            # random 4-6 hour gap before next
            time.sleep(random.randint(min_gap, max_gap) * 60)
    except Exception as e:
        logger.error(f"Post-from-queue error: {e}")
    finally:
        safe_close(conn)


wd_announce_thread = threading.Thread(target=withdrawal_announce_loop, daemon=True)
TRACKER_PAUSED = [False]


def set_tracker_paused(paused: bool):
    TRACKER_PAUSED[0] = paused
    logger.info(f"Payout tracker paused={paused}")


def tracker_is_paused():
    return TRACKER_PAUSED[0]


wd_announce_thread.start()
