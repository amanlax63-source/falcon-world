# ═══════════════════════════════════════════════════════════════
# ⚡ MEGA SPARK — Complete System v3 (Per-Channel Auto-Check)
# ═══════════════════════════════════════════════════════════════
import json, hmac, hashlib, time, asyncio, os, re, sqlite3, html, secrets
from urllib.parse import parse_qsl
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, Request, Body
from fastapi.responses import HTMLResponse, JSONResponse
import httpx

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
BOT_USERNAME = os.getenv("BOT_USERNAME", "MegaSpark_Bot").strip().lstrip("@")
MINI_APP_URL = os.getenv("MINI_APP_URL", "").strip()
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
DB_PATH = os.getenv("DB_PATH", "megaspark.db").strip() or "megaspark.db"
SUPPORT_USERNAME = "@AmanM_12"
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""

DEFAULT_DAILY = 0.50
DEFAULT_REFERRAL = 2.00
DEFAULT_MIN_WITHDRAW = 30.00

DEFAULT_CHANNELS = [
    {"username": "@ethiocashflow", "name": "Ethio Cash Flow", "url": "https://t.me/ethiocashflow"},
    {"username": "@Sheger_tech1", "name": "Sheger Tech", "url": "https://t.me/Sheger_tech1"},
    {"username": "@EthioVortex1", "name": "Ethio Vortex", "url": "https://t.me/EthioVortex1"},
    {"username": "@AmanIncomeLab", "name": "Aman Income Lab", "url": "https://t.me/AmanIncomeLab"},
    {"username": "@OnlineIncomeHub07", "name": "Online Income Hub", "url": "https://t.me/OnlineIncomeHub07"},
    {"username": "@Paymentprooff2", "name": "Payment Proof", "url": "https://t.me/Paymentprooff2"},
]

SERVICES = [
    ("📢", "Channel Growth", "Telegram channels ማሳደግ"),
    ("👥", "Group Growth", "Community መገንባት"),
    ("📣", "Advertising", "Brand ማስታወቂያ"),
    ("💱", "USDT Buy/Sell", "USDT መለዋወጥ"),
    ("📺", "Channel Buy/Sell", "Channel ግብይት"),
    ("📱", "Social Promotion", "Social media ማሳደግ"),
]

def db():
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn

def _col(conn, t, c): return c in {r[1] for r in conn.execute(f"PRAGMA table_info({t})").fetchall()}

def init_db():
    conn = db()
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY, username TEXT DEFAULT '', first_name TEXT DEFAULT '', last_name TEXT DEFAULT '',
            balance REAL DEFAULT 0, total_earned REAL DEFAULT 0, total_withdrawn REAL DEFAULT 0,
            referral_earnings REAL DEFAULT 0, daily_earnings REAL DEFAULT 0, task_earnings REAL DEFAULT 0, admin_credits REAL DEFAULT 0,
            verified INTEGER DEFAULT 0, banned INTEGER DEFAULT 0, ban_reason TEXT DEFAULT '',
            referred_by INTEGER, referral_paid INTEGER DEFAULT 0, daily_last_claim INTEGER DEFAULT 0,
            wallet_type TEXT, wallet_number TEXT, wallet_suspicious INTEGER DEFAULT 0,
            risk_score INTEGER DEFAULT 0, risk_flags TEXT DEFAULT '', device_hash TEXT DEFAULT '', ip_hash TEXT DEFAULT '',
            captcha_passed INTEGER DEFAULT 0, multi_flag INTEGER DEFAULT 0, is_test INTEGER DEFAULT 0,
            created_at INTEGER, updated_at INTEGER, last_active INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS captcha_sessions (
            token TEXT PRIMARY KEY, user_id INTEGER, question TEXT, answer TEXT,
            attempts INTEGER DEFAULT 0, created_at INTEGER, expires_at INTEGER);
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, type TEXT, amount REAL,
            balance_before REAL, balance_after REAL, description TEXT DEFAULT '', reference_id TEXT DEFAULT '',
            admin_id INTEGER, created_at INTEGER);
        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount REAL,
            wallet_type TEXT, wallet_number TEXT, status TEXT DEFAULT 'pending',
            risk_status TEXT DEFAULT 'normal', admin_id INTEGER, rejection_reason TEXT DEFAULT '',
            created_at INTEGER, reviewed_at INTEGER);
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, description TEXT DEFAULT '',
            reward REAL DEFAULT 0, url TEXT DEFAULT '', proof_type TEXT DEFAULT 'photo',
            active INTEGER DEFAULT 1, created_at INTEGER, created_by INTEGER);
        CREATE TABLE IF NOT EXISTS task_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER, user_id INTEGER,
            proof_text TEXT DEFAULT '', proof_image TEXT DEFAULT '', status TEXT DEFAULT 'pending',
            admin_id INTEGER, rejection_reason TEXT DEFAULT '', created_at INTEGER, reviewed_at INTEGER);
        CREATE TABLE IF NOT EXISTS required_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, name TEXT, url TEXT,
            active INTEGER DEFAULT 1, sort_order INTEGER DEFAULT 0, created_at INTEGER, updated_at INTEGER);
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS fraud_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, event_type TEXT,
            risk_score INTEGER DEFAULT 0, details TEXT DEFAULT '', created_at INTEGER);
        CREATE TABLE IF NOT EXISTS admin_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, admin_id INTEGER, action TEXT,
            target TEXT DEFAULT '', before_value TEXT DEFAULT '', after_value TEXT DEFAULT '', created_at INTEGER);
        CREATE INDEX IF NOT EXISTS idx_tx_u ON transactions(user_id);
        CREATE INDEX IF NOT EXISTS idx_wd_s ON withdrawals(status);
        CREATE INDEX IF NOT EXISTS idx_ref ON users(referred_by);
        """)
        for c, ddl in {"multi_flag":"INTEGER DEFAULT 0","is_test":"INTEGER DEFAULT 0","last_name":"TEXT DEFAULT ''","device_hash":"TEXT DEFAULT ''","ip_hash":"TEXT DEFAULT ''","risk_score":"INTEGER DEFAULT 0","risk_flags":"TEXT DEFAULT ''"}.items():
            if not _col(conn, "users", c): conn.execute(f"ALTER TABLE users ADD COLUMN {c} {ddl}")
        if conn.execute("SELECT COUNT(*) c FROM required_channels").fetchone()["c"] == 0:
            now = int(time.time())
            for i, c in enumerate(DEFAULT_CHANNELS):
                conn.execute("INSERT OR IGNORE INTO required_channels(username,name,url,active,sort_order,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                             (c["username"], c["name"], c["url"], 1, i, now, now))
        for k, v in {"daily_reward":DEFAULT_DAILY,"referral_reward":DEFAULT_REFERRAL,"minimum_withdrawal":DEFAULT_MIN_WITHDRAW,"maintenance_mode":"0"}.items():
            conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, str(v)))
        conn.commit()
    finally: conn.close()

def get_setting(k, d=None, kind=float):
    conn = db()
    try:
        r = conn.execute("SELECT value FROM settings WHERE key=?", (k,)).fetchone()
        if not r: return d
        try:
            if kind == float: return float(r["value"])
            if kind == int: return int(float(r["value"]))
            return r["value"]
        except: return d
    finally: conn.close()

def set_setting(k, v):
    conn = db()
    try:
        conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, str(v)))
        conn.commit()
    finally: conn.close()

def _r2(x): return round(float(x) + 1e-9, 2)

def is_payment_day():
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Africa/Addis_Ababa")
        return datetime.now(tz).weekday() != 6
    except:
        return datetime.utcnow().weekday() != 6

def credit(uid, amount, kind, desc="", ref="", admin_id=None):
    amount = _r2(amount)
    if amount <= 0: return False, "Invalid"
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        r = conn.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()
        if not r: conn.execute("ROLLBACK"); return False, "No user"
        before = float(r["balance"]); after = _r2(before + amount)
        conn.execute("UPDATE users SET balance=?, total_earned=ROUND(total_earned+?,8), updated_at=? WHERE user_id=?",
                     (after, amount, int(time.time()), uid))
        col = {"daily":"daily_earnings","referral":"referral_earnings","task":"task_earnings","admin":"admin_credits"}.get(kind)
        if col: conn.execute(f"UPDATE users SET {col}=ROUND({col}+?,8) WHERE user_id=?", (amount, uid))
        conn.execute("INSERT INTO transactions(user_id,type,amount,balance_before,balance_after,description,reference_id,admin_id,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                     (uid, kind.upper()+"_CREDIT", amount, before, after, desc, str(ref), admin_id, int(time.time())))
        conn.execute("COMMIT")
        return True, after
    except Exception as e:
        try: conn.execute("ROLLBACK")
        except: pass
        return False, str(e)
    finally: conn.close()

def debit(uid, amount, kind, desc="", ref="", admin_id=None):
    amount = _r2(amount)
    if amount <= 0: return False, "Invalid"
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        r = conn.execute("SELECT balance FROM users WHERE user_id=?", (uid,)).fetchone()
        if not r: conn.execute("ROLLBACK"); return False, "No user"
        before = float(r["balance"])
        if before < amount: conn.execute("ROLLBACK"); return False, "Insufficient"
        after = _r2(before - amount)
        conn.execute("UPDATE users SET balance=?, updated_at=? WHERE user_id=?", (after, int(time.time()), uid))
        conn.execute("INSERT INTO transactions(user_id,type,amount,balance_before,balance_after,description,reference_id,admin_id,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                     (uid, kind.upper(), amount, before, after, desc, str(ref), admin_id, int(time.time())))
        conn.execute("COMMIT")
        return True, after
    except Exception as e:
        try: conn.execute("ROLLBACK")
        except: pass
        return False, str(e)
    finally: conn.close()

def ensure_user(uid, username="", first_name="", last_name="", referred_by=None):
    now = int(time.time())
    conn = db()
    try:
        r = conn.execute("SELECT user_id, referred_by FROM users WHERE user_id=?", (uid,)).fetchone()
        if not r:
            conn.execute("INSERT INTO users(user_id,username,first_name,last_name,referred_by,created_at,updated_at,last_active) VALUES(?,?,?,?,?,?,?,?)",
                         (uid, username or "", first_name or "", last_name or "", referred_by, now, now, now))
        else:
            conn.execute("UPDATE users SET username=?, first_name=?, last_name=?, last_active=?, updated_at=? WHERE user_id=?",
                         (username or "", first_name or "", last_name or "", now, now, uid))
            if referred_by and not r["referred_by"] and referred_by != uid:
                conn.execute("UPDATE users SET referred_by=? WHERE user_id=?", (referred_by, uid))
        conn.commit()
    finally: conn.close()

def get_user(uid):
    conn = db()
    try: return conn.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
    finally: conn.close()

def is_admin(uid): return int(uid) in ADMIN_IDS
def is_banned(uid):
    u = get_user(uid); return bool(u and u["banned"])

def log_admin(aid, action, target="", before="", after=""):
    conn = db()
    try:
        conn.execute("INSERT INTO admin_logs(admin_id,action,target,before_value,after_value,created_at) VALUES(?,?,?,?,?,?)",
                     (aid, action, str(target), str(before), str(after), int(time.time())))
        conn.commit()
    finally: conn.close()

def add_risk(uid, pts, flag, details=""):
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        r = conn.execute("SELECT risk_score, risk_flags FROM users WHERE user_id=?", (uid,)).fetchone()
        if not r: conn.execute("ROLLBACK"); return
        ns = min(999, int(r["risk_score"] or 0) + int(pts))
        flags = [f for f in (r["risk_flags"] or "").split(",") if f]
        if flag and flag not in flags: flags.append(flag)
        conn.execute("UPDATE users SET risk_score=?, risk_flags=?, updated_at=? WHERE user_id=?",
                     (ns, ",".join(flags), int(time.time()), uid))
        conn.execute("INSERT INTO fraud_events(user_id,event_type,risk_score,details,created_at) VALUES(?,?,?,?,?)",
                     (uid, flag, pts, details, int(time.time())))
        conn.execute("COMMIT")
    except:
        try: conn.execute("ROLLBACK")
        except: pass
    finally: conn.close()

def get_referral_count(uid):
    conn = db()
    try: return int(conn.execute("SELECT COUNT(*) c FROM users WHERE referred_by=? AND referral_paid=1", (uid,)).fetchone()["c"])
    finally: conn.close()

def get_all_referrals(uid):
    conn = db()
    try:
        return conn.execute("SELECT user_id,username,first_name,last_name,verified,referral_paid,created_at FROM users WHERE referred_by=? ORDER BY user_id DESC",
                            (uid,)).fetchall()
    finally: conn.close()

def pay_referral_if_eligible(uid):
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        child = conn.execute("SELECT referred_by, verified, referral_paid, device_hash, ip_hash, created_at FROM users WHERE user_id=?", (uid,)).fetchone()
        if not child or not child["verified"] or child["referral_paid"]:
            conn.execute("ROLLBACK"); return None, None
        ref_id = child["referred_by"]
        if not ref_id or ref_id == uid:
            conn.execute("UPDATE users SET referral_paid=1 WHERE user_id=?", (uid,)); conn.execute("COMMIT"); return None, None
        ref = conn.execute("SELECT banned, device_hash FROM users WHERE user_id=?", (ref_id,)).fetchone()
        if not ref or ref["banned"]:
            conn.execute("UPDATE users SET referral_paid=1 WHERE user_id=?", (uid,)); conn.execute("COMMIT"); return None, None
        multi = False; reason = ""
        if child["device_hash"] and ref["device_hash"] and child["device_hash"] == ref["device_hash"]:
            multi = True; reason = "Same device as referrer"
        reward = get_setting("referral_reward", DEFAULT_REFERRAL, kind=float)
        cur = conn.execute("UPDATE users SET referral_paid=1 WHERE user_id=? AND referral_paid=0", (uid,))
        if cur.rowcount != 1:
            conn.execute("ROLLBACK"); return None, None
        if multi:
            conn.execute("UPDATE users SET multi_flag=1, risk_score=risk_score+30 WHERE user_id IN (?,?)", (uid, ref_id))
        conn.execute("COMMIT")
    except:
        try: conn.execute("ROLLBACK")
        except: pass
        return None, None
    finally: conn.close()
    ok, _ = credit(ref_id, reward, "referral", f"Referral reward — user {uid}", ref=str(uid))
    return (reward if ok else None), ({"multi": True, "reason": reason, "referrer": ref_id} if multi else None)

def claim_daily(uid):
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        r = conn.execute("SELECT banned, verified, daily_last_claim FROM users WHERE user_id=?", (uid,)).fetchone()
        if not r: conn.execute("ROLLBACK"); return False, {"error":"user_not_found"}
        if r["banned"]: conn.execute("ROLLBACK"); return False, {"error":"banned"}
        if not r["verified"]: conn.execute("ROLLBACK"); return False, {"error":"not_verified"}
        last = int(r["daily_last_claim"] or 0); now = int(time.time())
        if last and (now - last) < 86400:
            conn.execute("ROLLBACK"); return False, {"error":"cooldown","remaining":86400-(now-last)}
        reward = get_setting("daily_reward", DEFAULT_DAILY, kind=float)
        cur = conn.execute("UPDATE users SET daily_last_claim=? WHERE user_id=? AND (daily_last_claim=0 OR ?-daily_last_claim >= 86400)",
                           (now, uid, now))
        if cur.rowcount != 1:
            conn.execute("ROLLBACK"); return False, {"error":"cooldown","remaining":86400}
        conn.execute("COMMIT")
    except:
        try: conn.execute("ROLLBACK")
        except: pass
        return False, {"error":"server_error"}
    finally: conn.close()
    ok, bal = credit(uid, reward, "daily", "Daily bonus")
    if not ok: return False, {"error":"credit_failed"}
    return True, {"reward":reward,"balance":bal}

def daily_status(uid):
    u = get_user(uid)
    if not u: return {"available":False,"remaining":0,"reward":0}
    last = int(u["daily_last_claim"] or 0); now = int(time.time())
    reward = get_setting("daily_reward", DEFAULT_DAILY, kind=float)
    if not last or (now - last) >= 86400:
        return {"available":True,"remaining":0,"reward":reward}
    return {"available":False,"remaining":86400-(now-last),"reward":reward}

def validate_wallet(wt, num):
    wt = (wt or "").strip().lower(); num = (num or "").strip()
    if wt == "cbe":
        if not re.fullmatch(r"1000\d{9}", num): return False, "CBE 13 digits, starts with 1000"
        return True, "CBE"
    if wt == "telebirr":
        if not re.fullmatch(r"(09|07)\d{8}", num): return False, "Telebirr 10 digits, starts 09 or 07"
        return True, "Telebirr"
    return False, "Invalid type"

def save_wallet(uid, wt, num):
    ok, res = validate_wallet(wt, num)
    if not ok: return False, res, False
    conn = db()
    try:
        dup = conn.execute("SELECT COUNT(*) c FROM users WHERE wallet_number=? AND user_id!=?", (num, uid)).fetchone()["c"]
        susp = dup > 0
        conn.execute("UPDATE users SET wallet_type=?, wallet_number=?, wallet_suspicious=?, updated_at=? WHERE user_id=?",
                     (res, num, 1 if susp else 0, int(time.time()), uid))
        conn.commit()
    finally: conn.close()
    if susp: add_risk(uid, 40, "duplicate_wallet", f"Shared with {dup}")
    return True, "Wallet saved", susp

def create_withdrawal(uid, amount):
    amount = _r2(amount)
    minimum = get_setting("minimum_withdrawal", DEFAULT_MIN_WITHDRAW, kind=float)
    if amount < minimum: return False, f"Minimum withdrawal is {minimum:.2f} ETB"
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        u = conn.execute("SELECT banned, wallet_type, wallet_number, balance, risk_score, multi_flag FROM users WHERE user_id=?", (uid,)).fetchone()
        if not u: conn.execute("ROLLBACK"); return False, "User not found"
        if u["banned"]: conn.execute("ROLLBACK"); return False, "Account banned"
        if not u["wallet_type"] or not u["wallet_number"]: conn.execute("ROLLBACK"); return False, "Save wallet first"
        if float(u["balance"]) < amount: conn.execute("ROLLBACK"); return False, "Insufficient balance"
        pending = conn.execute("SELECT id FROM withdrawals WHERE user_id=? AND status='pending' LIMIT 1", (uid,)).fetchone()
        if pending: conn.execute("ROLLBACK"); return False, "You have a pending withdrawal"
        risk_status = "flagged" if (u["risk_score"] or 0) >= 50 or u["multi_flag"] else "normal"
        cur = conn.execute("INSERT INTO withdrawals(user_id,amount,wallet_type,wallet_number,status,risk_status,created_at) VALUES(?,?,?,?,?,?,?)",
                           (uid, amount, u["wallet_type"], u["wallet_number"], "pending", risk_status, int(time.time())))
        wid = cur.lastrowid
        conn.execute("COMMIT")
    except:
        try: conn.execute("ROLLBACK")
        except: pass
        return False, "Server error"
    finally: conn.close()
    ok, _ = debit(uid, amount, "withdrawal_hold", f"Withdrawal #{wid}")
    if not ok:
        conn = db()
        try: conn.execute("DELETE FROM withdrawals WHERE id=?", (wid,)); conn.commit()
        finally: conn.close()
        return False, "Balance error"
    return True, {"withdrawal_id": wid, "amount": amount, "risk_status": risk_status}

def approve_withdrawal(wid, aid):
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        w = conn.execute("SELECT * FROM withdrawals WHERE id=? AND status='pending'", (wid,)).fetchone()
        if not w: conn.execute("ROLLBACK"); return False, "Not pending"
        conn.execute("UPDATE withdrawals SET status='approved', admin_id=?, reviewed_at=? WHERE id=?", (aid, int(time.time()), wid))
        conn.execute("UPDATE users SET total_withdrawn=ROUND(total_withdrawn+?,8) WHERE user_id=?", (float(w["amount"]), w["user_id"]))
        conn.execute("COMMIT")
        return True, dict(w)
    except:
        try: conn.execute("ROLLBACK")
        except: pass
        return False, "Error"
    finally: conn.close()

def reject_withdrawal(wid, aid, reason=""):
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        w = conn.execute("SELECT * FROM withdrawals WHERE id=? AND status='pending'", (wid,)).fetchone()
        if not w: conn.execute("ROLLBACK"); return False, "Not pending"
        conn.execute("UPDATE withdrawals SET status='rejected', admin_id=?, reviewed_at=?, rejection_reason=? WHERE id=?",
                     (aid, int(time.time()), reason or "", wid))
        conn.execute("COMMIT")
    except:
        try: conn.execute("ROLLBACK")
        except: pass
        return False, "Error"
    finally: conn.close()
    credit(int(w["user_id"]), float(w["amount"]), "admin", f"Withdrawal #{wid} refund", admin_id=aid)
    return True, dict(w)

def get_channels(active_only=True):
    conn = db()
    try:
        sql = "SELECT * FROM required_channels " + ("WHERE active=1 " if active_only else "") + "ORDER BY sort_order ASC, id ASC"
        return conn.execute(sql).fetchall()
    finally: conn.close()

def get_tasks(active_only=True):
    conn = db()
    try:
        sql = "SELECT * FROM tasks " + ("WHERE active=1 " if active_only else "") + "ORDER BY id DESC"
        return conn.execute(sql).fetchall()
    finally: conn.close()

def get_user_task_status(uid, tid):
    conn = db()
    try: return conn.execute("SELECT * FROM task_submissions WHERE user_id=? AND task_id=? ORDER BY id DESC LIMIT 1", (uid, tid)).fetchone()
    finally: conn.close()

def submit_task(uid, tid, pt="", pi=""):
    if not (pt or pi): return False, "Proof required"
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        t = conn.execute("SELECT * FROM tasks WHERE id=? AND active=1", (tid,)).fetchone()
        if not t: conn.execute("ROLLBACK"); return False, "Task not found"
        last = conn.execute("SELECT status FROM task_submissions WHERE user_id=? AND task_id=? ORDER BY id DESC LIMIT 1", (uid, tid)).fetchone()
        if last and last["status"] == "pending": conn.execute("ROLLBACK"); return False, "Previous submission pending"
        if last and last["status"] == "approved": conn.execute("ROLLBACK"); return False, "Already approved"
        cur = conn.execute("INSERT INTO task_submissions(task_id,user_id,proof_text,proof_image,status,created_at) VALUES(?,?,?,?,?,?)",
                           (tid, uid, pt[:2000], pi[:500], "pending", int(time.time())))
        sid = cur.lastrowid
        conn.execute("COMMIT")
        return True, {"submission_id": sid, "task": dict(t)}
    except:
        try: conn.execute("ROLLBACK")
        except: pass
        return False, "Error"
    finally: conn.close()

def approve_task_submission(sid, aid):
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        s = conn.execute("SELECT ts.*, t.reward, t.title FROM task_submissions ts JOIN tasks t ON t.id=ts.task_id WHERE ts.id=? AND ts.status='pending'", (sid,)).fetchone()
        if not s: conn.execute("ROLLBACK"); return False, "Not pending"
        conn.execute("UPDATE task_submissions SET status='approved', admin_id=?, reviewed_at=? WHERE id=?", (aid, int(time.time()), sid))
        conn.execute("COMMIT")
    except:
        try: conn.execute("ROLLBACK")
        except: pass
        return False, "Error"
    finally: conn.close()
    credit(int(s["user_id"]), float(s["reward"]), "task", f"Task: {s['title']}", ref=str(sid))
    return True, dict(s)

def reject_task_submission(sid, aid, reason=""):
    conn = db()
    try:
        conn.execute("UPDATE task_submissions SET status='rejected', admin_id=?, reviewed_at=?, rejection_reason=? WHERE id=? AND status='pending'",
                     (aid, int(time.time()), reason or "", sid))
        conn.commit()
        return True
    finally: conn.close()

# ─── Telegram API ───
async def tg(method, data=None):
    if not BOT_TOKEN: return {"ok": False}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(f"{TELEGRAM_API}/{method}", json=data or {})
            try: return r.json()
            except: return {"ok": False}
    except: return {"ok": False}

async def send(chat_id, text, kb=None):
    d = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if kb: d["reply_markup"] = kb
    return await tg("sendMessage", d)

async def send_photo(chat_id, photo_id, caption="", kb=None):
    d = {"chat_id": chat_id, "photo": photo_id, "caption": caption, "parse_mode": "HTML"}
    if kb: d["reply_markup"] = kb
    return await tg("sendPhoto", d)

async def send_admin(text, kb=None):
    for aid in ADMIN_IDS: await send(aid, text, kb)

async def send_admin_photo(photo_id, caption="", kb=None):
    for aid in ADMIN_IDS: await send_photo(aid, photo_id, caption, kb)

async def check_channel_membership(uid, ch):
    r = await tg("getChatMember", {"chat_id": ch, "user_id": uid})
    if not r.get("ok"):
        err = r.get("description", "unknown")
        print(f"[CHANNEL-CHECK] FAILED for {ch}: {err}")
        return False
    st = r.get("result", {}).get("status")
    if st in {"member","administrator","creator"}: return True
    if st == "restricted" and r.get("result", {}).get("is_member") is True: return True
    return False

async def check_all_channels_parallel(uid):
    """PARALLEL check — much faster"""
    chans = get_channels(active_only=True)
    if not chans:
        return False, []
    tasks = [check_channel_membership(uid, c["username"]) for c in chans]
    results = await asyncio.gather(*tasks)
    out = []
    for c, joined in zip(chans, results):
        out.append({
            "id": c["id"], "username": c["username"], "name": c["name"], "url": c["url"], "joined": joined
        })
    all_joined = all(x["joined"] for x in out) and len(out) > 0
    return all_joined, out

async def verify_all_channels(uid):
    return await check_all_channels_parallel(uid)

def make_captcha(uid):
    a = secrets.randbelow(8) + 3
    b = secrets.randbelow(8) + 2
    op = secrets.choice(["+","-"])
    if op == "+": ans = a+b
    else:
        if a<b: a,b = b,a
        ans = a-b
    q = f"{a} {op} {b} = ?"
    t = secrets.token_urlsafe(24)
    conn = db()
    try:
        conn.execute("DELETE FROM captcha_sessions WHERE user_id=?", (uid,))
        conn.execute("INSERT INTO captcha_sessions(token,user_id,question,answer,attempts,created_at,expires_at) VALUES(?,?,?,?,?,?,?)",
                     (t, uid, q, str(ans), 0, int(time.time()), int(time.time())+600))
        conn.commit()
    finally: conn.close()
    return t, q

def verify_captcha(t, ans):
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        r = conn.execute("SELECT * FROM captcha_sessions WHERE token=?", (t,)).fetchone()
        if not r: conn.execute("ROLLBACK"); return False, "expired", None, None
        if int(r["expires_at"]) < int(time.time()):
            conn.execute("DELETE FROM captcha_sessions WHERE token=?", (t,)); conn.execute("COMMIT")
            return False, "expired", None, None
        if int(r["attempts"]) >= 5:
            conn.execute("DELETE FROM captcha_sessions WHERE token=?", (t,)); conn.execute("COMMIT")
            return False, "too_many", None, None
        if str(r["answer"]).strip() != str(ans).strip():
            conn.execute("DELETE FROM captcha_sessions WHERE token=?", (t,))
            conn.execute("COMMIT")
            conn2 = db()
            try:
                a = secrets.randbelow(8) + 3; b = secrets.randbelow(8) + 2
                op = secrets.choice(["+","-"])
                if op == "+": nans = a+b
                else:
                    if a<b: a,b = b,a
                    nans = a-b
                nq = f"{a} {op} {b} = ?"
                nt = secrets.token_urlsafe(24)
                conn2.execute("INSERT INTO captcha_sessions(token,user_id,question,answer,attempts,created_at,expires_at) VALUES(?,?,?,?,?,?,?)",
                              (nt, r["user_id"], nq, str(nans), 0, int(time.time()), int(time.time())+600))
                conn2.commit()
            finally: conn2.close()
            return False, "wrong", nt, nq
        conn.execute("UPDATE users SET captcha_passed=1 WHERE user_id=?", (r["user_id"],))
        conn.execute("DELETE FROM captcha_sessions WHERE token=?", (t,))
        conn.execute("COMMIT"); return True, "ok", None, None
    except:
        try: conn.execute("ROLLBACK")
        except: pass
        return False, "error", None, None
    finally: conn.close()

def parse_ref(text):
    parts = text.split(maxsplit=1)
    if len(parts) != 2: return None
    p = parts[1].strip()
    if p.startswith("ref_") and p[4:].isdigit(): return int(p[4:])
    if p.isdigit(): return int(p)
    return None

WELCOME_MSG = (
    "⚡ <b>ወደ Mega Spark እንኳን በደህና መጡ</b>\n\n"
    "💰 ያግኙ እና ተግባሮችን ያጠናቅቁ\n"
    "🎁 የቀን ሽልማቶች\n"
    "👥 የሪፈራል ሽልማቶች\n"
    "🚀 አዲስ እድሎች\n\n"
    "💱 USDT እና ማስታወቂያ\n"
    f"📣 አግኙን: {SUPPORT_USERNAME}\n\n"
    "⚠️ <b>አንድ ሰው አንድ አካውንት ብቻ</b>\n"
    "ብዙ አካውንት መጠቀም = ክፍያ ውድቅ\n\n"
    "ለመጀመር ከታች ያለውን የ Menu ቁልፍ ይጫኑ 👇"
)

def wd_kb(wid):
    return {"inline_keyboard": [
        [{"text": "✅ አጽድቅ", "callback_data": f"wdok:{wid}"},
         {"text": "❌ ውድቅ አድርግ", "callback_data": f"wdno:{wid}"}],
        [{"text": "👥 ሪፈራሎች", "callback_data": f"wdrefs:{wid}:0"},
         {"text": "📊 ሙሉ መረጃ", "callback_data": f"wdaudit:{wid}"}],
        [{"text": "🚫 ተጠቃሚውን አግድ", "callback_data": f"wdban:{wid}"}],
    ]}

def sub_kb(sid):
    return {"inline_keyboard": [[{"text":"✅ አጽድቅ","callback_data":f"tskok:{sid}"},{"text":"❌ ውድቅ","callback_data":f"tskno:{sid}"}]]}

def fmt_user(u):
    name = html.escape((u["first_name"] or "") + (" " + u["last_name"] if u["last_name"] else "") or u["username"] or str(u["user_id"]))
    un = f"@{html.escape(u['username'])}" if u["username"] else "—"
    return f"<b>{name}</b> ({un})\n🆔 <code>{u['user_id']}</code>"

async def send_withdrawal_admin(wid):
    conn = db()
    try:
        w = conn.execute("SELECT * FROM withdrawals WHERE id=?", (wid,)).fetchone()
        if not w: return
        u = conn.execute("SELECT * FROM users WHERE user_id=?", (w["user_id"],)).fetchone()
        if not u: return
        refs_total = int(conn.execute("SELECT COUNT(*) c FROM users WHERE referred_by=?", (u["user_id"],)).fetchone()["c"])
        refs_paid = int(conn.execute("SELECT COUNT(*) c FROM users WHERE referred_by=? AND referral_paid=1", (u["user_id"],)).fetchone()["c"])
        multi_count = 0
        if u["device_hash"]:
            multi_count = int(conn.execute("SELECT COUNT(DISTINCT user_id) c FROM users WHERE device_hash=? AND user_id!=?", (u["device_hash"], u["user_id"])).fetchone()["c"])
    finally: conn.close()
    risk = "🟢 ጥሩ"
    if u["multi_flag"] or multi_count >= 3: risk = "🔴 ከፍተኛ አደጋ"
    elif (u["risk_score"] or 0) >= 30: risk = "🟡 መመርመር ያስፈልጋል"
    day_note = "✅ የክፍያ ቀን" if is_payment_day() else "🛑 እሁድ — ክፍያ የለም"
    text = (
        f"💸 <b>አዲስ የዊዝድሮ ጥያቄ</b>\n\n"
        f"{fmt_user(u)}\n"
        f"🌐 IP: <code>{html.escape(u['ip_hash'] or 'unknown')}</code>\n"
        f"📱 Device: <code>{html.escape((u['device_hash'] or 'unknown')[:20])}</code>\n\n"
        f"💰 <b>መጠን: {w['amount']:.2f} ETB</b>\n"
        f"🏦 {html.escape(w['wallet_type'])}: <code>{html.escape(w['wallet_number'])}</code>\n\n"
        f"<b>📊 ገቢ ማጠቃለያ</b>\n"
        f"├ 🎁 ቦነስ: {float(u['daily_earnings'] or 0):.2f}\n"
        f"├ 👥 ሪፈራል: {float(u['referral_earnings'] or 0):.2f}\n"
        f"├ 📋 ታስክ: {float(u['task_earnings'] or 0):.2f}\n"
        f"├ 💼 አድሚን: {float(u['admin_credits'] or 0):.2f}\n"
        f"└ <b>ጠቅላላ: {float(u['total_earned'] or 0):.2f} ETB</b>\n\n"
        f"<b>👥 ሪፈራሎች</b>: {refs_total} ጠቅላላ, {refs_paid} የተከፈሉ\n"
        f"ተመሳሳይ ስልክ ተጠቃሚ: {multi_count}\n\n"
        f"<b>🛡 ስጋት</b>: {risk} ({u['risk_score'] or 0})\n"
        f"Multi-flag: {'🚨 አዎ' if u['multi_flag'] else 'አይ'}\n"
        f"📅 {day_note}"
    )
    await send_admin(text, wd_kb(wid))

async def send_submission_admin(sid):
    conn = db()
    try:
        s = conn.execute("SELECT ts.*, t.title, t.reward FROM task_submissions ts JOIN tasks t ON t.id=ts.task_id WHERE ts.id=?", (sid,)).fetchone()
        if not s: return
        u = conn.execute("SELECT * FROM users WHERE user_id=?", (s["user_id"],)).fetchone()
    finally: conn.close()
    if not s or not u: return
    cap = (
        f"📋 <b>አዲስ የታስክ ማስረጃ #{sid}</b>\n\n"
        f"{fmt_user(u)}\n\n"
        f"📌 ታስክ: <b>{html.escape(s['title'])}</b>\n"
        f"💰 ሽልማት: {s['reward']:.2f} ETB\n\n"
        f"መግለጫ: {html.escape(s['proof_text'] or '—')}"
    )
    if s["proof_image"]:
        await send_admin_photo(s["proof_image"], cap, sub_kb(sid))
    else:
        await send_admin(cap, sub_kb(sid))

async def user_audit(cid, tid):
    u = get_user(tid)
    if not u: await send(cid, "ተጠቃሚ አልተገኘም"); return
    refs = get_all_referrals(tid)
    refs_paid = get_referral_count(tid)
    text = (
        f"👤 <b>ተጠቃሚ መረጃ</b>\n\n"
        f"ስም: {html.escape(u['first_name'] or '')} {html.escape(u['last_name'] or '')}\n"
        f"@{html.escape(u['username'] or 'none')}\n"
        f"🆔 <code>{u['user_id']}</code>\n"
        f"🌐 IP: <code>{html.escape(u['ip_hash'] or '?')}</code>\n"
        f"📱 Device: <code>{html.escape((u['device_hash'] or '?')[:20])}</code>\n\n"
        f"💼 ባላንስ: <b>{float(u['balance'] or 0):.2f}</b>\n"
        f"📈 ጠቅላላ ገቢ: {float(u['total_earned'] or 0):.2f}\n"
        f"📉 ጠቅላላ ወጪ: {float(u['total_withdrawn'] or 0):.2f}\n"
        f"🎁 ቦነስ: {float(u['daily_earnings'] or 0):.2f}\n"
        f"👥 ሪፈራል: {float(u['referral_earnings'] or 0):.2f}\n"
        f"📋 ታስክ: {float(u['task_earnings'] or 0):.2f}\n\n"
        f"👥 ሪፈራሎች: {len(refs)} ({refs_paid} የተከፈሉ)\n"
        f"🚫 Multi-flag: {'አዎ' if u['multi_flag'] else 'አይ'}\n"
        f"🛡 ስጋት: {u['risk_score'] or 0} — {html.escape(u['risk_flags'] or 'none')}"
    )
    await send(cid, text)

async def admin_dash(cid):
    conn = db()
    try:
        users = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        verified = conn.execute("SELECT COUNT(*) c FROM users WHERE verified=1").fetchone()["c"]
        banned = conn.execute("SELECT COUNT(*) c FROM users WHERE banned=1").fetchone()["c"]
        multi = conn.execute("SELECT COUNT(*) c FROM users WHERE multi_flag=1").fetchone()["c"]
        flagged = conn.execute("SELECT COUNT(*) c FROM users WHERE risk_score>=30").fetchone()["c"]
        tb = conn.execute("SELECT COALESCE(SUM(balance),0) s FROM users").fetchone()["s"]
        te = conn.execute("SELECT COALESCE(SUM(total_earned),0) s FROM users").fetchone()["s"]
        tw = conn.execute("SELECT COALESCE(SUM(total_withdrawn),0) s FROM users").fetchone()["s"]
        pw = conn.execute("SELECT COUNT(*) c FROM withdrawals WHERE status='pending'").fetchone()["c"]
        pt = conn.execute("SELECT COUNT(*) c FROM task_submissions WHERE status='pending'").fetchone()["c"]
    finally: conn.close()
    ref_rate = get_setting("referral_reward", DEFAULT_REFERRAL, kind=float)
    day_rate = get_setting("daily_reward", DEFAULT_DAILY, kind=float)
    min_wd = get_setting("minimum_withdrawal", DEFAULT_MIN_WITHDRAW, kind=float)
    payment_day = is_payment_day()
    await send(cid,
        f"🛡 <b>Mega Spark Admin Panel</b>\n\n"
        f"👥 ተጠቃሚዎች: <b>{users}</b>  ✅ {verified}\n"
        f"🚫 የተከለከሉ: {banned}  🚨 Multi: {multi}  ⚠️ Flagged: {flagged}\n"
        f"💼 ጠቅላላ ባላንስ: <b>{tb:.2f} ETB</b>\n"
        f"📈 ጠቅላላ ገቢ: {te:.2f}  📉 ጠቅላላ ወጪ: {tw:.2f}\n\n"
        f"💸 በመጠባበቅ ላይ ያለ ዊዝድሮ: <b>{pw}</b>\n"
        f"📋 በመጠባበቅ ላይ ያለ ታስክ: <b>{pt}</b>\n\n"
        f"<b>⚙️ የአሁኑ ቅንብሮች</b>\n"
        f"👥 ሪፈራል: <b>{ref_rate:.2f} ETB</b>\n"
        f"🎁 ዴይሊ: <b>{day_rate:.2f} ETB</b>\n"
        f"💸 ሚኒማም ዊዝድሮ: <b>{min_wd:.2f} ETB</b>\n"
        f"📅 ዛሬ: {'✅ የክፍያ ቀን' if payment_day else '🛑 እሁድ'}\n\n"
        "<b>📋 Commands</b>\n"
        "/admin — ዳሽቦርድ\n/stats — ስታቲስቲክስ\n/checkuser ID\n"
        "/addbalance ID AMT\n/testbalance ID AMT\n/ban ID [reason]\n/unban ID\n"
        "/setref AMT\n/setdaily AMT\n/setminwithdraw AMT\n"
        "/channels\n/addchannel @u | Name | URL\n/removechannel @u\n/togglechannel @u\n/editchannel @old | @new | Name | URL\n"
        "/addtask Title | Desc | Reward | URL\n/deltask ID\n/tasks\n/withdrawals\n/maintenance")

# ─── Bot handlers ───
async def handle_message(msg):
    chat = msg.get("chat", {}); user = msg.get("from", {})
    cid = chat.get("id"); uid = user.get("id")
    if not cid or not uid: return
    text = (msg.get("text") or "").strip()
    caption = (msg.get("caption") or "").strip()
    photo = msg.get("photo") or []

    ref = parse_ref(text) if text.startswith("/start") else None
    ensure_user(uid, user.get("username",""), user.get("first_name",""), user.get("last_name",""), ref)

    if is_banned(uid) and not is_admin(uid):
        await send(cid, f"🚫 አካውንትዎ ተከልክሏል።\n📞 ድጋፍ: {SUPPORT_USERNAME}"); return

    if photo and caption:
        await handle_photo_proof(uid, cid, caption, photo[-1]["file_id"]); return
    if photo and not caption:
        await send(cid, "⚠️ <b>መግለጫ ያስፈልጋል</b>\n\nScreenshot ከታስክ ኮድ ጋር ይላኩ።\n\nምሳሌ: <code>#T5</code>"); return

    if text.startswith("/start"):
        await send(cid, WELCOME_MSG); return

    if text == "/id":
        await send(cid, f"🆔 <code>{uid}</code>"); return

    if text == "/help":
        await send(cid,
            "⚡ <b>Mega Spark እርዳታ</b>\n\n"
            "1. Menu ቁልፍ ተጭነው ይክፈቱ\n2. Captcha ያረጋግጡ\n"
            "3. ቻናሎቹን ይቀላቀሉ\n4. ያግኙ\n5. ከ 30 ETB በላይ ሲሆን ያውጡ\n\n"
            "⚠️ ብዙ አካውንት = ክፍያ ውድቅ\n\n"
            f"📞 ድጋፍ: {SUPPORT_USERNAME}")
        return

    if not is_admin(uid):
        await send(cid, "ጀምር ለማድረግ /start ይላኩ ወይም Menu ቁልፍ ይጫኑ 🚀")
        return

    if text.startswith("/admin") or text.startswith("/stats"):
        await admin_dash(cid); return

    if text.startswith("/checkuser"):
        p = text.split()
        if len(p) != 2 or not p[1].isdigit(): await send(cid, "አጠቃቀም: /checkuser ID"); return
        await user_audit(cid, int(p[1])); return

    if text.startswith("/addbalance"):
        p = text.split()
        if len(p) != 3: await send(cid, "አጠቃቀም: /addbalance ID AMT"); return
        try: tid = int(p[1]); amt = float(p[2])
        except: await send(cid, "ልክ ያልሆነ ቁጥር"); return
        if not get_user(tid): await send(cid, "ተጠቃሚ አልተገኘም"); return
        if amt > 0: credit(tid, amt, "admin", f"Admin {uid}", admin_id=uid)
        else: debit(tid, abs(amt), "admin", f"Admin {uid}", admin_id=uid)
        log_admin(uid, "addbalance", tid, "", amt)
        await send(cid, f"✅ {amt:+.2f} ETB ለ {tid}"); return

    if text.startswith("/testbalance"):
        p = text.split()
        if len(p) != 3: await send(cid, "አጠቃቀም: /testbalance ID AMT"); return
        try: tid = int(p[1]); amt = float(p[2])
        except: await send(cid, "ልክ ያልሆነ ቁጥር"); return
        if not get_user(tid): await send(cid, "ተጠቃሚ አልተገኘም"); return
        conn = db()
        try:
            conn.execute("UPDATE users SET is_test=1 WHERE user_id=?", (tid,)); conn.commit()
        finally: conn.close()
        if amt > 0: credit(tid, amt, "admin", f"TEST balance by {uid}", admin_id=uid)
        elif amt < 0: debit(tid, abs(amt), "admin", f"TEST deduct by {uid}", admin_id=uid)
        log_admin(uid, "testbalance", tid, "", amt)
        await send(cid, f"🧪 የቴስት ባላንስ {amt:+.2f} ETB ለ {tid}"); return

    if text.startswith("/ban"):
        p = text.split()
        if len(p) < 2 or not p[1].isdigit(): await send(cid, "አጠቃቀም: /ban ID [reason]"); return
        tid = int(p[1]); reason = " ".join(p[2:]) or "Policy"
        conn = db()
        try:
            conn.execute("UPDATE users SET banned=1, ban_reason=?, updated_at=? WHERE user_id=?", (reason, int(time.time()), tid)); conn.commit()
        finally: conn.close()
        log_admin(uid, "ban", tid, "", reason)
        await send(cid, f"🚫 {tid} ተከልክሏል")
        try: await send(tid, f"🚫 አካውንትዎ ተከልክሏል\nምክንያት: {reason}")
        except: pass
        return

    if text.startswith("/unban"):
        p = text.split()
        if len(p) != 2 or not p[1].isdigit(): await send(cid, "አጠቃቀም: /unban ID"); return
        conn = db()
        try:
            conn.execute("UPDATE users SET banned=0, ban_reason='', updated_at=? WHERE user_id=?", (int(time.time()), int(p[1]))); conn.commit()
        finally: conn.close()
        log_admin(uid, "unban", p[1])
        await send(cid, "✅ ተከፍቷል"); return

    if text.startswith("/setref"):
        p = text.split()
        if len(p) != 2: await send(cid, "አጠቃቀም: /setref AMOUNT"); return
        try: v = float(p[1])
        except: await send(cid, "ልክ ያልሆነ ቁጥር"); return
        old = get_setting("referral_reward", DEFAULT_REFERRAL, kind=float)
        set_setting("referral_reward", v); log_admin(uid, "setref", "", old, v)
        await send(cid, f"✅ ሪፈራል ዋጋ: <b>{old:.2f}</b> → <b>{v:.2f} ETB</b>"); return

    if text.startswith("/setdaily"):
        p = text.split()
        if len(p) != 2: await send(cid, "አጠቃቀም: /setdaily AMOUNT"); return
        try: v = float(p[1])
        except: await send(cid, "ልክ ያልሆነ ቁጥር"); return
        old = get_setting("daily_reward", DEFAULT_DAILY, kind=float)
        set_setting("daily_reward", v); log_admin(uid, "setdaily", "", old, v)
        await send(cid, f"✅ ዴይሊ: <b>{old:.2f}</b> → <b>{v:.2f} ETB</b>"); return

    if text.startswith("/setminwithdraw"):
        p = text.split()
        if len(p) != 2: await send(cid, "አጠቃቀም: /setminwithdraw AMOUNT"); return
        try: v = float(p[1])
        except: await send(cid, "ልክ ያልሆነ ቁጥር"); return
        old = get_setting("minimum_withdrawal", DEFAULT_MIN_WITHDRAW, kind=float)
        set_setting("minimum_withdrawal", v); log_admin(uid, "setminwithdraw", "", old, v)
        await send(cid, f"✅ ሚኒማም ዊዝድሮ: <b>{old:.2f}</b> → <b>{v:.2f} ETB</b>"); return

    if text == "/channels":
        ch = get_channels(active_only=False)
        lines = ["📢 <b>የግዴታ ቻናሎች</b>\n"]
        for c in ch:
            st = "✅" if c["active"] else "❌"
            lines.append(f"{st} <b>{html.escape(c['name'])}</b> — {html.escape(c['username'])}")
        lines.append("\n/addchannel @u | Name | URL\n/removechannel @u\n/togglechannel @u\n/editchannel @old | @new | Name | URL")
        await send(cid, "\n".join(lines)); return

    if text.startswith("/addchannel"):
        parts = [x.strip() for x in text.split("|", 2)]
        if len(parts) != 3: await send(cid, "አጠቃቀም: /addchannel @u | Name | URL"); return
        first = parts[0].replace("/addchannel","").strip()
        if not first.startswith("@"): first = "@"+first
        conn = db()
        try:
            mx = conn.execute("SELECT COALESCE(MAX(sort_order),0) m FROM required_channels").fetchone()["m"]
            conn.execute("INSERT INTO required_channels(username,name,url,active,sort_order,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                         (first, parts[1], parts[2], 1, int(mx)+1, int(time.time()), int(time.time())))
            conn.commit()
        except sqlite3.IntegrityError:
            await send(cid, "❌ ቀድሞ አለ"); return
        finally: conn.close()
        await send(cid, f"✅ ተጨምሯል: {first}"); return

    if text.startswith("/removechannel"):
        p = text.split()
        if len(p) != 2: await send(cid, "አጠቃቀም: /removechannel @u"); return
        u = p[1] if p[1].startswith("@") else "@"+p[1]
        conn = db()
        try:
            cur = conn.execute("DELETE FROM required_channels WHERE username=?", (u,)); conn.commit()
        finally: conn.close()
        await send(cid, "✅ ተሰርዟል" if cur.rowcount else "❌ አልተገኘም"); return

    if text.startswith("/togglechannel"):
        p = text.split()
        if len(p) != 2: await send(cid, "አጠቃቀም: /togglechannel @u"); return
        u = p[1] if p[1].startswith("@") else "@"+p[1]
        conn = db()
        try:
            r = conn.execute("SELECT active FROM required_channels WHERE username=?", (u,)).fetchone()
            if not r: await send(cid, "❌ አልተገኘም"); return
            n = 0 if r["active"] else 1
            conn.execute("UPDATE required_channels SET active=?, updated_at=? WHERE username=?", (n, int(time.time()), u)); conn.commit()
        finally: conn.close()
        await send(cid, f"✅ አሁን {'ንቁ' if n else 'ተዘግቷል'}"); return

    if text.startswith("/editchannel"):
        parts = [x.strip() for x in text.split("|", 3)]
        if len(parts) != 4: await send(cid, "አጠቃቀም: /editchannel @old | @new | Name | URL"); return
        old = parts[0].replace("/editchannel","").strip()
        if not old.startswith("@"): old = "@"+old
        new, name, url = parts[1], parts[2], parts[3]
        if not new.startswith("@"): new = "@"+new
        conn = db()
        try:
            cur = conn.execute("UPDATE required_channels SET username=?, name=?, url=?, updated_at=? WHERE username=?",
                               (new, name, url, int(time.time()), old)); conn.commit()
        finally: conn.close()
        await send(cid, "✅ ተስተካክሏል" if cur.rowcount else "❌ አልተገኘም"); return

    if text.startswith("/addtask"):
        parts = text.replace("/addtask","",1).strip().split("|")
        if len(parts) != 4: await send(cid, "አጠቃቀም: /addtask Title | Desc | Reward | URL"); return
        try: rw = float(parts[2].strip())
        except: await send(cid, "ልክ ያልሆነ ሽልማት"); return
        conn = db()
        try:
            cur = conn.execute("INSERT INTO tasks(title,description,reward,url,proof_type,active,created_at,created_by) VALUES(?,?,?,?,?,1,?,?)",
                               (parts[0].strip(), parts[1].strip(), rw, parts[3].strip(), "photo", int(time.time()), uid))
            conn.commit(); tid = cur.lastrowid
        finally: conn.close()
        log_admin(uid, "addtask", tid)
        await send(cid, f"✅ ታስክ #{tid} ተፈጥሯል\n\nተጠቃሚዎች screenshot ከ <code>#T{tid}</code> ጋር ይልካሉ"); return

    if text.startswith("/deltask"):
        p = text.split()
        if len(p) != 2 or not p[1].isdigit(): await send(cid, "አጠቃቀም: /deltask ID"); return
        conn = db()
        try:
            conn.execute("UPDATE tasks SET active=0 WHERE id=?", (int(p[1]),)); conn.commit()
        finally: conn.close()
        await send(cid, "✅ ጠፍቷል"); return

    if text == "/tasks":
        ts = get_tasks(False)
        if not ts: await send(cid, "ታስኮች የሉም"); return
        lines = ["📋 <b>ታስኮች</b>"]
        for t in ts:
            st = "✅" if t["active"] else "❌"
            lines.append(f"{st} #{t['id']} {html.escape(t['title'])} — {t['reward']:.2f}")
        await send(cid, "\n".join(lines)); return

    if text == "/withdrawals":
        conn = db()
        try:
            wds = conn.execute("SELECT id FROM withdrawals WHERE status='pending' ORDER BY id ASC LIMIT 10").fetchall()
        finally: conn.close()
        if not wds: await send(cid, "በመጠባበቅ ላይ ያለ ዊዝድሮ የለም"); return
        for w in wds: await send_withdrawal_admin(w["id"])
        return

    if text == "/maintenance":
        cur = get_setting("maintenance_mode", "0", kind=str) == "1"
        set_setting("maintenance_mode", "0" if cur else "1")
        await send(cid, f"✅ የጥገና ሁኔታ: {'ጠፍቷል' if cur else 'ተብርቷል'}"); return

    await send(cid, "ያልታወቀ ትዕዛዝ። /admin ይላኩ")

async def handle_photo_proof(uid, cid, caption, photo_id):
    m = re.search(r"#T(\d+)", caption)
    if not m:
        await send(cid, "⚠️ <b>የታስክ ኮድ የለም</b>\n\nመግለጫው የታስክ ID መያዝ አለበት።\nምሳሌ: <code>#T5</code>"); return
    tid = int(m.group(1))
    conn = db()
    try:
        t = conn.execute("SELECT * FROM tasks WHERE id=? AND active=1", (tid,)).fetchone()
    finally: conn.close()
    if not t: await send(cid, "❌ ታስክ አልተገኘም"); return
    u = get_user(uid)
    if not u or not u["verified"]:
        await send(cid, "⚠️ መጀመሪያ በአፑ ውስጥ ያረጋግጡ"); return
    ok, res = submit_task(uid, tid, proof_text=caption[:500], proof_image=photo_id)
    if not ok:
        await send(cid, f"❌ {res}"); return
    await send(cid, f"✅ <b>ማስረጃ ተልኳል!</b>\n\nታስክ: {html.escape(t['title'])}\nሽልማት: {t['reward']:.2f} ETB\n\nAdmin ከገመገመ በኋላ ይነገርዎታል።")
    await send_submission_admin(res["submission_id"])

async def edit_cb(q, text, kb=None):
    d = {"chat_id": q["message"]["chat"]["id"], "message_id": q["message"]["message_id"], "text": text, "parse_mode": "HTML"}
    if kb is not None: d["reply_markup"] = kb
    return await tg("editMessageText", d)

async def answer_cb(cid, text="", alert=False):
    return await tg("answerCallbackQuery", {"callback_query_id": cid, "text": text, "show_alert": alert})

async def handle_callback(q):
    data = q.get("data", "")
    aid = int(q["from"]["id"])
    if not is_admin(aid): await answer_cb(q["id"], "ፍቃድ የለህም", True); return

    if data.startswith("wdrefs:"):
        _, wid_s, page_s = data.split(":", 2)
        wid = int(wid_s); page = int(page_s)
        conn = db()
        try:
            w = conn.execute("SELECT user_id FROM withdrawals WHERE id=?", (wid,)).fetchone()
            if not w: await answer_cb(q["id"], "አልተገኘም", True); return
            refs = conn.execute("SELECT user_id, username, first_name, last_name, referral_paid, created_at FROM users WHERE referred_by=? ORDER BY user_id DESC",
                                (w["user_id"],)).fetchall()
        finally: conn.close()
        per = 40; start = page*per; chunk = refs[start:start+per]
        total_pages = max(1, (len(refs)+per-1)//per)
        if not chunk: await answer_cb(q["id"], "ሪፈራሎች የሉም"); return
        lines = [f"👥 <b>ሪፈራሎች — ገጽ {page+1}/{total_pages}</b> ({len(refs)} ጠቅላላ)\n"]
        for r in chunk:
            pd = "💰" if r["referral_paid"] else "⏳"
            nm = html.escape(((r["first_name"] or "") + " " + (r["last_name"] or "")).strip() or "—")
            un = f"@{html.escape(r['username'])}" if r["username"] else "—"
            dt = datetime.utcfromtimestamp(int(r["created_at"])).strftime("%m-%d %H:%M")
            lines.append(f"{pd} {nm} {un}\n<code>{r['user_id']}</code> • {dt}")
        nav = []
        if page > 0: nav.append({"text": "⬅️ ቀዳሚ", "callback_data": f"wdrefs:{wid}:{page-1}"})
        if page+1 < total_pages: nav.append({"text": "ቀጣይ ➡️", "callback_data": f"wdrefs:{wid}:{page+1}"})
        kb = {"inline_keyboard": [nav]} if nav else None
        await send(aid, "\n".join(lines), kb)
        await answer_cb(q["id"], f"ገጽ {page+1}"); return

    if data.startswith("wdaudit:"):
        wid = int(data.split(":")[1])
        conn = db()
        try:
            w = conn.execute("SELECT user_id FROM withdrawals WHERE id=?", (wid,)).fetchone()
        finally: conn.close()
        if w: await user_audit(aid, int(w["user_id"]))
        await answer_cb(q["id"], "ተልኳል"); return

    if data.startswith(("wdok:","wdno:","wdban:")):
        action, wid_s = data.split(":", 1); wid = int(wid_s)
        if action == "wdok":
            ok, w = approve_withdrawal(wid, aid)
            if not ok: await answer_cb(q["id"], str(w), True); return
            await answer_cb(q["id"], "✅ ጸድቋል")
            await edit_cb(q, f"✅ <b>ዊዝድሮ #{wid}</b> — ጸድቋል")
            try: await send(int(w["user_id"]), f"✅ <b>ዊዝድሮ ጸድቋል</b>\n\n{w['amount']:.2f} ETB\n{html.escape(w['wallet_type'])}: <code>{html.escape(w['wallet_number'])}</code>")
            except: pass
        elif action == "wdno":
            ok, w = reject_withdrawal(wid, aid, "Rejected by admin")
            if not ok: await answer_cb(q["id"], str(w), True); return
            await answer_cb(q["id"], "❌ ውድቅ ሆኗል")
            await edit_cb(q, f"❌ <b>ዊዝድሮ #{wid}</b> — ውድቅ ሆኖ ተመልሷል")
            try: await send(int(w["user_id"]), f"❌ <b>ዊዝድሮ ውድቅ ሆኗል</b>\nየተመለሰ: {w['amount']:.2f} ETB")
            except: pass
        else:
            conn = db()
            try:
                w = conn.execute("SELECT user_id FROM withdrawals WHERE id=?", (wid,)).fetchone()
                if w:
                    conn.execute("UPDATE users SET banned=1, ban_reason='Withdrawal fraud', updated_at=? WHERE user_id=?", (int(time.time()), w["user_id"])); conn.commit()
            finally: conn.close()
            await answer_cb(q["id"], "🚫 ተከልክሏል")
            await edit_cb(q, f"🚫 <b>ዊዝድሮ #{wid}</b> — ተጠቃሚ ተከልክሏል")
        return

    if data.startswith(("tskok:","tskno:")):
        action, sid_s = data.split(":", 1); sid = int(sid_s)
        if action == "tskok":
            ok, s = approve_task_submission(sid, aid)
            if not ok: await answer_cb(q["id"], str(s), True); return
            await answer_cb(q["id"], "✅")
            await edit_cb(q, f"✅ <b>ታስክ #{sid}</b> — ጸድቋል")
            try: await send(int(s["user_id"]), f"✅ <b>ታስክ ጸድቋል</b>\n{html.escape(s['title'])}\n+{s['reward']:.2f} ETB")
            except: pass
        else:
            reject_task_submission(sid, aid, "Rejected")
            await answer_cb(q["id"], "❌")
            await edit_cb(q, f"❌ <b>ታስክ #{sid}</b> — ውድቅ")
        return
    await answer_cb(q["id"])

# ═══ FASTAPI ═══
app = FastAPI(title="Mega Spark")
init_db()

def validate_init_data(d):
    if not d or not BOT_TOKEN: return None
    try:
        p = dict(parse_qsl(d, keep_blank_values=True))
        h = p.pop("hash", None)
        if not h: return None
        s = "\n".join(f"{k}={p[k]}" for k in sorted(p.keys()))
        sk = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(hmac.new(sk, s.encode(), hashlib.sha256).hexdigest(), h): return None
        if int(p.get("auth_date","0")) < time.time() - 86400: return None
        u = json.loads(p.get("user","{}"))
        if not u.get("id"): return None
        return u
    except: return None

async def require_user(request: Request):
    u = validate_init_data(request.headers.get("X-Telegram-Init-Data",""))
    if not u: return None, None, JSONResponse({"error":"telegram_required"}, status_code=401)
    uid = int(u["id"])
    if is_banned(uid): return None, None, JSONResponse({"error":"banned"}, status_code=403)
    if get_setting("maintenance_mode","0",kind=str) == "1" and not is_admin(uid):
        return None, None, JSONResponse({"error":"maintenance"}, status_code=503)
    ensure_user(uid, u.get("username",""), u.get("first_name",""), u.get("last_name",""))
    ip_h = ""
    try:
        fwd = request.headers.get("x-forwarded-for","")
        rip = fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "")
        if rip: ip_h = hashlib.sha256(rip.encode()).hexdigest()[:16]
    except: pass
    x_device_id = request.headers.get("X-Device-Id","")
    dev_h = hashlib.sha256(x_device_id.encode()).hexdigest()[:16] if x_device_id else ""
    conn = db()
    try:
        cur = conn.execute("SELECT device_hash FROM users WHERE user_id=?", (uid,)).fetchone()
        if cur and not cur["device_hash"] and dev_h:
            conn.execute("UPDATE users SET device_hash=?, ip_hash=? WHERE user_id=?", (dev_h, ip_h, uid)); conn.commit()
        elif cur and dev_h:
            conn.execute("UPDATE users SET device_hash=?, ip_hash=?, last_active=? WHERE user_id=?",
                         (dev_h, ip_h, int(time.time()), uid)); conn.commit()
    finally: conn.close()
    return u, uid, None

@app.get("/", response_class=HTMLResponse)
@app.get("/app", response_class=HTMLResponse)
async def mini_app(): return HTMLResponse(MINI_APP_HTML)

@app.get("/health")
async def health(): return {"status":"ok","service":"mega-spark"}

@app.post("/api/me")
async def api_me(request: Request):
    u, uid, err = await require_user(request)
    if err: return err
    row = get_user(uid)
    return {
        "user_id": uid, "username": row["username"] or "", "first_name": row["first_name"] or "", "last_name": row["last_name"] or "",
        "balance": _r2(row["balance"]), "total_earned": _r2(row["total_earned"]), "total_withdrawn": _r2(row["total_withdrawn"]),
        "referral_earnings": _r2(row["referral_earnings"]), "daily_earnings": _r2(row["daily_earnings"]), "task_earnings": _r2(row["task_earnings"]),
        "verified": bool(row["verified"]), "captcha_passed": bool(row["captcha_passed"]), "banned": bool(row["banned"]),
        "referral_count": get_referral_count(uid),
        "wallet_type": row["wallet_type"] or "", "wallet_number": row["wallet_number"] or "",
        "wallet_suspicious": bool(row["wallet_suspicious"]),
        "settings": {
            "daily_reward": get_setting("daily_reward", DEFAULT_DAILY, kind=float),
            "referral_reward": get_setting("referral_reward", DEFAULT_REFERRAL, kind=float),
            "minimum_withdrawal": get_setting("minimum_withdrawal", DEFAULT_MIN_WITHDRAW, kind=float),
            "bot_username": BOT_USERNAME, "support_username": SUPPORT_USERNAME,
            "payment_day": is_payment_day(),
        },
        "daily_status": daily_status(uid),
        "services": [{"icon":s[0],"title":s[1],"desc":s[2]} for s in SERVICES],
    }

@app.get("/api/channels")
async def api_channels(request: Request):
    u, uid, err = await require_user(request)
    if err: return err
    return {"channels":[{"id":c["id"],"username":c["username"],"name":c["name"],"url":c["url"]} for c in get_channels(active_only=True)]}

@app.get("/api/channel-status")
async def api_channel_status(request: Request):
    """Fast parallel check of per-channel joined status."""
    u, uid, err = await require_user(request)
    if err: return err
    all_joined, results = await check_all_channels_parallel(uid)
    return {"channels": results, "all_joined": all_joined}

@app.post("/api/captcha")
async def api_captcha(request: Request):
    u, uid, err = await require_user(request)
    if err: return err
    t, q = make_captcha(uid)
    return {"token":t,"question":q}

@app.post("/api/captcha/verify")
async def api_captcha_verify(request: Request, payload: dict = Body(...)):
    u, uid, err = await require_user(request)
    if err: return err
    ok, msg, new_t, new_q = verify_captcha((payload.get("token") or "").strip(), str(payload.get("answer") or "").strip())
    if not ok:
        return JSONResponse({"ok":False,"error":msg,"token":new_t,"question":new_q}, status_code=400)
    return {"ok": True}

@app.post("/api/verify")
async def api_verify(request: Request):
    u, uid, err = await require_user(request)
    if err: return err
    row = get_user(uid)
    if not row["captcha_passed"]: return JSONResponse({"ok":False,"error":"captcha_required"}, status_code=400)
    all_ok, results = await check_all_channels_parallel(uid)
    if not all_ok:
        return {"ok":False,"verified":False,"channels":results}
    conn = db()
    try:
        was = bool(row["verified"])
        conn.execute("UPDATE users SET verified=1, updated_at=? WHERE user_id=?", (int(time.time()), uid)); conn.commit()
    finally: conn.close()
    if not was:
        reward, block = pay_referral_if_eligible(uid)
        if block and block.get("multi"):
            try: await send_admin(f"🚨 <b>ማስጠንቀቂያ — Multi-Account</b>\n\nተጠቃሚ: <code>{uid}</code>\nReferrer: <code>{block['referrer']}</code>")
            except: pass
        if reward:
            try: await send(int(get_user(uid)["referred_by"]), f"👥 <b>የሪፈራል ሽልማት</b>\n\n+{reward:.2f} ETB ተከፍሏል!")
            except: pass
    return {"ok":True,"verified":True,"channels":results}

@app.get("/api/tasks")
async def api_tasks(request: Request):
    u, uid, err = await require_user(request)
    if err: return err
    return {"tasks":[{"id":t["id"],"title":t["title"],"description":t["description"] or "","reward":_r2(t["reward"]),"url":t["url"] or "","status":(get_user_task_status(uid,t["id"])["status"] if get_user_task_status(uid,t["id"]) else None)} for t in get_tasks(active_only=True)]}

@app.get("/api/referral")
async def api_ref(request: Request):
    u, uid, err = await require_user(request)
    if err: return err
    conn = db()
    try:
        total_count = int(conn.execute("SELECT COUNT(*) c FROM users WHERE referred_by=?", (uid,)).fetchone()["c"])
    finally: conn.close()
    return {"link":f"https://t.me/{BOT_USERNAME}?start=ref_{uid}","count":get_referral_count(uid),"total":total_count,
            "reward":get_setting("referral_reward",DEFAULT_REFERRAL,kind=float)}

@app.get("/api/wallet")
async def api_wallet_get(request: Request):
    u, uid, err = await require_user(request)
    if err: return err
    r = get_user(uid)
    return {"wallet_type":r["wallet_type"] or "","wallet_number":r["wallet_number"] or "","suspicious":bool(r["wallet_suspicious"])}

@app.post("/api/wallet")
async def api_wallet_post(request: Request, payload: dict = Body(...)):
    u, uid, err = await require_user(request)
    if err: return err
    ok, msg, susp = save_wallet(uid, payload.get("wallet_type",""), payload.get("wallet_number",""))
    if not ok: return JSONResponse({"ok":False,"error":msg}, status_code=400)
    return {"ok":True,"message":msg,"suspicious":susp}

@app.get("/api/daily-status")
async def api_daily_status(request: Request):
    u, uid, err = await require_user(request)
    if err: return err
    return daily_status(uid)

@app.post("/api/daily-bonus")
async def api_daily_bonus(request: Request):
    u, uid, err = await require_user(request)
    if err: return err
    ok, res = claim_daily(uid)
    if not ok: return JSONResponse({"ok":False,**res}, status_code=400)
    return {"ok":True,**res}

@app.post("/api/withdraw")
async def api_withdraw(request: Request, payload: dict = Body(...)):
    u, uid, err = await require_user(request)
    if err: return err
    row = get_user(uid)
    if not row["verified"]: return JSONResponse({"ok":False,"error":"not_verified"}, status_code=400)
    if not is_payment_day(): return JSONResponse({"ok":False,"error":"sunday"}, status_code=400)
    ok, res = create_withdrawal(uid, float(payload.get("amount") or 0))
    if not ok: return JSONResponse({"ok":False,"error":res}, status_code=400)
    try: await send_withdrawal_admin(res["withdrawal_id"])
    except: pass
    return {"ok":True,**res}

@app.get("/api/history")
async def api_history(request: Request):
    u, uid, err = await require_user(request)
    if err: return err
    conn = db()
    try:
        wds = conn.execute("SELECT id,amount,wallet_type,status,created_at FROM withdrawals WHERE user_id=? ORDER BY id DESC LIMIT 50", (uid,)).fetchall()
        subs = conn.execute("SELECT ts.id, ts.status, ts.created_at, t.title, t.reward FROM task_submissions ts JOIN tasks t ON t.id=ts.task_id WHERE ts.user_id=? ORDER BY ts.id DESC LIMIT 50", (uid,)).fetchall()
        txs = conn.execute("SELECT type,amount,description,created_at FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT 50", (uid,)).fetchall()
    finally: conn.close()
    return {"withdrawals":[dict(w) for w in wds],"submissions":[dict(s) for s in subs],"transactions":[dict(t) for t in txs]}

@app.post("/webhook")
async def webhook(request: Request):
    if WEBHOOK_SECRET and request.headers.get("X-Telegram-Bot-Api-Secret-Token","") != WEBHOOK_SECRET:
        return JSONResponse({"ok":False}, status_code=401)
    try: up = await request.json()
    except: return {"ok":True}
    asyncio.create_task(handle_update(up)); return {"ok":True}

async def handle_update(up: dict):
    try:
        if "callback_query" in up: await handle_callback(up["callback_query"]); return
        if "message" in up: await handle_message(up["message"]); return
    except Exception as e: print("err:", e)

@app.on_event("startup")
async def on_startup():
    if BOT_TOKEN and WEBHOOK_URL:
        p = {"url": WEBHOOK_URL, "allowed_updates": ["message","callback_query"]}
        if WEBHOOK_SECRET: p["secret_token"] = WEBHOOK_SECRET
        r = await tg("setWebhook", p)
        print("setWebhook:", r)

# ═══ MINI APP ═══
MINI_APP_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
<meta name="theme-color" content="#050b18">
<title>Mega Spark</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root{--bg:#050b18;--panel:#0b1830;--panel2:#0e1e3c;--line:rgba(80,150,255,.16);--text:#f5f9ff;--muted:#8ba0be;--blue:#2ea8ff;--gold:#ffc63f;--green:#34e6a4;--red:#ff6178;--violet:#7c68ff;--r:20px;--rs:14px}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;background:var(--bg);color:var(--text);font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;overflow-x:hidden}
body{min-height:100vh}
body.app-mode{padding-bottom:90px}
a{color:var(--blue);text-decoration:none}
button{font-family:inherit;cursor:pointer;border:0;outline:0;color:inherit}
.hidden{display:none!important}
.header{position:sticky;top:0;z-index:20;padding:14px 18px;display:flex;align-items:center;gap:12px;background:linear-gradient(180deg,rgba(5,11,24,.96),rgba(5,11,24,.82));backdrop-filter:blur(14px);border-bottom:1px solid var(--line)}
.logo{width:40px;height:40px;border-radius:12px;background:linear-gradient(135deg,#0f6fff,#2ea8ff 60%,#7c68ff);display:grid;place-items:center;font-size:22px;box-shadow:0 8px 24px -8px rgba(46,168,255,.6)}
.brand{font-weight:800;letter-spacing:.3px;font-size:16px;line-height:1.1}
.brand small{display:block;color:var(--muted);font-weight:500;font-size:11px;letter-spacing:.5px}
.balance-chip{margin-left:auto;padding:8px 12px;border-radius:999px;background:linear-gradient(135deg,rgba(46,168,255,.16),rgba(124,104,255,.16));border:1px solid var(--line);font-weight:700;font-size:13px;display:flex;align-items:center;gap:6px}
.balance-chip .amt{color:var(--gold)}
.wrap{padding:16px 16px 8px;max-width:640px;margin:0 auto}
.screen{display:none;animation:fade .25s ease}
.screen.active{display:block}
@keyframes fade{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.card{background:linear-gradient(180deg,var(--panel),var(--panel2));border:1px solid var(--line);border-radius:var(--r);padding:16px;margin-bottom:14px}
.hero{background:radial-gradient(120% 90% at 100% 0%,rgba(46,168,255,.22),transparent 55%),radial-gradient(90% 80% at 0% 100%,rgba(124,104,255,.22),transparent 55%),linear-gradient(180deg,#0b1830,#0a1428);border:1px solid rgba(80,150,255,.22)}
.hero .label{color:var(--muted);font-size:12px;letter-spacing:.6px;text-transform:uppercase;font-weight:600}
.hero .amount{font-size:38px;font-weight:800;letter-spacing:-1px;margin:6px 0 2px;line-height:1}
.hero .amount .cur{font-size:18px;color:var(--muted);font-weight:600;margin-left:6px}
.hero .sub{color:var(--muted);font-size:12px;margin-top:6px}
.split{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-top:12px}
.split .box{background:rgba(0,0,0,.25);border:1px solid var(--line);border-radius:14px;padding:10px;text-align:center}
.split .box .v{font-weight:800;font-size:13px}
.split .box .k{color:var(--muted);font-size:9px;text-transform:uppercase;letter-spacing:.4px;margin-top:3px;font-weight:700}
.split .box.bonus .v{color:var(--gold)}
.split .box.ref .v{color:var(--violet)}
.split .box.task .v{color:var(--green)}
.sect{font-size:12px;color:var(--muted);font-weight:700;letter-spacing:1.4px;text-transform:uppercase;margin:20px 4px 10px}
.actions{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.action{background:linear-gradient(180deg,var(--panel),var(--panel2));border:1px solid var(--line);border-radius:var(--r);padding:14px;display:flex;align-items:center;gap:12px;text-align:left;width:100%;transition:transform .12s}
.action:active{transform:scale(.98)}
.action .ico{width:40px;height:40px;border-radius:12px;flex:0 0 40px;display:grid;place-items:center;font-size:20px;background:linear-gradient(135deg,rgba(46,168,255,.22),rgba(124,104,255,.22));border:1px solid var(--line)}
.action .ico.gold{background:linear-gradient(135deg,rgba(255,198,63,.22),rgba(255,140,0,.18));border-color:rgba(255,198,63,.32)}
.action .ico.green{background:linear-gradient(135deg,rgba(52,230,164,.2),rgba(0,180,110,.16));border-color:rgba(52,230,164,.3)}
.action .ico.violet{background:linear-gradient(135deg,rgba(124,104,255,.22),rgba(80,60,220,.18));border-color:rgba(124,104,255,.32)}
.action .ico.red{background:linear-gradient(135deg,rgba(255,97,120,.2),rgba(220,40,80,.16));border-color:rgba(255,97,120,.3)}
.action .t{font-weight:700;font-size:14px}
.action .s{color:var(--muted);font-size:11px;margin-top:3px}
.row{display:flex;align-items:center;gap:12px;padding:14px;background:linear-gradient(180deg,var(--panel),var(--panel2));border:1px solid var(--line);border-radius:var(--rs);margin-bottom:8px}
.row .ico{width:38px;height:38px;border-radius:11px;flex:0 0 38px;display:grid;place-items:center;background:linear-gradient(135deg,rgba(46,168,255,.18),rgba(124,104,255,.18));border:1px solid var(--line);font-size:18px}
.row .body{flex:1;min-width:0}
.row .title{font-weight:700;font-size:14px}
.row .desc{color:var(--muted);font-size:12px;margin-top:3px}
.row .right{font-weight:800;color:var(--gold);font-size:14px;text-align:right}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;padding:14px 18px;border-radius:14px;font-weight:700;font-size:14px;width:100%;background:linear-gradient(135deg,#2ea8ff,#0f6fff);color:#fff;box-shadow:0 8px 24px -10px rgba(46,168,255,.7);transition:transform .12s}
.btn:active{transform:scale(.98)}
.btn.ghost{background:rgba(46,168,255,.12);color:var(--blue);border:1px solid rgba(46,168,255,.3);box-shadow:none}
.btn.gold{background:linear-gradient(135deg,#ffc63f,#ff9500);color:#1a1200;box-shadow:0 8px 24px -10px rgba(255,198,63,.7)}
.btn.dark{background:rgba(255,255,255,.05);border:1px solid var(--line);color:var(--text);box-shadow:none}
.btn:disabled{opacity:.45;pointer-events:none}
.btn-row{display:flex;gap:8px;margin-top:12px}
.btn-row .btn{flex:1}
.label{display:block;font-size:12px;color:var(--muted);font-weight:600;margin:12px 0 6px}
.input,textarea.input{width:100%;padding:14px;border-radius:14px;background:rgba(0,0,0,.32);border:1px solid var(--line);color:var(--text);font-size:15px;outline:none}
.input:focus{border-color:var(--blue)}
.chips{display:flex;gap:8px;flex-wrap:wrap;margin-top:6px}
.chip{padding:10px 14px;border-radius:999px;font-size:13px;font-weight:600;background:rgba(255,255,255,.05);border:1px solid var(--line);color:var(--muted)}
.chip.active{background:linear-gradient(135deg,rgba(46,168,255,.3),rgba(124,104,255,.24));color:#fff;border-color:rgba(46,168,255,.5)}
.badge{display:inline-flex;padding:4px 8px;border-radius:999px;font-size:10px;font-weight:800;letter-spacing:.5px;text-transform:uppercase}
.badge.pending{background:rgba(255,198,63,.16);color:var(--gold);border:1px solid rgba(255,198,63,.32)}
.badge.approved{background:rgba(52,230,164,.16);color:var(--green);border:1px solid rgba(52,230,164,.32)}
.badge.rejected{background:rgba(255,97,120,.16);color:var(--red);border:1px solid rgba(255,97,120,.32)}
.warn{background:linear-gradient(135deg,rgba(255,97,120,.15),rgba(255,60,100,.1));border:1px solid rgba(255,97,120,.35);border-radius:14px;padding:12px;font-size:12px;color:#ffd4dc;margin-bottom:12px;line-height:1.5}
.nav{position:fixed;left:0;right:0;bottom:0;z-index:30;display:none;grid-template-columns:repeat(4,1fr);padding:8px 8px calc(8px + env(safe-area-inset-bottom));background:linear-gradient(180deg,rgba(5,11,24,.86),rgba(5,11,24,.98));backdrop-filter:blur(18px);border-top:1px solid var(--line)}
body.app-mode .nav{display:grid}
.nav button{background:none;display:flex;flex-direction:column;align-items:center;gap:3px;padding:8px 4px;color:var(--muted);font-size:10px;font-weight:700}
.nav button .ni{font-size:20px}
.nav button.active{color:var(--blue)}
.gate{position:fixed;inset:0;background:var(--bg);z-index:100;display:none;overflow-y:auto;padding:24px 18px}
.gate.active{display:block}
.gate-inner{max-width:480px;margin:0 auto;padding-top:30px;text-align:center}
.gate-logo{font-size:64px;line-height:1;margin-bottom:12px;filter:drop-shadow(0 8px 24px rgba(46,168,255,.6))}
.gate-title{font-size:24px;font-weight:800;letter-spacing:-.5px;margin:0 0 6px}
.gate-sub{color:var(--muted);font-size:14px;margin-bottom:24px}
.captcha-card{background:linear-gradient(180deg,var(--panel),var(--panel2));border:1px solid var(--line);border-radius:22px;padding:28px 22px;margin-top:12px}
.captcha-q-label{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:1.5px;font-weight:700;margin-bottom:8px}
.captcha-q{font-size:44px;font-weight:900;letter-spacing:-1px;margin:8px 0 22px;background:linear-gradient(135deg,#2ea8ff,#7c68ff);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;line-height:1.1;min-height:52px;display:flex;align-items:center;justify-content:center}
.captcha-input{width:100%;padding:18px;border-radius:16px;background:rgba(0,0,0,.4);border:2px solid var(--line);color:var(--text);font-size:24px;text-align:center;font-weight:800;letter-spacing:4px;outline:none;transition:border-color .2s}
.captcha-input:focus{border-color:var(--blue)}
.captcha-input.err{border-color:var(--red);animation:shake .4s}
@keyframes shake{0%,100%{transform:translateX(0)}25%{transform:translateX(-8px)}75%{transform:translateX(8px)}}

/* Channel items with per-channel status */
.channels-card{background:linear-gradient(180deg,var(--panel),var(--panel2));border:1px solid var(--line);border-radius:20px;padding:6px;margin-top:16px;text-align:left}
.channel-item{display:flex;align-items:center;gap:12px;padding:14px;border-radius:14px;margin-bottom:4px;text-decoration:none;color:inherit;transition:background .2s}
.channel-item:active{background:rgba(46,168,255,.08)}
.channel-item:last-child{margin-bottom:0}
.channel-item .ico{width:42px;height:42px;border-radius:12px;border:1px solid var(--line);display:grid;place-items:center;font-size:20px;flex:0 0 42px;background:linear-gradient(135deg,rgba(46,168,255,.22),rgba(124,104,255,.22))}
.channel-item.joined .ico{background:linear-gradient(135deg,rgba(52,230,164,.22),rgba(0,180,110,.16));border-color:rgba(52,230,164,.4)}
.channel-item .nm{font-weight:700;font-size:14px}
.channel-item .un{color:var(--muted);font-size:12px;margin-top:2px}
.channel-item .go{margin-left:auto;font-size:12px;font-weight:700;white-space:nowrap}
.channel-item:not(.joined) .go{color:var(--blue)}
.channel-item.joined .go{color:var(--green)}

.modal-bg{position:fixed;inset:0;z-index:40;background:rgba(3,8,18,.72);backdrop-filter:blur(6px);display:flex;align-items:flex-end;justify-content:center}
.modal{width:100%;max-width:640px;max-height:88vh;overflow-y:auto;background:linear-gradient(180deg,#0d1c38,#0a1528);border-radius:24px 24px 0 0;border:1px solid var(--line);border-bottom:0;padding:20px 18px calc(24px + env(safe-area-inset-bottom));animation:slideUp .28s}
@keyframes slideUp{from{transform:translateY(30px);opacity:.5}to{transform:none;opacity:1}}
.modal h3{margin:0 0 4px;font-size:19px}
.modal .muted{color:var(--muted);font-size:13px;margin-bottom:14px}
.mh{display:flex;align-items:center;gap:10px;margin-bottom:14px}
.mh .close{margin-left:auto;background:rgba(255,255,255,.06);border:1px solid var(--line);border-radius:10px;width:34px;height:34px;display:grid;place-items:center;font-size:16px}
.toast{position:fixed;left:50%;bottom:110px;transform:translateX(-50%);padding:12px 18px;border-radius:14px;background:rgba(20,35,65,.96);border:1px solid var(--line);font-size:13px;font-weight:600;z-index:200;animation:toastIn .25s}
@keyframes toastIn{from{transform:translate(-50%,14px);opacity:0}to{transform:translate(-50%,0);opacity:1}}
.center{display:grid;place-items:center;min-height:60vh;text-align:center;padding:20px}
.spinner{width:44px;height:44px;border-radius:50%;border:3px solid rgba(46,168,255,.18);border-top-color:var(--blue);animation:spin 1s linear infinite;margin:0 auto 14px}
@keyframes spin{to{transform:rotate(360deg)}}
</style>
</head>
<body>

<div id="loading" class="center"><div><div class="spinner"></div><div style="color:var(--muted);font-size:13px">Loading Mega Spark…</div></div></div>

<div id="gate-captcha" class="gate">
  <div class="gate-inner">
    <div class="gate-logo">⚡</div>
    <h1 class="gate-title">Mega Spark</h1>
    <div class="gate-sub">Human verification required</div>
    <div class="captcha-card">
      <div class="captcha-q-label">Solve this</div>
      <div class="captcha-q" id="captchaQ">···</div>
      <input class="captcha-input" id="captchaA" type="number" inputmode="numeric" placeholder="?" maxlength="4">
      <button class="btn" id="captchaBtn" style="margin-top:14px">✅ Verify Answer</button>
    </div>
  </div>
</div>

<div id="gate-channels" class="gate">
  <div class="gate-inner">
    <div class="gate-logo">📢</div>
    <h1 class="gate-title">Join Required Channels</h1>
    <div class="gate-sub" id="channelStatus">Checking…</div>
    <div class="channels-card" id="channelsList"></div>
    <button class="btn" id="verifyBtn" style="margin-top:16px" disabled>🔄 Verify Membership</button>
    <div style="text-align:center;color:var(--muted);font-size:11px;margin-top:12px">
      Tap each channel to join, then come back. Status refreshes automatically.
    </div>
  </div>
</div>

<div id="app" class="hidden">
  <header class="header">
    <div class="logo">⚡</div>
    <div class="brand">Mega Spark<small>Earn • Complete • Grow</small></div>
    <div class="balance-chip">💼 <span class="amt" id="chipBalance">0.00</span> ETB</div>
  </header>
  <main class="wrap">
    <section id="screen-overview" class="screen">
      <div class="card hero">
        <div class="label">Available Balance</div>
        <div class="amount"><span id="ovBalance">0.00</span><span class="cur">ETB</span></div>
        <div class="sub" id="ovGreeting">Hello 👋</div>
        <div class="split">
          <div class="box bonus"><div class="v" id="ovBonus">0.00</div><div class="k">🎁 Bonus</div></div>
          <div class="box ref"><div class="v" id="ovRef">0.00</div><div class="k">👥 Referral</div></div>
          <div class="box task"><div class="v" id="ovTask">0.00</div><div class="k">📋 Task</div></div>
        </div>
      </div>
      <div class="sect">Quick Actions</div>
      <div class="actions">
        <button class="action" data-nav="earn"><div class="ico gold">🎁</div><div><div class="t">Earn</div><div class="s">Daily & Tasks</div></div></button>
        <button class="action" id="inviteBtn"><div class="ico violet">👥</div><div><div class="t">Invite</div><div class="s">Refer & earn</div></div></button>
        <button class="action" id="walletBtn"><div class="ico">💳</div><div><div class="t">Wallet</div><div class="s">CBE / Telebirr</div></div></button>
        <button class="action" id="withdrawBtn"><div class="ico green">💸</div><div><div class="t">Payout</div><div class="s">Withdraw ETB</div></div></button>
      </div>
      <div class="sect">Services & Support</div>
      <button class="action" id="servicesBtn" style="width:100%"><div class="ico red">🛠</div><div><div class="t">Services & Support</div><div class="s">Promotions, USDT, growth</div></div></button>
    </section>

    <section id="screen-earn" class="screen">
      <div class="sect">Daily Bonus · Every 24 Hours</div>
      <div class="card hero" style="text-align:center">
        <div style="font-size:40px;line-height:1">🎁</div>
        <div style="font-size:26px;font-weight:800;color:var(--gold);margin-top:4px" id="dailyAmount">+0.50 ETB</div>
        <div style="color:var(--muted);font-size:12px;margin:4px 0 14px" id="dailyMsg">Claim once every 24 hours</div>
        <button class="btn gold" id="dailyBtn">Claim Daily Bonus</button>
      </div>
      <div class="sect">Tasks</div>
      <div id="tasksList"></div>
    </section>

    <section id="screen-activity" class="screen">
      <div class="sect">Withdrawals</div>
      <div id="withdrawalsList"></div>
      <div class="sect">Task Submissions</div>
      <div id="submissionsList"></div>
      <div class="sect">Transactions</div>
      <div id="transactionsList"></div>
    </section>

    <section id="screen-account" class="screen">
      <div class="card hero">
        <div style="display:flex;align-items:center;gap:12px">
          <div class="logo" style="width:52px;height:52px;font-size:26px">⚡</div>
          <div><div style="font-weight:800;font-size:17px" id="accName">—</div>
          <div style="color:var(--muted);font-size:12px" id="accUser">—</div></div>
        </div>
        <div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap">
          <span class="badge approved" id="accVerified">Verified</span>
          <span class="badge pending" id="accId">ID —</span>
        </div>
      </div>
      <div class="sect">Wallet</div>
      <div class="row">
        <div class="ico">💳</div>
        <div class="body"><div class="title" id="accWalletType">Not set</div><div class="desc" id="accWalletNum">Save CBE or Telebirr</div></div>
        <button class="btn ghost" style="width:auto;padding:10px 14px;font-size:12px" id="walletBtn2">Edit</button>
      </div>
      <div class="sect">Referral</div>
      <button class="row" id="refRow" style="width:100%;text-align:left">
        <div class="ico">👥</div>
        <div class="body"><div class="title">Invite Friends</div><div class="desc" id="accRefDesc">Earn per verified referral</div></div>
        <div class="right" id="accRefCount">0</div>
      </button>
      <div class="sect">Support</div>
      <a class="row" href="https://t.me/AmanM_12" target="_blank" style="text-decoration:none;color:inherit">
        <div class="ico">🎧</div>
        <div class="body"><div class="title">Contact Support</div><div class="desc">@AmanM_12</div></div>
      </a>
    </section>
  </main>

  <nav class="nav">
    <button data-nav="overview" class="active"><span class="ni">🏠</span>Overview</button>
    <button data-nav="earn"><span class="ni">⚡</span>Earn</button>
    <button data-nav="activity"><span class="ni">📊</span>Activity</button>
    <button data-nav="account"><span class="ni">👤</span>Account</button>
  </nav>
</div>

<script>
const tg = window.Telegram?.WebApp;
if (tg) { tg.ready(); tg.expand(); tg.setHeaderColor?.('#050b18'); tg.setBackgroundColor?.('#050b18'); }
const initData = tg?.initData || '';
let deviceId = localStorage.getItem('ms_fid');
if (!deviceId) { deviceId = 'd_' + Math.random().toString(36).slice(2) + Date.now(); localStorage.setItem('ms_fid', deviceId); }
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
let STATE = { me:null, tasks:[], captchaToken:null, channelsChecked:false };

async function api(path, opts={}) {
  const r = await fetch(path, {
    method: opts.method || 'GET',
    headers: { 'Content-Type':'application/json', 'X-Telegram-Init-Data': initData, 'X-Device-Id': deviceId },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  let d = {};
  try { d = await r.json(); } catch(e){}
  return { ok: r.ok, status: r.status, data: d };
}
function toast(m, ms=2200){ const t=document.createElement('div'); t.className='toast'; t.textContent=m; document.body.appendChild(t); setTimeout(()=>t.remove(), ms); }
function fmt(n){ return (Number(n)||0).toFixed(2); }
function esc(s){ return String(s ?? '').replace(/[&<>"']/g, c=>({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c])); }

function showGate(name) {
  $('#loading').classList.add('hidden');
  $('#app').classList.add('hidden');
  document.body.classList.remove('app-mode');
  $$('.gate').forEach(g => g.classList.remove('active'));
  const g = $('#gate-'+name);
  if (g) g.classList.add('active');
}
function showApp() {
  $('#loading').classList.add('hidden');
  $$('.gate').forEach(g => g.classList.remove('active'));
  $('#app').classList.remove('hidden');
  document.body.classList.add('app-mode');
  showScreen('overview');
}
function showScreen(n){
  $$('.screen').forEach(s => s.classList.remove('active'));
  const el = $('#screen-'+n); if (el) el.classList.add('active');
  $$('.nav button').forEach(b => b.classList.toggle('active', b.dataset.nav === n));
  if (n === 'activity') loadActivity();
}
document.addEventListener('click', e => { const b = e.target.closest('[data-nav]'); if (b) showScreen(b.dataset.nav); });

function renderApp(){
  const m = STATE.me;
  $('#chipBalance').textContent = fmt(m.balance);
  $('#ovBalance').textContent = fmt(m.balance);
  $('#ovGreeting').textContent = 'Hello, ' + (m.first_name || m.username || 'User') + ' 👋';
  $('#ovBonus').textContent = fmt(m.daily_earnings);
  $('#ovRef').textContent = fmt(m.referral_earnings);
  $('#ovTask').textContent = fmt(m.task_earnings);
  $('#dailyAmount').textContent = '+' + fmt(m.settings.daily_reward) + ' ETB';
  if (m.daily_status && !m.daily_status.available && m.daily_status.remaining > 0) {
    const h = Math.floor(m.daily_status.remaining/3600);
    const mn = Math.floor((m.daily_status.remaining%3600)/60);
    $('#dailyMsg').textContent = `✅ Today taken. Next in ${h}h ${mn}m`;
    $('#dailyBtn').disabled = true;
    $('#dailyBtn').textContent = '⏳ Wait ' + h + 'h ' + mn + 'm';
  } else {
    $('#dailyMsg').textContent = 'Claim once every 24 hours';
    $('#dailyBtn').disabled = false;
    $('#dailyBtn').textContent = '🎁 Claim Daily Bonus';
  }
  $('#accName').textContent = m.first_name || m.username || ('User ' + m.user_id);
  $('#accUser').textContent = m.username ? '@' + m.username : 'No username';
  $('#accId').textContent = 'ID ' + m.user_id;
  $('#accVerified').textContent = m.verified ? '✓ Verified' : 'Unverified';
  $('#accVerified').className = 'badge ' + (m.verified ? 'approved' : 'pending');
  $('#accWalletType').textContent = m.wallet_type || 'Not set';
  $('#accWalletNum').textContent = m.wallet_number || 'Save CBE or Telebirr';
  if (m.wallet_suspicious) $('#accWalletNum').textContent += ' ⚠️';
  $('#accRefDesc').textContent = 'Earn ' + fmt(m.settings.referral_reward) + ' ETB per verified invite';
  $('#accRefCount').textContent = m.referral_count || 0;
}

async function loadMe(){
  const r = await api('/api/me', { method:'POST' });
  if (!r.ok) {
    if (r.status === 401) { $('#loading').innerHTML='<div class="center"><div>Open from Telegram.</div></div>'; return false; }
    if (r.status === 403) { $('#loading').innerHTML='<div class="center"><div style="color:var(--red)">🚫 Restricted.</div></div>'; return false; }
    if (r.status === 503) { $('#loading').innerHTML='<div class="center"><div>🛠 Maintenance mode.</div></div>'; return false; }
    return false;
  }
  STATE.me = r.data; return true;
}

async function startCaptcha(){
  const q = $('#captchaQ'); q.textContent = '···';
  const r = await api('/api/captcha', { method:'POST' });
  if (r.ok && r.data.question) { STATE.captchaToken = r.data.token; q.textContent = r.data.question; }
  else { q.textContent = 'Error'; }
}

/* ─── CHANNELS with per-channel status & auto-refresh ─── */
async function loadChannelStatus(showSpinner){
  if (showSpinner) {
    $('#channelsList').innerHTML = '<div style="text-align:center;padding:24px;color:var(--muted);font-size:13px"><div class="spinner" style="width:28px;height:28px;margin-bottom:8px"></div>Checking channels…</div>';
  }
  const r = await api('/api/channel-status');
  if (!r.ok) {
    $('#channelsList').innerHTML = '<div style="text-align:center;padding:20px;color:var(--red);font-size:13px">Failed to check channels</div>';
    return;
  }
  const chans = r.data.channels || [];
  const joinedCount = chans.filter(c => c.joined).length;
  const total = chans.length;
  const remaining = total - joinedCount;

  // Update header text
  if (r.data.all_joined) {
    $('#channelStatus').innerHTML = '<span style="color:var(--green)">✅ All channels verified!</span>';
    $('#verifyBtn').disabled = false;
    $('#verifyBtn').textContent = '✅ Continue to App';
  } else {
    $('#channelStatus').innerHTML = `<span style="color:var(--gold)">${remaining} channel${remaining>1?'s':''} still needed</span> · ${joinedCount}/${total} joined`;
    $('#verifyBtn').disabled = false;
    $('#verifyBtn').textContent = '🔄 Verify Membership';
  }

  // Render each channel
  $('#channelsList').innerHTML = chans.map(c => `
    <a class="channel-item ${c.joined ? 'joined' : ''}" href="${esc(c.url)}" target="_blank" rel="noopener" data-user="${esc(c.username)}">
      <div class="ico">${c.joined ? '✅' : '📢'}</div>
      <div><div class="nm">${esc(c.name)}</div><div class="un">${esc(c.username)}</div></div>
      <div class="go">${c.joined ? '✓ Joined' : 'Join →'}</div>
    </a>`).join('');

  STATE.channelsChecked = true;
}

/* Re-check when user returns from Telegram (after joining a channel) */
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible' && !STATE.channelsChecked) {
    // Only auto-refresh if we're on channels gate
    if ($('#gate-channels').classList.contains('active')) {
      loadChannelStatus(false);
    }
  }
});
// Also refresh when window gains focus
window.addEventListener('focus', () => {
  if ($('#gate-channels').classList.contains('active')) {
    loadChannelStatus(false);
  }
});
// Telegram WebApp: also listen for "activated" event
if (tg && tg.onEvent) {
  tg.onEvent('activated', () => {
    if ($('#gate-channels').classList.contains('active')) {
      loadChannelStatus(false);
    }
  });
}

async function loadTasks(){
  const r = await api('/api/tasks');
  if (r.ok) STATE.tasks = r.data.tasks || [];
  const box = $('#tasksList');
  if (!STATE.tasks.length) {
    box.innerHTML = `
      <div class="card" style="text-align:center;padding:28px 20px">
        <div style="font-size:52px;line-height:1;margin-bottom:8px">📋</div>
        <div style="font-weight:800;font-size:20px;margin-bottom:6px">Tasks Coming Soon</div>
        <div style="color:var(--muted);font-size:13px;line-height:1.6;margin-bottom:18px">
          Get ready! New paid tasks will be available here very soon.
          Complete simple activities and earn real rewards.
        </div>
        <div style="text-align:left;background:rgba(0,0,0,.28);border:1px solid var(--line);border-radius:14px;padding:14px;margin-bottom:14px">
          <div style="font-size:12px;font-weight:700;color:var(--muted);letter-spacing:1px;margin-bottom:8px">WHAT TO EXPECT</div>
          <div style="font-size:13px;line-height:1.9">
            🎯 Join Telegram channels<br>
            👀 Watch short videos<br>
            ✅ Complete surveys<br>
            📱 Social media tasks<br>
            🔗 Website visits<br>
            📸 Screenshot proofs
          </div>
        </div>
        <div style="color:var(--muted);font-size:12px">
          💡 Stay tuned — announcements coming soon!
        </div>
      </div>`;
    return;
  }
  box.innerHTML = STATE.tasks.map(t => {
    const st = t.status ? `<span class="badge ${t.status}">${t.status}</span>` : '';
    const dis = (t.status === 'pending' || t.status === 'approved') ? 'disabled' : '';
    return `<div class="row" style="flex-direction:column;align-items:stretch;gap:10px">
      <div style="display:flex;gap:12px;align-items:center">
        <div class="ico">📋</div>
        <div class="body"><div class="title">${esc(t.title)}</div><div class="desc">${esc(t.description)}</div></div>
        <div class="right">+${fmt(t.reward)} ETB</div>
      </div>
      ${st ? `<div>${st}</div>` : ''}
      <div class="btn-row">
        ${t.url ? `<a class="btn dark" href="${esc(t.url)}" target="_blank" style="text-decoration:none">Open Task</a>` : ''}
        <button class="btn" data-task="${t.id}" ${dis}>Submit Proof</button>
      </div></div>`;
  }).join('');
  $$('[data-task]').forEach(b => b.addEventListener('click', () => openSubmit(parseInt(b.dataset.task))));
}

async function loadActivity(){
  const r = await api('/api/history');
  if (!r.ok) return;
  const { withdrawals, submissions, transactions } = r.data;
  $('#withdrawalsList').innerHTML = (withdrawals||[]).length ? withdrawals.map(w => `
    <div class="row"><div class="ico">💸</div>
      <div class="body"><div class="title">${fmt(w.amount)} ETB</div>
      <div class="desc">${esc(w.wallet_type)} • ${new Date(w.created_at*1000).toLocaleDateString()}</div></div>
      <span class="badge ${w.status}">${w.status}</span></div>`).join('') : '<div style="color:var(--muted);font-size:13px;text-align:center;padding:16px">No withdrawals.</div>';
  $('#submissionsList').innerHTML = (submissions||[]).length ? submissions.map(s => `
    <div class="row"><div class="ico">📋</div>
      <div class="body"><div class="title">${esc(s.title)}</div>
      <div class="desc">+${fmt(s.reward)} ETB • ${new Date(s.created_at*1000).toLocaleDateString()}</div></div>
      <span class="badge ${s.status}">${s.status}</span></div>`).join('') : '<div style="color:var(--muted);font-size:13px;text-align:center;padding:16px">No submissions.</div>';
  $('#transactionsList').innerHTML = (transactions||[]).length ? transactions.map(t => `
    <div class="row"><div class="ico">📊</div>
      <div class="body"><div class="title">${esc(t.type)}</div>
      <div class="desc">${esc(t.description||'')} • ${new Date(t.created_at*1000).toLocaleDateString()}</div></div>
      <div class="right">${t.amount>=0?'+':''}${fmt(t.amount)}</div></div>`).join('') : '<div style="color:var(--muted);font-size:13px;text-align:center;padding:16px">No transactions.</div>';
}

function closeModal(){ const m = $('.modal-bg'); if (m) m.remove(); }
function openModal(html){
  closeModal();
  const w = document.createElement('div'); w.className='modal-bg';
  w.innerHTML = `<div class="modal">${html}</div>`;
  w.addEventListener('click', e => { if (e.target === w) closeModal(); });
  document.body.appendChild(w);
  w.querySelectorAll('[data-close]').forEach(b => b.addEventListener('click', closeModal));
}

function openSubmit(taskId){
  const t = STATE.tasks.find(x => x.id === taskId); if (!t) return;
  const botUser = STATE.me.settings.bot_username;
  const code = `#T${taskId}`;
  openModal(`<div class="mh"><h3>Submit Task Proof</h3><button class="close" data-close>✕</button></div>
    <div class="muted">${esc(t.title)} • +${fmt(t.reward)} ETB</div>
    <div class="card" style="background:rgba(46,168,255,.08);border-color:rgba(46,168,255,.3)">
      <div style="font-size:13px;font-weight:700;margin-bottom:8px">📸 How to submit</div>
      <ol style="margin:0;padding-left:20px;font-size:13px;line-height:1.7;color:var(--muted)">
        <li>Complete the task</li>
        <li>Take a <b style="color:var(--text)">screenshot</b> as proof</li>
        <li>Open <b style="color:var(--blue)">@${esc(botUser)}</b> on Telegram</li>
        <li>Send the screenshot with caption:</li>
      </ol>
      <div style="text-align:center;margin:14px 0 6px">
        <div style="display:inline-block;padding:10px 20px;background:rgba(0,0,0,.4);border:2px dashed rgba(46,168,255,.5);border-radius:12px;font-size:20px;font-weight:900;letter-spacing:2px;color:var(--blue)">${code}</div>
      </div>
      <div style="text-align:center;color:var(--muted);font-size:11px;margin-top:8px">Admin will review and credit your reward</div>
    </div>
    <div class="btn-row">
      <button class="btn dark" data-close>Close</button>
      <a class="btn" href="https://t.me/${esc(botUser)}" target="_blank" style="text-decoration:none">📤 Open Bot</a>
    </div>`);
}

function openInvite(){
  const m = STATE.me;
  openModal(`<div class="mh"><h3>Invite Friends</h3><button class="close" data-close>✕</button></div>
    <div class="muted">Earn <b style="color:var(--gold)">${fmt(m.settings.referral_reward)} ETB</b> per verified referral.</div>
    <div class="warn">⚠️ Multi-account usage = <b>withdrawal rejected without payment</b>.</div>
    <div class="card hero" style="text-align:center">
      <div class="label">Your Referral Link</div>
      <div style="word-break:break-all;font-size:13px;margin:8px 0;color:var(--blue)" id="refLink">https://t.me/${esc(m.settings.bot_username)}?start=ref_${m.user_id}</div>
      <button class="btn" id="copyRef">📋 Copy Link</button>
    </div>
    <div class="card">
      <div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid var(--line)"><span style="color:var(--muted)">Verified referrals</span><b style="color:var(--green);font-size:18px">${m.referral_count}</b></div>
      <div style="display:flex;justify-content:space-between;padding:8px 0"><span style="color:var(--muted)">Referral earnings</span><b style="color:var(--gold)">${fmt(m.referral_earnings)} ETB</b></div>
    </div>`);
  $('#copyRef').addEventListener('click', async () => {
    const link = $('#refLink').textContent;
    try { await navigator.clipboard.writeText(link); toast('Copied!'); }
    catch(e){ tg?.openTelegramLink?.(`https://t.me/share/url?url=${encodeURIComponent(link)}`); }
  });
}

function openWallet(){
  const m = STATE.me;
  openModal(`<div class="mh"><h3>Wallet</h3><button class="close" data-close>✕</button></div>
    <div class="muted">Choose method and enter your number.</div>
    <div class="chips">
      <button class="chip ${m.wallet_type==='CBE'?'active':''}" data-w="cbe">🏦 CBE</button>
      <button class="chip ${m.wallet_type==='Telebirr'?'active':''}" data-w="telebirr">📱 Telebirr</button>
    </div>
    <label class="label">Wallet Number</label>
    <input class="input" id="wnum" placeholder="${m.wallet_number || 'Enter number'}" value="${m.wallet_number || ''}">
    <div style="color:var(--muted);font-size:11px;margin-top:6px">CBE: 13 digits starting 1000 · Telebirr: 10 digits starting 09/07</div>
    <div class="btn-row"><button class="btn dark" data-close>Cancel</button><button class="btn" id="saveWallet">Save</button></div>`);
  let wt = m.wallet_type ? m.wallet_type.toLowerCase() : 'cbe';
  $$('.chip[data-w]').forEach(c => c.addEventListener('click', () => {
    wt = c.dataset.w; $$('.chip[data-w]').forEach(x => x.classList.toggle('active', x === c));
  }));
  $('#saveWallet').addEventListener('click', async () => {
    const num = ($('#wnum').value || '').trim();
    const r = await api('/api/wallet', { method:'POST', body:{ wallet_type: wt, wallet_number: num } });
    if (r.ok) { toast('✅ Saved'); closeModal(); await refresh(); }
    else toast(r.data.error || 'Invalid');
  });
}

function openWithdraw(){
  const m = STATE.me;
  if (!m.wallet_type || !m.wallet_number) { toast('Save wallet first'); openWallet(); return; }
  if (!m.settings.payment_day) {
    toast('🛑 Sunday — no withdrawals. Try Monday.');
    return;
  }
  openModal(`<div class="mh"><h3>Request Payout</h3><button class="close" data-close>✕</button></div>
    <div class="muted">Available: <b style="color:var(--gold)">${fmt(m.balance)} ETB</b> · Min: ${fmt(m.settings.minimum_withdrawal)} ETB</div>
    <div class="warn">⚠️ Multi-account usage = <b>rejection without payment</b>.<br>Admin reviews before paying.</div>
    <label class="label">Amount (ETB)</label>
    <input class="input" id="wamount" type="number" step="0.01" value="${Math.max(m.balance, m.settings.minimum_withdrawal).toFixed(2)}">
    <div class="card" style="margin-top:12px">
      <div style="display:flex;justify-content:space-between"><span style="color:var(--muted)">Method</span><b>${esc(m.wallet_type)}</b></div>
      <div style="display:flex;justify-content:space-between;margin-top:6px"><span style="color:var(--muted)">Wallet</span><b>${esc(m.wallet_number)}</b></div>
    </div>
    <div class="btn-row"><button class="btn dark" data-close>Cancel</button><button class="btn gold" id="doWithdraw">🚀 Request</button></div>`);
  $('#doWithdraw').addEventListener('click', async () => {
    const amount = parseFloat($('#wamount').value || 0);
    const r = await api('/api/withdraw', { method:'POST', body:{ amount } });
    if (r.ok) { toast('⏳ Requested'); closeModal(); await refresh(); }
    else {
      const err = r.data.error || 'Failed';
      if (err === 'sunday') toast('🛑 Sunday — no withdrawals');
      else toast(err);
    }
  });
}

function openServices(){
  const items = STATE.me?.services || [];
  openModal(`<div class="mh"><h3>Services & Support</h3><button class="close" data-close>✕</button></div>
    <div class="muted">Contact <b>@AmanM_12</b> for any service.</div>
    ${items.map(s => `<a class="row" href="https://t.me/AmanM_12" target="_blank" style="text-decoration:none;color:inherit;margin-bottom:8px">
      <div class="ico">${s.icon}</div><div class="body"><div class="title">${esc(s.title)}</div><div class="desc">${esc(s.desc)}</div></div></a>`).join('')}`);
}

async function refresh(){
  if (!(await loadMe())) return;
  renderApp();
  if (!STATE.me.captcha_passed) { await startCaptcha(); showGate('captcha'); return; }
  if (!STATE.me.verified) { showGate('channels'); await loadChannelStatus(true); return; }
  await loadTasks(); showApp();
}

async function verifyCaptcha(){
  const ans = ($('#captchaA').value || '').trim();
  if (!ans) { toast('Enter answer'); return; }
  const btn = $('#captchaBtn'); btn.disabled = true; btn.textContent = 'Checking…';
  const r = await api('/api/captcha/verify', { method:'POST', body:{ token: STATE.captchaToken, answer: ans } });
  if (r.ok) {
    toast('✅ Verified');
    await loadMe(); renderApp();
    showGate('channels');
    await loadChannelStatus(true);
  } else {
    if (r.data.token && r.data.question) {
      STATE.captchaToken = r.data.token;
      $('#captchaQ').textContent = r.data.question;
    } else {
      await startCaptcha();
    }
    $('#captchaA').value = '';
    const inp = $('#captchaA');
    inp.classList.add('err');
    setTimeout(() => inp.classList.remove('err'), 400);
    toast('❌ Wrong answer — try again');
  }
  btn.disabled = false; btn.textContent = '✅ Verify Answer';
}

async function verifyChannels(){
  const btn = $('#verifyBtn');
  const origText = btn.textContent;
  btn.disabled = true; btn.textContent = 'Checking…';
  const r = await api('/api/verify', { method:'POST' });
  if (r.ok && r.data.verified) {
    toast('✅ All channels verified!');
    await refresh();
  } else {
    // Update per-channel display with fresh data
    const chans = r.data.channels || [];
    const joined = chans.filter(c => c.joined).length;
    const total = chans.length;
    const remaining = total - joined;
    $('#channelStatus').innerHTML = `<span style="color:var(--gold)">${remaining} channel${remaining>1?'s':''} still needed</span> · ${joined}/${total} joined`;
    $('#channelsList').innerHTML = chans.map(c => `
      <a class="channel-item ${c.joined ? 'joined' : ''}" href="${esc(c.url)}" target="_blank" rel="noopener">
        <div class="ico">${c.joined ? '✅' : '📢'}</div>
        <div><div class="nm">${esc(c.name)}</div><div class="un">${esc(c.username)}</div></div>
        <div class="go">${c.joined ? '✓ Joined' : 'Join →'}</div>
      </a>`).join('');
    toast(`⚠️ ${remaining} channel(s) still needed`);
    btn.disabled = false;
    btn.textContent = '🔄 Verify Membership';
  }
}

$('#captchaBtn')?.addEventListener('click', verifyCaptcha);
$('#captchaA')?.addEventListener('keydown', e => { if (e.key === 'Enter') verifyCaptcha(); });
$('#verifyBtn')?.addEventListener('click', verifyChannels);
$('#dailyBtn')?.addEventListener('click', async () => {
  const r = await api('/api/daily-bonus', { method:'POST' });
  if (r.ok) { toast('🎁 +' + fmt(r.data.reward) + ' ETB'); await refresh(); }
  else if (r.data.error === 'cooldown') {
    const rem = r.data.remaining || 0;
    const h = Math.floor(rem/3600), mn = Math.floor((rem%3600)/60);
    toast(`⏳ Today already claimed. Next in ${h}h ${mn}m`);
  } else toast(r.data.error || 'Failed');
});
$('#inviteBtn')?.addEventListener('click', openInvite);
$('#refRow')?.addEventListener('click', openInvite);
$('#walletBtn')?.addEventListener('click', openWallet);
$('#walletBtn2')?.addEventListener('click', openWallet);
$('#withdrawBtn')?.addEventListener('click', openWithdraw);
$('#servicesBtn')?.addEventListener('click', openServices);

(async () => {
  try {
    if (!(await loadMe())) return;
    renderApp();
    if (!STATE.me.captcha_passed) { await startCaptcha(); showGate('captcha'); }
    else if (!STATE.me.verified) { showGate('channels'); await loadChannelStatus(true); }
    else { await loadTasks(); showApp(); }
  } catch(e) {
    console.error(e);
    $('#loading').innerHTML = '<div class="center"><div>Failed. Refresh.</div></div>';
  }
})();
</script>
</body>
</html>
"""
