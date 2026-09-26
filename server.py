# ═══════════════════════════════════════════════════════════════
# 🦅 FALCON WORLD — Complete Production System
# Render: uvicorn server:app --host 0.0.0.0 --port $PORT
# ═══════════════════════════════════════════════════════════════

import json, hmac, hashlib, time, asyncio, os, re, sqlite3, html, secrets
from datetime import datetime, timedelta
from urllib.parse import parse_qsl
from typing import Optional

from fastapi import FastAPI, Request, Body, Header
from fastapi.responses import HTMLResponse, JSONResponse
import httpx

# ═══════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
BOT_USERNAME = os.getenv("BOT_USERNAME", "FalconWorld_Bot").strip().lstrip("@")
MINI_APP_URL = os.getenv("MINI_APP_URL", "https://falcon-world.onrender.com/app").strip()
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://falcon-world.onrender.com/webhook").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
DB_PATH = os.getenv("DB_PATH", "falcon_world.db").strip() or "falcon_world.db"
SUPPORT_USERNAME = "@AmanM_12"
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""

DEFAULT_DAILY = 0.50
DEFAULT_REFERRAL = 2.00
DEFAULT_MIN_WITHDRAW = 30.00
REFERRAL_COOLDOWN_HOURS = 1

DEFAULT_CHANNELS = [
    {"username": "@ethiocashflow", "name": "Ethio Cash Flow", "url": "https://t.me/ethiocashflow"},
    {"username": "@Sheger_tech1", "name": "Sheger Tech", "url": "https://t.me/Sheger_tech1"},
    {"username": "@EthioVortex1", "name": "Ethio Vortex", "url": "https://t.me/EthioVortex1"},
    {"username": "@AmanIncomeLab", "name": "Aman Income Lab", "url": "https://t.me/AmanIncomeLab"},
    {"username": "@OnlineIncomeHub07", "name": "Online Income Hub", "url": "https://t.me/OnlineIncomeHub07"},
    {"username": "@Paymentprooff2", "name": "Payment Proof", "url": "https://t.me/Paymentprooff2"},
]

# ═══════════════════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════════════════
def db():
    conn = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn


def _col_exists(conn, table, col):
    return col in {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def init_db():
    conn = db()
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT DEFAULT '',
            first_name TEXT DEFAULT '',
            last_name TEXT DEFAULT '',
            balance REAL NOT NULL DEFAULT 0,
            total_earned REAL NOT NULL DEFAULT 0,
            total_withdrawn REAL NOT NULL DEFAULT 0,
            referral_earnings REAL NOT NULL DEFAULT 0,
            daily_earnings REAL NOT NULL DEFAULT 0,
            task_earnings REAL NOT NULL DEFAULT 0,
            admin_credits REAL NOT NULL DEFAULT 0,
            verified INTEGER NOT NULL DEFAULT 0,
            banned INTEGER NOT NULL DEFAULT 0,
            ban_reason TEXT DEFAULT '',
            referred_by INTEGER,
            referral_paid INTEGER NOT NULL DEFAULT 0,
            daily_last_claim INTEGER NOT NULL DEFAULT 0,
            wallet_type TEXT,
            wallet_number TEXT,
            wallet_suspicious INTEGER NOT NULL DEFAULT 0,
            risk_score INTEGER NOT NULL DEFAULT 0,
            risk_flags TEXT DEFAULT '',
            device_hash TEXT DEFAULT '',
            ip_hash TEXT DEFAULT '',
            captcha_passed INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL,
            last_active INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS captcha_sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            amount REAL NOT NULL,
            balance_before REAL NOT NULL,
            balance_after REAL NOT NULL,
            description TEXT DEFAULT '',
            reference_id TEXT DEFAULT '',
            admin_id INTEGER,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            wallet_type TEXT NOT NULL,
            wallet_number TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            risk_status TEXT DEFAULT 'normal',
            admin_id INTEGER,
            rejection_reason TEXT DEFAULT '',
            created_at INTEGER NOT NULL,
            reviewed_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            reward REAL NOT NULL DEFAULT 0,
            url TEXT DEFAULT '',
            proof_type TEXT DEFAULT 'text',
            active INTEGER NOT NULL DEFAULT 1,
            created_at INTEGER NOT NULL,
            created_by INTEGER
        );
        CREATE TABLE IF NOT EXISTS task_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            proof_text TEXT DEFAULT '',
            proof_image TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            admin_id INTEGER,
            rejection_reason TEXT DEFAULT '',
            created_at INTEGER NOT NULL,
            reviewed_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS required_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS fraud_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            risk_score INTEGER NOT NULL DEFAULT 0,
            details TEXT DEFAULT '',
            ip_hash TEXT DEFAULT '',
            device_hash TEXT DEFAULT '',
            resolved INTEGER NOT NULL DEFAULT 0,
            resolved_by INTEGER,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS admin_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            target TEXT DEFAULT '',
            before_value TEXT DEFAULT '',
            after_value TEXT DEFAULT '',
            created_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_tx_user ON transactions(user_id);
        CREATE INDEX IF NOT EXISTS idx_wd_status ON withdrawals(status);
        CREATE INDEX IF NOT EXISTS idx_wd_user ON withdrawals(user_id);
        CREATE INDEX IF NOT EXISTS idx_sub_status ON task_submissions(status);
        CREATE INDEX IF NOT EXISTS idx_users_referred ON users(referred_by);
        """)

        for col, ddl in {
            "last_name": "TEXT DEFAULT ''",
            "total_earned": "REAL NOT NULL DEFAULT 0",
            "total_withdrawn": "REAL NOT NULL DEFAULT 0",
            "referral_earnings": "REAL NOT NULL DEFAULT 0",
            "daily_earnings": "REAL NOT NULL DEFAULT 0",
            "task_earnings": "REAL NOT NULL DEFAULT 0",
            "admin_credits": "REAL NOT NULL DEFAULT 0",
            "ban_reason": "TEXT DEFAULT ''",
            "risk_score": "INTEGER NOT NULL DEFAULT 0",
            "risk_flags": "TEXT DEFAULT ''",
            "device_hash": "TEXT DEFAULT ''",
            "ip_hash": "TEXT DEFAULT ''",
            "captcha_passed": "INTEGER NOT NULL DEFAULT 0",
            "last_active": "INTEGER NOT NULL DEFAULT 0",
        }.items():
            if not _col_exists(conn, "users", col):
                conn.execute(f"ALTER TABLE users ADD COLUMN {col} {ddl}")

        if conn.execute("SELECT COUNT(*) c FROM required_channels").fetchone()["c"] == 0:
            now = int(time.time())
            for i, c in enumerate(DEFAULT_CHANNELS):
                conn.execute(
                    "INSERT OR IGNORE INTO required_channels(username,name,url,active,sort_order,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                    (c["username"], c["name"], c["url"], 1, i, now, now),
                )

        for k, v in {
            "daily_reward": DEFAULT_DAILY,
            "referral_reward": DEFAULT_REFERRAL,
            "minimum_withdrawal": DEFAULT_MIN_WITHDRAW,
            "maintenance_mode": "0",
            "support_username": SUPPORT_USERNAME,
        }.items():
            conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, str(v)))
        conn.commit()
    finally:
        conn.close()


def get_setting(key, default=None, kind=float):
    conn = db()
    try:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        if not row: return default
        try:
            if kind == float: return float(row["value"])
            if kind == int: return int(float(row["value"]))
            return row["value"]
        except Exception:
            return default
    finally:
        conn.close()


def set_setting(key, value):
    conn = db()
    try:
        conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     (key, str(value)))
        conn.commit()
    finally:
        conn.close()


def is_maintenance():
    return get_setting("maintenance_mode", "0", kind=str) == "1"


def _r2(x): return round(float(x) + 1e-9, 2)


def credit(user_id, amount, kind, description="", reference_id="", admin_id=None):
    amount = _r2(amount)
    if amount <= 0: return False, "Invalid amount"
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT balance FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            conn.execute("ROLLBACK"); return False, "User not found"
        before = float(row["balance"])
        after = _r2(before + amount)
        conn.execute("UPDATE users SET balance=?, total_earned=ROUND(total_earned+?,8), updated_at=? WHERE user_id=?",
                     (after, amount, int(time.time()), user_id))
        col = {"daily":"daily_earnings","referral":"referral_earnings","task":"task_earnings","admin":"admin_credits"}.get(kind)
        if col:
            conn.execute(f"UPDATE users SET {col}=ROUND({col}+?,8) WHERE user_id=?", (amount, user_id))
        conn.execute(
            """INSERT INTO transactions(user_id,type,amount,balance_before,balance_after,description,reference_id,admin_id,created_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (user_id, kind.upper() + "_CREDIT", amount, before, after, description, str(reference_id), admin_id, int(time.time())),
        )
        conn.execute("COMMIT")
        return True, after
    except Exception as e:
        try: conn.execute("ROLLBACK")
        except: pass
        return False, str(e)
    finally:
        conn.close()


def debit(user_id, amount, kind, description="", reference_id=""):
    amount = _r2(amount)
    if amount <= 0: return False, "Invalid amount"
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT balance FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            conn.execute("ROLLBACK"); return False, "User not found"
        before = float(row["balance"])
        if before < amount:
            conn.execute("ROLLBACK"); return False, "Insufficient balance"
        after = _r2(before - amount)
        conn.execute("UPDATE users SET balance=?, updated_at=? WHERE user_id=?", (after, int(time.time()), user_id))
        conn.execute(
            """INSERT INTO transactions(user_id,type,amount,balance_before,balance_after,description,reference_id,created_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (user_id, kind.upper(), amount, before, after, description, str(reference_id), int(time.time())),
        )
        conn.execute("COMMIT")
        return True, after
    except Exception as e:
        try: conn.execute("ROLLBACK")
        except: pass
        return False, str(e)
    finally:
        conn.close()


def ensure_user(user_id, username="", first_name="", last_name="", referred_by=None):
    now = int(time.time())
    conn = db()
    try:
        row = conn.execute("SELECT user_id, referred_by FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            conn.execute(
                """INSERT INTO users(user_id,username,first_name,last_name,referred_by,created_at,updated_at,last_active)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (user_id, username or "", first_name or "", last_name or "", referred_by, now, now, now),
            )
        else:
            conn.execute("UPDATE users SET username=?, first_name=?, last_name=?, last_active=?, updated_at=? WHERE user_id=?",
                         (username or "", first_name or "", last_name or "", now, now, user_id))
            if referred_by and not row["referred_by"] and referred_by != user_id:
                conn.execute("UPDATE users SET referred_by=? WHERE user_id=?", (referred_by, user_id))
        conn.commit()
    finally:
        conn.close()


def get_user(user_id):
    conn = db()
    try:
        return conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    finally:
        conn.close()


def is_admin(uid): return int(uid) in ADMIN_IDS


def is_banned(uid):
    u = get_user(uid); return bool(u and u["banned"])


def log_admin(admin_id, action, target="", before="", after=""):
    conn = db()
    try:
        conn.execute("INSERT INTO admin_logs(admin_id,action,target,before_value,after_value,created_at) VALUES(?,?,?,?,?,?)",
                     (admin_id, action, str(target), str(before), str(after), int(time.time())))
        conn.commit()
    finally:
        conn.close()


def add_risk(user_id, points, flag, details=""):
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT risk_score, risk_flags FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            conn.execute("ROLLBACK"); return
        new_score = min(999, int(row["risk_score"] or 0) + int(points))
        flags = [f for f in (row["risk_flags"] or "").split(",") if f]
        if flag and flag not in flags: flags.append(flag)
        conn.execute("UPDATE users SET risk_score=?, risk_flags=?, updated_at=? WHERE user_id=?",
                     (new_score, ",".join(flags), int(time.time()), user_id))
        conn.execute("INSERT INTO fraud_events(user_id,event_type,risk_score,details,created_at) VALUES(?,?,?,?,?)",
                     (user_id, flag, points, details, int(time.time())))
        conn.execute("COMMIT")
    except Exception:
        try: conn.execute("ROLLBACK")
        except: pass
    finally:
        conn.close()


def check_wallet_duplicate(user_id, wallet_number):
    conn = db()
    try:
        return int(conn.execute("SELECT COUNT(*) c FROM users WHERE wallet_number=? AND user_id!=?",
                                 (wallet_number, user_id)).fetchone()["c"])
    finally:
        conn.close()


def update_fingerprints(user_id, device_hash="", ip_hash=""):
    conn = db()
    try:
        upd, params = [], []
        if device_hash: upd.append("device_hash=?"); params.append(device_hash)
        if ip_hash: upd.append("ip_hash=?"); params.append(ip_hash)
        if not upd: return
        params.append(user_id)
        conn.execute(f"UPDATE users SET {','.join(upd)} WHERE user_id=?", params)
        conn.commit()
    finally:
        conn.close()


def detect_device_sharing(device_hash):
    if not device_hash: return 0
    conn = db()
    try:
        return int(conn.execute("SELECT COUNT(DISTINCT user_id) c FROM users WHERE device_hash=?", (device_hash,)).fetchone()["c"])
    finally:
        conn.close()


def detect_ip_sharing(ip_hash):
    if not ip_hash: return 0
    conn = db()
    try:
        return int(conn.execute("SELECT COUNT(DISTINCT user_id) c FROM users WHERE ip_hash=? AND last_active > ?",
                                 (ip_hash, int(time.time())-86400)).fetchone()["c"])
    finally:
        conn.close()


def get_referral_count(uid):
    conn = db()
    try:
        return int(conn.execute("SELECT COUNT(*) c FROM users WHERE referred_by=? AND referral_paid=1", (uid,)).fetchone()["c"])
    finally:
        conn.close()


def get_all_referrals(uid, limit=500):
    conn = db()
    try:
        return conn.execute(
            "SELECT user_id,username,first_name,last_name,verified,referral_paid,created_at FROM users WHERE referred_by=? ORDER BY user_id DESC LIMIT ?",
            (uid, limit)).fetchall()
    finally:
        conn.close()


def pay_referral_if_eligible(user_id):
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        child = conn.execute("SELECT referred_by, verified, referral_paid, created_at FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not child or not child["verified"] or child["referral_paid"]:
            conn.execute("ROLLBACK"); return None
        ref_id = child["referred_by"]
        if not ref_id or ref_id == user_id:
            conn.execute("UPDATE users SET referral_paid=1 WHERE user_id=?", (user_id,))
            conn.execute("COMMIT"); return None
        if int(time.time()) - int(child["created_at"]) < REFERRAL_COOLDOWN_HOURS * 3600:
            conn.execute("ROLLBACK"); return None
        ref = conn.execute("SELECT banned, risk_score FROM users WHERE user_id=?", (ref_id,)).fetchone()
        if not ref or ref["banned"]:
            conn.execute("UPDATE users SET referral_paid=1 WHERE user_id=?", (user_id,))
            conn.execute("COMMIT"); return None
        reward = get_setting("referral_reward", DEFAULT_REFERRAL, kind=float)
        cur = conn.execute("UPDATE users SET referral_paid=1 WHERE user_id=? AND referral_paid=0", (user_id,))
        if cur.rowcount != 1:
            conn.execute("ROLLBACK"); return None
        conn.execute("COMMIT")
    except Exception:
        try: conn.execute("ROLLBACK")
        except: pass
        return None
    finally:
        conn.close()
    ok, _ = credit(ref_id, reward, "referral", f"Referral reward for user {user_id}", reference_id=str(user_id))
    return reward if ok else None


def check_referral_velocity(referrer_id):
    conn = db()
    try:
        return int(conn.execute(
            "SELECT COUNT(*) c FROM users WHERE referred_by=? AND referral_paid=1 AND created_at > ?",
            (referrer_id, int(time.time()) - 3600)).fetchone()["c"])
    finally:
        conn.close()


def claim_daily(user_id):
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT banned, verified, daily_last_claim FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            conn.execute("ROLLBACK"); return False, {"error": "user_not_found"}
        if row["banned"]:
            conn.execute("ROLLBACK"); return False, {"error": "banned"}
        if not row["verified"]:
            conn.execute("ROLLBACK"); return False, {"error": "not_verified"}
        last = int(row["daily_last_claim"] or 0)
        now = int(time.time())
        if last and (now - last) < 86400:
            remaining = 86400 - (now - last)
            conn.execute("ROLLBACK")
            return False, {"error": "cooldown", "remaining": remaining}
        reward = get_setting("daily_reward", DEFAULT_DAILY, kind=float)
        cur = conn.execute("UPDATE users SET daily_last_claim=? WHERE user_id=? AND (daily_last_claim=0 OR ?-daily_last_claim >= 86400)",
                           (now, user_id, now))
        if cur.rowcount != 1:
            conn.execute("ROLLBACK")
            return False, {"error": "cooldown", "remaining": 86400}
        conn.execute("COMMIT")
    except Exception:
        try: conn.execute("ROLLBACK")
        except: pass
        return False, {"error": "server_error"}
    finally:
        conn.close()
    ok, balance = credit(user_id, reward, "daily", "Daily bonus")
    if not ok: return False, {"error": "credit_failed"}
    return True, {"reward": reward, "balance": balance, "next_in": 86400}


def daily_status(user_id):
    u = get_user(user_id)
    if not u: return {"available": False, "remaining": 0}
    last = int(u["daily_last_claim"] or 0)
    now = int(time.time())
    if not last or (now - last) >= 86400:
        return {"available": True, "remaining": 0, "reward": get_setting("daily_reward", DEFAULT_DAILY, kind=float)}
    return {"available": False, "remaining": 86400 - (now - last), "reward": get_setting("daily_reward", DEFAULT_DAILY, kind=float)}


def validate_wallet(wallet_type, number):
    wallet_type = (wallet_type or "").strip().lower()
    number = (number or "").strip()
    if wallet_type == "cbe":
        if not re.fullmatch(r"1000\d{9}", number):
            return False, "CBE must be 13 digits starting with 1000."
        return True, "CBE"
    if wallet_type == "telebirr":
        if not re.fullmatch(r"(09|07)\d{8}", number):
            return False, "Telebirr must be 10 digits starting with 09 or 07."
        return True, "Telebirr"
    return False, "Invalid wallet type."


def save_wallet(user_id, wallet_type, number):
    ok, res = validate_wallet(wallet_type, number)
    if not ok: return False, res, False
    normalized = res
    dup = check_wallet_duplicate(user_id, number)
    suspicious = dup > 0
    conn = db()
    try:
        conn.execute("UPDATE users SET wallet_type=?, wallet_number=?, wallet_suspicious=?, updated_at=? WHERE user_id=?",
                     (normalized, number, 1 if suspicious else 0, int(time.time()), user_id))
        conn.commit()
    finally:
        conn.close()
    if suspicious:
        add_risk(user_id, 40, "duplicate_wallet", f"Wallet {normalized} used by {dup} other user(s)")
    return True, "Wallet saved.", suspicious


def create_withdrawal(user_id, amount):
    amount = _r2(amount)
    minimum = get_setting("minimum_withdrawal", DEFAULT_MIN_WITHDRAW, kind=float)
    if amount < minimum:
        return False, f"Minimum withdrawal is {minimum:.2f} ETB."
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        u = conn.execute("SELECT banned, wallet_type, wallet_number, balance FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not u:
            conn.execute("ROLLBACK"); return False, "User not found."
        if u["banned"]:
            conn.execute("ROLLBACK"); return False, "Account banned."
        if not u["wallet_type"] or not u["wallet_number"]:
            conn.execute("ROLLBACK"); return False, "Save your wallet first."
        if float(u["balance"]) < amount:
            conn.execute("ROLLBACK"); return False, "Insufficient balance."
        pending = conn.execute("SELECT id FROM withdrawals WHERE user_id=? AND status='pending' LIMIT 1", (user_id,)).fetchone()
        if pending:
            conn.execute("ROLLBACK"); return False, "You already have a pending withdrawal."
        cur = conn.execute(
            """INSERT INTO withdrawals(user_id,amount,wallet_type,wallet_number,status,created_at)
               VALUES(?,?,?,?,?,?)""",
            (user_id, amount, u["wallet_type"], u["wallet_number"], "pending", int(time.time())),
        )
        wid = cur.lastrowid
        conn.execute("COMMIT")
    except Exception:
        try: conn.execute("ROLLBACK")
        except: pass
        return False, "Server error."
    finally:
        conn.close()
    ok, new_bal = debit(user_id, amount, "withdrawal_hold", f"Withdrawal #{wid}")
    if not ok:
        conn = db()
        try: conn.execute("DELETE FROM withdrawals WHERE id=?", (wid,)); conn.commit()
        finally: conn.close()
        return False, "Balance error."
    return True, {"withdrawal_id": wid, "amount": amount}


def get_pending_withdrawals(limit=20):
    conn = db()
    try:
        return conn.execute("SELECT * FROM withdrawals WHERE status='pending' ORDER BY id ASC LIMIT ?", (limit,)).fetchall()
    finally:
        conn.close()


def approve_withdrawal(wid, admin_id):
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        w = conn.execute("SELECT * FROM withdrawals WHERE id=? AND status='pending'", (wid,)).fetchone()
        if not w:
            conn.execute("ROLLBACK"); return False, "Not pending."
        conn.execute("UPDATE withdrawals SET status='approved', admin_id=?, reviewed_at=? WHERE id=?",
                     (admin_id, int(time.time()), wid))
        conn.execute("UPDATE users SET total_withdrawn=ROUND(total_withdrawn+?,8) WHERE user_id=?",
                     (float(w["amount"]), w["user_id"]))
        conn.execute("COMMIT")
        return True, dict(w)
    except Exception:
        try: conn.execute("ROLLBACK")
        except: pass
        return False, "Server error"
    finally:
        conn.close()


def reject_withdrawal(wid, admin_id, reason=""):
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        w = conn.execute("SELECT * FROM withdrawals WHERE id=? AND status='pending'", (wid,)).fetchone()
        if not w:
            conn.execute("ROLLBACK"); return False, "Not pending."
        conn.execute("UPDATE withdrawals SET status='rejected', admin_id=?, reviewed_at=?, rejection_reason=? WHERE id=?",
                     (admin_id, int(time.time()), reason or "", wid))
        conn.execute("COMMIT")
    except Exception:
        try: conn.execute("ROLLBACK")
        except: pass
        return False, "Server error"
    finally:
        conn.close()
    credit(int(w["user_id"]), float(w["amount"]), "admin", f"Withdrawal #{wid} refund", admin_id=admin_id)
    return True, dict(w)


def get_channels(active_only=True):
    conn = db()
    try:
        sql = "SELECT * FROM required_channels " + ("WHERE active=1 " if active_only else "") + "ORDER BY sort_order ASC, id ASC"
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def get_tasks(active_only=True):
    conn = db()
    try:
        sql = "SELECT * FROM tasks " + ("WHERE active=1 " if active_only else "") + "ORDER BY id DESC"
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def get_user_task_status(user_id, task_id):
    conn = db()
    try:
        return conn.execute("SELECT * FROM task_submissions WHERE user_id=? AND task_id=? ORDER BY id DESC LIMIT 1",
                            (user_id, task_id)).fetchone()
    finally:
        conn.close()


def submit_task(user_id, task_id, proof_text="", proof_image=""):
    if not (proof_text or proof_image): return False, "Proof required."
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        t = conn.execute("SELECT * FROM tasks WHERE id=? AND active=1", (task_id,)).fetchone()
        if not t:
            conn.execute("ROLLBACK"); return False, "Task not found."
        last = conn.execute("SELECT status FROM task_submissions WHERE user_id=? AND task_id=? ORDER BY id DESC LIMIT 1",
                            (user_id, task_id)).fetchone()
        if last and last["status"] == "pending":
            conn.execute("ROLLBACK"); return False, "Previous submission pending."
        if last and last["status"] == "approved":
            conn.execute("ROLLBACK"); return False, "Already approved."
        cur = conn.execute(
            "INSERT INTO task_submissions(task_id,user_id,proof_text,proof_image,status,created_at) VALUES(?,?,?,?,?,?)",
            (task_id, user_id, proof_text[:2000], proof_image[:500], "pending", int(time.time())))
        sid = cur.lastrowid
        conn.execute("COMMIT")
        return True, {"submission_id": sid, "task": dict(t)}
    except Exception:
        try: conn.execute("ROLLBACK")
        except: pass
        return False, "Server error"
    finally:
        conn.close()


def approve_task_submission(sid, admin_id):
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        s = conn.execute(
            "SELECT ts.*, t.reward, t.title FROM task_submissions ts JOIN tasks t ON t.id=ts.task_id WHERE ts.id=? AND ts.status='pending'",
            (sid,)).fetchone()
        if not s:
            conn.execute("ROLLBACK"); return False, "Not pending."
        conn.execute("UPDATE task_submissions SET status='approved', admin_id=?, reviewed_at=? WHERE id=?",
                     (admin_id, int(time.time()), sid))
        conn.execute("COMMIT")
    except Exception:
        try: conn.execute("ROLLBACK")
        except: pass
        return False, "Server error"
    finally:
        conn.close()
    credit(int(s["user_id"]), float(s["reward"]), "task", f"Task: {s['title']}", reference_id=str(sid))
    return True, dict(s)


def reject_task_submission(sid, admin_id, reason=""):
    conn = db()
    try:
        conn.execute(
            "UPDATE task_submissions SET status='rejected', admin_id=?, reviewed_at=?, rejection_reason=? WHERE id=? AND status='pending'",
            (admin_id, int(time.time()), reason or "", sid))
        conn.commit()
        return True
    finally:
        conn.close()


async def tg(method, data=None):
    if not BOT_TOKEN: return {"ok": False, "description": "BOT_TOKEN missing"}
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            r = await client.post(f"{TELEGRAM_API}/{method}", json=data or {})
            try: return r.json()
            except: return {"ok": False, "description": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"ok": False, "description": str(e)}


async def send(chat_id, text, reply_markup=None):
    d = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if reply_markup: d["reply_markup"] = reply_markup
    return await tg("sendMessage", d)


async def send_admin(text, kb=None):
    for aid in ADMIN_IDS:
        await send(aid, text, kb)


async def check_channel_membership(user_id, username):
    r = await tg("getChatMember", {"chat_id": username, "user_id": user_id})
    if not r.get("ok"): return False
    st = r.get("result", {}).get("status")
    if st in {"member", "administrator", "creator"}: return True
    if st == "restricted" and r.get("result", {}).get("is_member") is True: return True
    return False


async def verify_all_channels(user_id):
    channels = get_channels(active_only=True)
    results = []
    for c in channels:
        joined = await check_channel_membership(user_id, c["username"])
        results.append({"id": c["id"], "username": c["username"], "name": c["name"], "url": c["url"], "joined": joined})
    all_joined = all(r["joined"] for r in results) and len(results) > 0
    return all_joined, results


def make_captcha(user_id):
    a = secrets.randbelow(9) + 2
    b = secrets.randbelow(9) + 1
    op = secrets.choice(["+", "-"])
    if op == "+": ans = a + b
    else:
        if a < b: a, b = b, a
        ans = a - b
    q = f"{a} {op} {b} = ?"
    token = secrets.token_urlsafe(24)
    conn = db()
    try:
        conn.execute("DELETE FROM captcha_sessions WHERE user_id=?", (user_id,))
        conn.execute("INSERT INTO captcha_sessions(token,user_id,question,answer,attempts,created_at,expires_at) VALUES(?,?,?,?,?,?,?)",
                     (token, user_id, q, str(ans), 0, int(time.time()), int(time.time()) + 300))
        conn.commit()
    finally:
        conn.close()
    return token, q


def verify_captcha(token, answer):
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM captcha_sessions WHERE token=?", (token,)).fetchone()
        if not row:
            conn.execute("ROLLBACK"); return False, "expired"
        if int(row["expires_at"]) < int(time.time()):
            conn.execute("DELETE FROM captcha_sessions WHERE token=?", (token,))
            conn.execute("COMMIT"); return False, "expired"
        if int(row["attempts"]) >= 5:
            conn.execute("DELETE FROM captcha_sessions WHERE token=?", (token,))
            conn.execute("COMMIT"); return False, "too_many_attempts"
        if str(row["answer"]).strip() != str(answer).strip():
            conn.execute("UPDATE captcha_sessions SET attempts=attempts+1 WHERE token=?", (token,))
            conn.execute("COMMIT"); return False, "wrong"
        conn.execute("UPDATE users SET captcha_passed=1 WHERE user_id=?", (row["user_id"],))
        conn.execute("DELETE FROM captcha_sessions WHERE token=?", (token,))
        conn.execute("COMMIT")
        return True, "ok"
    except Exception:
        try: conn.execute("ROLLBACK")
        except: pass
        return False, "error"
    finally:
        conn.close()


def main_kb():
    return {"inline_keyboard": [[{"text": "🚀 Open Falcon World", "web_app": {"url": MINI_APP_URL}}]]}


def parse_start_ref(text):
    parts = text.split(maxsplit=1)
    if len(parts) != 2: return None
    p = parts[1].strip()
    if p.startswith("ref_") and p[4:].isdigit(): return int(p[4:])
    if p.isdigit(): return int(p)
    return None


async def handle_message(msg):
    chat = msg.get("chat", {}); user = msg.get("from", {})
    chat_id = chat.get("id"); uid = user.get("id")
    if not chat_id or not uid: return
    text = (msg.get("text") or "").strip()
    referred_by = parse_start_ref(text) if text.startswith("/start") else None
    ensure_user(uid, user.get("username", ""), user.get("first_name", ""), user.get("last_name", ""), referred_by)
    if is_banned(uid) and not is_admin(uid):
        await send(chat_id, "🚫 Your Falcon World account is restricted.\nContact: " + SUPPORT_USERNAME)
        return

    if text.startswith("/start"):
        await send(chat_id,
            "🦅 <b>WELCOME TO FALCON WORLD</b>\n\n"
            "💰 Earn & Complete Tasks\n🎁 Daily Rewards\n👥 Referral Rewards\n🚀 New Opportunities\n\n"
            f"💱 USDT Exchange & Advertising\n📣 Contact: {SUPPORT_USERNAME}\n\n"
            "Tap below to begin 👇", main_kb())
        return

    if text == "/id":
        await send(chat_id, f"🆔 Your Telegram ID: <code>{uid}</code>"); return

    if text == "/help":
        await send(chat_id,
            "🦅 <b>Falcon World — Help</b>\n\n"
            "1. Tap Open Falcon World\n2. Complete verification\n"
            "3. Claim daily bonus, tasks, referrals\n4. Save CBE/Telebirr wallet\n5. Withdraw at ≥30 ETB\n\n"
            f"Support: {SUPPORT_USERNAME}", main_kb())
        return

    if text.startswith("/admin") and is_admin(uid):
        await send_admin_dashboard(chat_id); return

    if text.startswith("/checkuser") and is_admin(uid):
        parts = text.split()
        if len(parts) != 2 or not parts[1].isdigit():
            await send(chat_id, "Usage: /checkuser USER_ID"); return
        await send_user_audit(chat_id, int(parts[1])); return

    if text.startswith("/addbalance") and is_admin(uid):
        p = text.split()
        if len(p) != 3:
            await send(chat_id, "Usage: /addbalance USER_ID AMOUNT"); return
        try: tid = int(p[1]); amt = float(p[2])
        except: await send(chat_id, "Invalid input."); return
        if not get_user(tid): await send(chat_id, "User not found."); return
        if amt == 0: await send(chat_id, "Amount cannot be 0."); return
        before = float(get_user(tid)["balance"])
        if amt > 0: credit(tid, amt, "admin", f"Admin credit by {uid}", admin_id=uid)
        else: debit(tid, abs(amt), "admin", f"Admin debit by {uid}")
        log_admin(uid, "addbalance", tid, before, before+amt)
        await send(chat_id, f"✅ Adjusted {amt:+.2f} ETB for {tid}.")
        try: await send(tid, f"💼 Admin balance update: <b>{amt:+.2f} ETB</b>")
        except: pass
        return

    if text.startswith("/ban") and is_admin(uid):
        p = text.split()
        if len(p) < 2 or not p[1].isdigit():
            await send(chat_id, "Usage: /ban USER_ID [reason]"); return
        tid = int(p[1]); reason = " ".join(p[2:]) or "Policy violation"
        conn = db()
        try:
            conn.execute("UPDATE users SET banned=1, ban_reason=?, updated_at=? WHERE user_id=?", (reason, int(time.time()), tid))
            conn.commit()
        finally: conn.close()
        log_admin(uid, "ban", tid, "", reason)
        await send(chat_id, f"🚫 Banned {tid}.")
        try: await send(tid, f"🚫 Your account is restricted.\nReason: {reason}")
        except: pass
        return

    if text.startswith("/unban") and is_admin(uid):
        p = text.split()
        if len(p) != 2 or not p[1].isdigit():
            await send(chat_id, "Usage: /unban USER_ID"); return
        tid = int(p[1])
        conn = db()
        try:
            conn.execute("UPDATE users SET banned=0, ban_reason='', updated_at=? WHERE user_id=?", (int(time.time()), tid))
            conn.commit()
        finally: conn.close()
        log_admin(uid, "unban", tid)
        await send(chat_id, f"✅ Unbanned {tid}.")
        try: await send(tid, "✅ Your account has been restored.")
        except: pass
        return

    if text.startswith("/setdaily") and is_admin(uid):
        p = text.split()
        if len(p) != 2: await send(chat_id, "Usage: /setdaily AMOUNT"); return
        try: v = float(p[1])
        except: await send(chat_id, "Invalid."); return
        old = get_setting("daily_reward", DEFAULT_DAILY, kind=float)
        set_setting("daily_reward", v); log_admin(uid, "setdaily", "", old, v)
        await send(chat_id, f"✅ Daily = {v:.2f} ETB."); return

    if text.startswith("/setref") and is_admin(uid):
        p = text.split()
        if len(p) != 2: await send(chat_id, "Usage: /setref AMOUNT"); return
        try: v = float(p[1])
        except: await send(chat_id, "Invalid."); return
        old = get_setting("referral_reward", DEFAULT_REFERRAL, kind=float)
        set_setting("referral_reward", v); log_admin(uid, "setref", "", old, v)
        await send(chat_id, f"✅ Referral = {v:.2f} ETB."); return

    if text.startswith("/setminwithdraw") and is_admin(uid):
        p = text.split()
        if len(p) != 2: await send(chat_id, "Usage: /setminwithdraw AMOUNT"); return
        try: v = float(p[1])
        except: await send(chat_id, "Invalid."); return
        old = get_setting("minimum_withdrawal", DEFAULT_MIN_WITHDRAW, kind=float)
        set_setting("minimum_withdrawal", v); log_admin(uid, "setminwithdraw", "", old, v)
        await send(chat_id, f"✅ Min withdrawal = {v:.2f} ETB."); return

    if text == "/channels" and is_admin(uid):
        chans = get_channels(active_only=False)
        if not chans: await send(chat_id, "No channels.")
        else:
            lines = ["📢 <b>Required Channels</b>"]
            for c in chans:
                st = "✅" if c["active"] else "❌"
                lines.append(f"{st} <b>{html.escape(c['name'])}</b> — {html.escape(c['username'])}\n{html.escape(c['url'])}")
            lines.append("\n/addchannel @u | Name | URL\n/removechannel @u\n/editchannel @old | @new | Name | URL\n/togglechannel @u")
            await send(chat_id, "\n\n".join(lines))
        return

    if text.startswith("/addchannel") and is_admin(uid):
        parts = [x.strip() for x in text.split("|", 2)]
        if len(parts) != 3:
            await send(chat_id, "Usage: /addchannel @u | Name | URL"); return
        first = parts[0].replace("/addchannel", "").strip()
        if not first.startswith("@"): first = "@" + first
        username, name, url = first, parts[1], parts[2]
        conn = db()
        try:
            mx = conn.execute("SELECT COALESCE(MAX(sort_order),0) m FROM required_channels").fetchone()["m"]
            conn.execute("INSERT INTO required_channels(username,name,url,active,sort_order,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                         (username, name, url, 1, int(mx)+1, int(time.time()), int(time.time())))
            conn.commit()
        except sqlite3.IntegrityError:
            await send(chat_id, "❌ Channel already exists."); return
        finally: conn.close()
        log_admin(uid, "addchannel", username)
        await send(chat_id, f"✅ Channel added: {html.escape(username)}"); return

    if text.startswith("/removechannel") and is_admin(uid):
        p = text.split()
        if len(p) != 2: await send(chat_id, "Usage: /removechannel @u"); return
        u = p[1] if p[1].startswith("@") else "@"+p[1]
        conn = db()
        try:
            cur = conn.execute("DELETE FROM required_channels WHERE username=?", (u,))
            conn.commit()
        finally: conn.close()
        log_admin(uid, "removechannel", u)
        await send(chat_id, "✅ Removed." if cur.rowcount else "❌ Not found."); return

    if text.startswith("/togglechannel") and is_admin(uid):
        p = text.split()
        if len(p) != 2: await send(chat_id, "Usage: /togglechannel @u"); return
        u = p[1] if p[1].startswith("@") else "@"+p[1]
        conn = db()
        try:
            row = conn.execute("SELECT active FROM required_channels WHERE username=?", (u,)).fetchone()
            if not row: await send(chat_id, "❌ Not found."); return
            new = 0 if row["active"] else 1
            conn.execute("UPDATE required_channels SET active=?, updated_at=? WHERE username=?", (new, int(time.time()), u))
            conn.commit()
        finally: conn.close()
        log_admin(uid, "togglechannel", u, row["active"], new)
        await send(chat_id, f"✅ Now {'active' if new else 'inactive'}."); return

    if text.startswith("/editchannel") and is_admin(uid):
        parts = [x.strip() for x in text.split("|", 3)]
        if len(parts) != 4:
            await send(chat_id, "Usage: /editchannel @old | @new | Name | URL"); return
        old = parts[0].replace("/editchannel", "").strip()
        if not old.startswith("@"): old = "@"+old
        new, name, url = parts[1], parts[2], parts[3]
        if not new.startswith("@"): new = "@"+new
        conn = db()
        try:
            cur = conn.execute("UPDATE required_channels SET username=?, name=?, url=?, updated_at=? WHERE username=?",
                               (new, name, url, int(time.time()), old))
            conn.commit()
        finally: conn.close()
        log_admin(uid, "editchannel", old, old, new)
        await send(chat_id, "✅ Updated." if cur.rowcount else "❌ Not found."); return

    if text.startswith("/addtask") and is_admin(uid):
        parts = text.replace("/addtask", "", 1).strip().split("|")
        if len(parts) != 4:
            await send(chat_id, "Usage: /addtask Title | Description | Reward | URL"); return
        title, desc, reward, url = [x.strip() for x in parts]
        try: reward = float(reward)
        except: await send(chat_id, "Reward must be a number."); return
        conn = db()
        try:
            cur = conn.execute("INSERT INTO tasks(title,description,reward,url,proof_type,active,created_at,created_by) VALUES(?,?,?,?,?,1,?,?)",
                               (title, desc, reward, url, "text", int(time.time()), uid))
            conn.commit()
            tid = cur.lastrowid
        finally: conn.close()
        log_admin(uid, "addtask", tid)
        await send(chat_id, f"✅ Task #{tid} created."); return

    if text.startswith("/deltask") and is_admin(uid):
        p = text.split()
        if len(p) != 2 or not p[1].isdigit(): await send(chat_id, "Usage: /deltask ID"); return
        conn = db()
        try:
            conn.execute("UPDATE tasks SET active=0 WHERE id=?", (int(p[1]),))
            conn.commit()
        finally: conn.close()
        log_admin(uid, "deltask", p[1])
        await send(chat_id, f"✅ Task {p[1]} disabled."); return

    if text == "/tasks" and is_admin(uid):
        tasks = get_tasks(active_only=False)
        if not tasks: await send(chat_id, "No tasks."); return
        lines = ["📋 <b>Tasks</b>"]
        for t in tasks:
            st = "✅" if t["active"] else "❌"
            lines.append(f"{st} #{t['id']} <b>{html.escape(t['title'])}</b> — {t['reward']:.2f} ETB")
        lines.append("\n/deltask ID to disable")
        await send(chat_id, "\n".join(lines)); return

    if text == "/withdrawals" and is_admin(uid):
        wds = get_pending_withdrawals(20)
        if not wds: await send(chat_id, "No pending withdrawals."); return
        for w in wds:
            await send_withdrawal_to_admin(w["id"])
        return

    if text == "/maintenance" and is_admin(uid):
        cur = is_maintenance()
        set_setting("maintenance_mode", "0" if cur else "1")
        await send(chat_id, f"✅ Maintenance mode: {'OFF' if cur else 'ON'}"); return

    if text == "/stats" and is_admin(uid):
        await send_admin_dashboard(chat_id); return

    if is_admin(uid):
        await send(chat_id, "Admin commands:\n/admin /stats /withdrawals /checkuser /ban /unban /addbalance /setdaily /setref /setminwithdraw /channels /addchannel /removechannel /togglechannel /editchannel /addtask /deltask /tasks /maintenance")
    else:
        await send(chat_id, "Tap below to open Falcon World 🚀", main_kb())


def wd_kb(wid):
    return {"inline_keyboard": [
        [{"text": "✅ Approve Payout", "callback_data": f"wdok:{wid}"},
         {"text": "❌ Reject & Refund", "callback_data": f"wdno:{wid}"}],
        [{"text": "👥 View Referrals", "callback_data": f"wdrefs:{wid}:0"},
         {"text": "📊 Full Audit", "callback_data": f"wdaudit:{wid}"}],
        [{"text": "🚫 Ban User", "callback_data": f"wdban:{wid}"}],
    ]}


def sub_kb(sid):
    return {"inline_keyboard": [[
        {"text": "✅ Approve", "callback_data": f"tskok:{sid}"},
        {"text": "❌ Reject", "callback_data": f"tskno:{sid}"},
    ]]}


def fmt_user(u):
    name = html.escape((u["first_name"] or "") + (" " + u["last_name"] if u["last_name"] else "") or u["username"] or str(u["user_id"]))
    un = f"@{html.escape(u['username'])}" if u["username"] else "no username"
    return f"<b>{name}</b> ({un})\n🆔 <code>{u['user_id']}</code>"


async def send_withdrawal_to_admin(wid):
    conn = db()
    try:
        w = conn.execute("SELECT * FROM withdrawals WHERE id=?", (wid,)).fetchone()
        if not w: return
        u = conn.execute("SELECT * FROM users WHERE user_id=?", (w["user_id"],)).fetchone()
    finally:
        conn.close()
    if not w or not u: return
    refs = get_referral_count(u["user_id"])
    conn2 = db()
    try:
        refs_total = int(conn2.execute("SELECT COUNT(*) c FROM users WHERE referred_by=?", (u["user_id"],)).fetchone()["c"])
    finally: conn2.close()
    risk = "🟢 Normal" if (u["risk_score"] or 0) < 30 else ("🟡 Review" if (u["risk_score"] or 0) < 60 else "🔴 High")
    text = (
        f"💸 <b>NEW WITHDRAWAL REQUEST</b>\n\n"
        f"{fmt_user(u)}\n\n"
        f"💰 Amount: <b>{w['amount']:.2f} ETB</b>\n"
        f"🏦 Method: <b>{html.escape(w['wallet_type'])}</b>\n"
        f"📱 Wallet: <code>{html.escape(w['wallet_number'])}</code>\n\n"
        f"<b>📊 Earnings Breakdown</b>\n"
        f"• Referral: {float(u['referral_earnings'] or 0):.2f} ETB\n"
        f"• Daily: {float(u['daily_earnings'] or 0):.2f} ETB\n"
        f"• Task: {float(u['task_earnings'] or 0):.2f} ETB\n"
        f"• Admin credits: {float(u['admin_credits'] or 0):.2f} ETB\n"
        f"• Total earned: <b>{float(u['total_earned'] or 0):.2f} ETB</b>\n"
        f"• Total withdrawn: {float(u['total_withdrawn'] or 0):.2f} ETB\n\n"
        f"<b>👥 Referrals</b>\n"
        f"• Total invited: {refs_total}\n"
        f"• Verified & paid: {refs}\n\n"
        f"<b>🛡 Risk</b>: {risk} ({u['risk_score'] or 0})\n"
        f"Flags: {html.escape(u['risk_flags'] or 'none')}"
    )
    await send_admin(text, wd_kb(wid))


async def send_task_to_admin(sid):
    conn = db()
    try:
        s = conn.execute("SELECT ts.*, t.title, t.reward FROM task_submissions ts JOIN tasks t ON t.id=ts.task_id WHERE ts.id=?",
                         (sid,)).fetchone()
        if not s: return
        u = conn.execute("SELECT * FROM users WHERE user_id=?", (s["user_id"],)).fetchone()
    finally:
        conn.close()
    if not s or not u: return
    text = (
        f"📋 <b>NEW TASK SUBMISSION</b>\n\n"
        f"{fmt_user(u)}\n\n"
        f"📌 Task: <b>{html.escape(s['title'])}</b>\n"
        f"💰 Reward: <b>{s['reward']:.2f} ETB</b>\n\n"
        f"🧾 <b>Proof:</b>\n{html.escape(s['proof_text'] or '(image)')}"
    )
    if s["proof_image"]:
        text += f"\n🖼 Image: <code>{html.escape(s['proof_image'])}</code>"
    await send_admin(text, sub_kb(sid))


async def send_user_audit(chat_id, target_id):
    u = get_user(target_id)
    if not u:
        await send(chat_id, "User not found."); return
    refs_paid = get_referral_count(target_id)
    conn = db()
    try:
        refs_total = conn.execute("SELECT COUNT(*) c FROM users WHERE referred_by=?", (target_id,)).fetchone()["c"]
        wds = conn.execute("SELECT id,amount,status,created_at FROM withdrawals WHERE user_id=? ORDER BY id DESC LIMIT 10", (target_id,)).fetchall()
        subs = conn.execute("SELECT id,status,created_at FROM task_submissions WHERE user_id=? ORDER BY id DESC LIMIT 10", (target_id,)).fetchall()
        txs = conn.execute("SELECT type,amount,created_at FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT 15", (target_id,)).fetchall()
    finally: conn.close()
    name = html.escape((u["first_name"] or "") + (" " + u["last_name"] if u["last_name"] else ""))
    lines = [
        f"👤 <b>User Audit</b>\n",
        f"Name: {name}",
        f"Username: @{html.escape(u['username'] or 'none')}",
        f"ID: <code>{u['user_id']}</code>",
        f"Balance: <b>{float(u['balance'] or 0):.2f} ETB</b>",
        f"Total earned: {float(u['total_earned'] or 0):.2f} ETB",
        f"Total withdrawn: {float(u['total_withdrawn'] or 0):.2f} ETB",
        f"Verified: {'✅' if u['verified'] else '❌'}",
        f"Banned: {'🚫' if u['banned'] else '✅'}",
        f"Wallet: {html.escape(u['wallet_type'] or 'none')} / <code>{html.escape(u['wallet_number'] or 'none')}</code>",
        f"Suspicious: {'⚠️' if u['wallet_suspicious'] else 'no'}",
        f"Risk: {u['risk_score'] or 0} — {html.escape(u['risk_flags'] or 'none')}",
        f"\n👥 Referrals: total {refs_total}, paid {refs_paid}",
    ]
    if wds:
        lines.append("\n💸 <b>Recent withdrawals</b>")
        for w in wds[:5]: lines.append(f"#{w['id']} {w['amount']:.2f} — {w['status']}")
    if subs:
        lines.append("\n📋 <b>Recent tasks</b>")
        for s in subs[:5]: lines.append(f"#{s['id']} — {s['status']}")
    if txs:
        lines.append("\n📊 <b>Recent transactions</b>")
        for t in txs[:8]: lines.append(f"{t['type']} {t['amount']:+.2f}")
    await send(chat_id, "\n".join(lines))


async def send_admin_dashboard(chat_id):
    conn = db()
    try:
        users = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        verified = conn.execute("SELECT COUNT(*) c FROM users WHERE verified=1").fetchone()["c"]
        banned = conn.execute("SELECT COUNT(*) c FROM users WHERE banned=1").fetchone()["c"]
        flagged = conn.execute("SELECT COUNT(*) c FROM users WHERE risk_score>=30").fetchone()["c"]
        total_bal = conn.execute("SELECT COALESCE(SUM(balance),0) s FROM users").fetchone()["s"]
        total_earned = conn.execute("SELECT COALESCE(SUM(total_earned),0) s FROM users").fetchone()["s"]
        total_wd = conn.execute("SELECT COALESCE(SUM(total_withdrawn),0) s FROM users").fetchone()["s"]
        pw = conn.execute("SELECT COUNT(*) c FROM withdrawals WHERE status='pending'").fetchone()["c"]
        pt = conn.execute("SELECT COUNT(*) c FROM task_submissions WHERE status='pending'").fetchone()["c"]
    finally: conn.close()
    await send(chat_id,
        f"🛡 <b>Falcon World Admin Dashboard</b>\n\n"
        f"👥 Users: <b>{users}</b>  (verified: {verified})\n"
        f"🚫 Banned: {banned}  🚨 Flagged: {flagged}\n"
        f"💼 Total balance: <b>{total_bal:.2f} ETB</b>\n"
        f"📈 Total earned: {total_earned:.2f} ETB\n"
        f"📉 Total withdrawn: {total_wd:.2f} ETB\n\n"
        f"💸 Pending withdrawals: <b>{pw}</b>\n"
        f"📋 Pending task proofs: <b>{pt}</b>\n\n"
        f"<b>Commands</b>\n"
        f"/checkuser ID\n/addbalance ID AMOUNT\n/ban ID [reason]  /unban ID\n"
        f"/setdaily /setref /setminwithdraw\n"
        f"/channels /addchannel /removechannel /togglechannel /editchannel\n"
        f"/addtask /deltask /tasks\n"
        f"/withdrawals  /stats  /maintenance")


async def edit_cb(query, text, kb=None):
    d = {"chat_id": query["message"]["chat"]["id"], "message_id": query["message"]["message_id"],
         "text": text, "parse_mode": "HTML"}
    if kb is not None: d["reply_markup"] = kb
    return await tg("editMessageText", d)


async def answer_cb(cid, text="", alert=False):
    return await tg("answerCallbackQuery", {"callback_query_id": cid, "text": text, "show_alert": alert})


async def handle_callback(query):
    data = query.get("data", "")
    admin_id = int(query["from"]["id"])
    if not is_admin(admin_id):
        await answer_cb(query["id"], "Not authorized.", True); return

    if data.startswith("wdrefs:"):
        _, wid_s, page_s = data.split(":", 2)
        wid = int(wid_s); page = int(page_s)
        conn = db()
        try:
            w = conn.execute("SELECT user_id FROM withdrawals WHERE id=?", (wid,)).fetchone()
            if not w: await answer_cb(query["id"], "Not found", True); return
            all_refs = conn.execute(
                "SELECT user_id, username, first_name, referral_paid FROM users WHERE referred_by=? ORDER BY user_id DESC",
                (w["user_id"],)).fetchall()
        finally: conn.close()
        per = 50
        start = page * per
        chunk = all_refs[start:start+per]
        total_pages = max(1, (len(all_refs) + per - 1)//per)
        if not chunk:
            await answer_cb(query["id"], "No referrals."); return
        lines = [f"👥 <b>Referrals — page {page+1}/{total_pages}</b>  ({len(all_refs)} total)\n"]
        for r in chunk:
            nm = html.escape(r["first_name"] or "")
            un = f"@{html.escape(r['username'])}" if r["username"] else "—"
            pd = "💰" if r["referral_paid"] else "⏳"
            lines.append(f"{pd} {nm} {un}\n<code>{r['user_id']}</code>")
        kb = None
        if page + 1 < total_pages:
            kb = {"inline_keyboard": [[{"text": "➡️ Next", "callback_data": f"wdrefs:{wid}:{page+1}"}]]}
        await send(admin_id, "\n".join(lines), kb)
        await answer_cb(query["id"], f"Page {page+1}"); return

    if data.startswith("wdaudit:"):
        wid = int(data.split(":")[1])
        conn = db()
        try:
            w = conn.execute("SELECT user_id FROM withdrawals WHERE id=?", (wid,)).fetchone()
        finally: conn.close()
        if w: await send_user_audit(admin_id, int(w["user_id"]))
        await answer_cb(query["id"], "Sent audit"); return

    if data.startswith("wdok:") or data.startswith("wdno:") or data.startswith("wdban:"):
        action, wid_s = data.split(":", 1)
        wid = int(wid_s)
        if action == "wdok":
            ok, w = approve_withdrawal(wid, admin_id)
            if not ok: await answer_cb(query["id"], str(w), True); return
            log_admin(admin_id, "approve_withdrawal", wid)
            await answer_cb(query["id"], "✅ Approved")
            await edit_cb(query, f"✅ <b>Withdrawal #{wid}</b> — Approved")
            try:
                await send(int(w["user_id"]),
                    f"✅ <b>Withdrawal Approved</b>\n\nAmount: <b>{w['amount']:.2f} ETB</b>\n"
                    f"Method: {html.escape(w['wallet_type'])}\nWallet: <code>{html.escape(w['wallet_number'])}</code>")
            except: pass
        elif action == "wdno":
            ok, w = reject_withdrawal(wid, admin_id, "Rejected by admin")
            if not ok: await answer_cb(query["id"], str(w), True); return
            log_admin(admin_id, "reject_withdrawal", wid)
            await answer_cb(query["id"], "❌ Rejected")
            await edit_cb(query, f"❌ <b>Withdrawal #{wid}</b> — Rejected & refunded")
            try:
                await send(int(w["user_id"]),
                    f"❌ <b>Withdrawal Rejected</b>\n\nAmount refunded: <b>{w['amount']:.2f} ETB</b>")
            except: pass
        else:
            conn = db()
            try:
                w = conn.execute("SELECT user_id FROM withdrawals WHERE id=?", (wid,)).fetchone()
                if w:
                    conn.execute("UPDATE users SET banned=1, ban_reason='Withdrawal fraud', updated_at=? WHERE user_id=?",
                                 (int(time.time()), w["user_id"]))
                    conn.commit()
            finally: conn.close()
            log_admin(admin_id, "ban_from_wd", wid)
            await answer_cb(query["id"], "🚫 Banned")
            await edit_cb(query, f"🚫 <b>Withdrawal #{wid}</b> — User banned")
        return

    if data.startswith("tskok:") or data.startswith("tskno:"):
        action, sid_s = data.split(":", 1)
        sid = int(sid_s)
        if action == "tskok":
            ok, s = approve_task_submission(sid, admin_id)
            if not ok: await answer_cb(query["id"], str(s), True); return
            log_admin(admin_id, "approve_task", sid)
            await answer_cb(query["id"], "✅ Approved")
            await edit_cb(query, f"✅ <b>Task Submission #{sid}</b> — Approved")
            try:
                await send(int(s["user_id"]),
                    f"✅ <b>Task Approved</b>\n\n{html.escape(s['title'])}\n+{s['reward']:.2f} ETB credited.")
            except: pass
        else:
            reject_task_submission(sid, admin_id, "Rejected")
            log_admin(admin_id, "reject_task", sid)
            await answer_cb(query["id"], "❌ Rejected")
            await edit_cb(query, f"❌ <b>Task Submission #{sid}</b> — Rejected")
        return

    await answer_cb(query["id"])


app = FastAPI(title="Falcon World")
init_db()


def validate_init_data(init_data: str):
    if not init_data or not BOT_TOKEN: return None
    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))
        recv = parsed.pop("hash", None)
        if not recv: return None
        dcs = "\n".join(f"{k}={parsed[k]}" for k in sorted(parsed.keys()))
        sk = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calc = hmac.new(sk, dcs.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, recv): return None
        if int(parsed.get("auth_date", "0")) < time.time() - 86400: return None
        user = json.loads(parsed.get("user", "{}"))
        if not user.get("id"): return None
        return user
    except Exception:
        return None


async def require_user(request: Request, x_device_id: str = Header(default="", alias="X-Device-Id")):
    user = validate_init_data(request.headers.get("X-Telegram-Init-Data", ""))
    if not user: return None, None, JSONResponse({"error": "telegram_required"}, status_code=401)
    uid = int(user["id"])
    if is_banned(uid): return None, None, JSONResponse({"error": "banned"}, status_code=403)
    if is_maintenance() and not is_admin(uid):
        return None, None, JSONResponse({"error": "maintenance"}, status_code=503)
    ensure_user(uid, user.get("username", ""), user.get("first_name", ""), user.get("last_name", ""))
    ip_hash = ""
    try:
        forwarded = request.headers.get("x-forwarded-for", "")
        real_ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "")
        if real_ip: ip_hash = hashlib.sha256(real_ip.encode()).hexdigest()[:16]
    except: pass
    dev_hash = ""
    if x_device_id:
        dev_hash = hashlib.sha256(x_device_id.encode()).hexdigest()[:16]
        n = detect_device_sharing(dev_hash)
        if n >= 3: add_risk(uid, 30, "device_sharing", f"Device used by {n+1} accounts")
    if ip_hash:
        m = detect_ip_sharing(ip_hash)
        if m >= 5: add_risk(uid, 15, "ip_sharing", f"IP shared by {m+1} accounts in 24h")
    update_fingerprints(uid, dev_hash, ip_hash)
    return user, uid, None


@app.get("/", response_class=HTMLResponse)
@app.get("/app", response_class=HTMLResponse)
async def mini_app():
    return HTMLResponse(MINI_APP_HTML)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "falcon-world", "time": int(time.time())}


@app.post("/api/me")
async def api_me(request: Request, x_device_id: str = Header(default="", alias="X-Device-Id")):
    user, uid, err = await require_user(request, x_device_id)
    if err: return err
    u = get_user(uid)
    return {
        "user_id": uid,
        "username": u["username"] or "",
        "first_name": u["first_name"] or "",
        "last_name": u["last_name"] or "",
        "balance": _r2(u["balance"]),
        "total_earned": _r2(u["total_earned"]),
        "total_withdrawn": _r2(u["total_withdrawn"]),
        "referral_earnings": _r2(u["referral_earnings"]),
        "daily_earnings": _r2(u["daily_earnings"]),
        "task_earnings": _r2(u["task_earnings"]),
        "verified": bool(u["verified"]),
        "captcha_passed": bool(u["captcha_passed"]),
        "banned": bool(u["banned"]),
        "referral_count": get_referral_count(uid),
        "wallet_type": u["wallet_type"] or "",
        "wallet_number": u["wallet_number"] or "",
        "wallet_suspicious": bool(u["wallet_suspicious"]),
        "risk_score": u["risk_score"] or 0,
        "settings": {
            "daily_reward": get_setting("daily_reward", DEFAULT_DAILY, kind=float),
            "referral_reward": get_setting("referral_reward", DEFAULT_REFERRAL, kind=float),
            "minimum_withdrawal": get_setting("minimum_withdrawal", DEFAULT_MIN_WITHDRAW, kind=float),
            "bot_username": BOT_USERNAME,
            "support_username": SUPPORT_USERNAME,
        },
        "daily_status": daily_status(uid),
    }


@app.get("/api/channels")
async def api_channels(request: Request):
    user, uid, err = await require_user(request)
    if err: return err
    return {"channels": [{"id": c["id"], "username": c["username"], "name": c["name"], "url": c["url"]} for c in get_channels(active_only=True)]}


@app.post("/api/captcha")
async def api_captcha(request: Request):
    user, uid, err = await require_user(request)
    if err: return err
    token, q = make_captcha(uid)
    return {"token": token, "question": q}


@app.post("/api/captcha/verify")
async def api_captcha_verify(request: Request, payload: dict = Body(...)):
    user, uid, err = await require_user(request)
    if err: return err
    token = (payload.get("token") or "").strip()
    answer = str(payload.get("answer") or "").strip()
    ok, msg = verify_captcha(token, answer)
    if not ok:
        new_token, new_q = make_captcha(uid)
        return JSONResponse({"ok": False, "error": msg, "token": new_token, "question": new_q}, status_code=400)
    return {"ok": True}


@app.post("/api/verify")
async def api_verify(request: Request):
    user, uid, err = await require_user(request)
    if err: return err
    u = get_user(uid)
    if not u["captcha_passed"]:
        return JSONResponse({"ok": False, "error": "captcha_required"}, status_code=400)
    all_joined, results = await verify_all_channels(uid)
    if not all_joined:
        return {"ok": False, "verified": False, "channels": results}
    conn = db()
    try:
        was_verified = bool(u["verified"])
        conn.execute("UPDATE users SET verified=1, updated_at=? WHERE user_id=?", (int(time.time()), uid))
        conn.commit()
    finally: conn.close()
    if not was_verified:
        reward = pay_referral_if_eligible(uid)
        if reward:
            ref = get_user(uid)
            if ref and ref["referred_by"]:
                try:
                    await send(int(ref["referred_by"]),
                        f"👥 <b>Referral Reward</b>\n\n+{reward:.2f} ETB credited.\nA new user verified using your link!")
                except: pass
        if u["referred_by"]:
            n = check_referral_velocity(int(u["referred_by"]))
            if n >= 10:
                add_risk(int(u["referred_by"]), 25, "referral_velocity", f"{n} verified in 1h")
                try: await send_admin(f"🚨 <b>Referral velocity alert</b>\nUser <code>{u['referred_by']}</code> got {n} verified in 1 hour.")
                except: pass
    return {"ok": True, "verified": True, "channels": results}


@app.get("/api/tasks")
async def api_tasks(request: Request):
    user, uid, err = await require_user(request)
    if err: return err
    tasks = get_tasks(active_only=True)
    out = []
    for t in tasks:
        st = get_user_task_status(uid, t["id"])
        out.append({
            "id": t["id"], "title": t["title"], "description": t["description"] or "",
            "reward": _r2(t["reward"]), "url": t["url"] or "",
            "proof_type": t["proof_type"] or "text",
            "status": st["status"] if st else None,
        })
    return {"tasks": out}


@app.post("/api/tasks/{task_id}/submit")
async def api_submit_task(task_id: int, request: Request, payload: dict = Body(...)):
    user, uid, err = await require_user(request)
    if err: return err
    u = get_user(uid)
    if not u["verified"]:
        return JSONResponse({"ok": False, "error": "not_verified"}, status_code=400)
    proof_text = (payload.get("proof_text") or "").strip()
    proof_image = (payload.get("proof_image") or "").strip()
    ok, res = submit_task(uid, task_id, proof_text, proof_image)
    if not ok:
        return JSONResponse({"ok": False, "error": res}, status_code=400)
    try: await send_task_to_admin(res["submission_id"])
    except: pass
    return {"ok": True, "submission_id": res["submission_id"]}


@app.get("/api/referral")
async def api_referral(request: Request):
    user, uid, err = await require_user(request)
    if err: return err
    refs = get_all_referrals(uid)
    return {
        "link": f"https://t.me/{BOT_USERNAME}?start=ref_{uid}",
        "count": get_referral_count(uid),
        "total": len(refs),
        "reward": get_setting("referral_reward", DEFAULT_REFERRAL, kind=float),
        "referrals": [{
            "user_id": r["user_id"],
            "name": (r["first_name"] or "") + (" " + r["last_name"] if r["last_name"] else "") or (r["username"] or str(r["user_id"])),
            "username": r["username"] or "",
            "paid": bool(r["referral_paid"]),
        } for r in refs[:200]],
    }


@app.get("/api/wallet")
async def api_wallet_get(request: Request):
    user, uid, err = await require_user(request)
    if err: return err
    u = get_user(uid)
    return {"wallet_type": u["wallet_type"] or "", "wallet_number": u["wallet_number"] or "", "suspicious": bool(u["wallet_suspicious"])}


@app.post("/api/wallet")
async def api_wallet_post(request: Request, payload: dict = Body(...)):
    user, uid, err = await require_user(request)
    if err: return err
    ok, msg, susp = save_wallet(uid, payload.get("wallet_type", ""), payload.get("wallet_number", ""))
    if not ok:
        return JSONResponse({"ok": False, "error": msg}, status_code=400)
    return {"ok": True, "message": msg, "suspicious": susp}


@app.get("/api/daily-status")
async def api_daily_status(request: Request):
    user, uid, err = await require_user(request)
    if err: return err
    return daily_status(uid)


@app.post("/api/daily-bonus")
async def api_daily_bonus(request: Request):
    user, uid, err = await require_user(request)
    if err: return err
    ok, res = claim_daily(uid)
    if not ok:
        return JSONResponse({"ok": False, **res}, status_code=400)
    return {"ok": True, **res}


@app.post("/api/withdraw")
async def api_withdraw(request: Request, payload: dict = Body(...)):
    user, uid, err = await require_user(request)
    if err: return err
    u = get_user(uid)
    if not u["verified"]:
        return JSONResponse({"ok": False, "error": "not_verified"}, status_code=400)
    amount = float(payload.get("amount") or 0)
    ok, res = create_withdrawal(uid, amount)
    if not ok:
        return JSONResponse({"ok": False, "error": res}, status_code=400)
    try: await send_withdrawal_to_admin(res["withdrawal_id"])
    except: pass
    return {"ok": True, **res}


@app.get("/api/history")
async def api_history(request: Request):
    user, uid, err = await require_user(request)
    if err: return err
    conn = db()
    try:
        wds = conn.execute("SELECT id,amount,wallet_type,wallet_number,status,created_at,reviewed_at FROM withdrawals WHERE user_id=? ORDER BY id DESC LIMIT 50", (uid,)).fetchall()
        subs = conn.execute(
            "SELECT ts.id, ts.status, ts.created_at, t.title, t.reward FROM task_submissions ts JOIN tasks t ON t.id=ts.task_id WHERE ts.user_id=? ORDER BY ts.id DESC LIMIT 50",
            (uid,)).fetchall()
        txs = conn.execute("SELECT type,amount,description,created_at FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT 50", (uid,)).fetchall()
    finally: conn.close()
    return {"withdrawals": [dict(w) for w in wds], "submissions": [dict(s) for s in subs], "transactions": [dict(t) for t in txs]}


@app.post("/webhook")
async def webhook(request: Request):
    if WEBHOOK_SECRET:
        if request.headers.get("X-Telegram-Bot-Api-Secret-Token", "") != WEBHOOK_SECRET:
            return JSONResponse({"ok": False}, status_code=401)
    try: update = await request.json()
    except: return {"ok": True}
    asyncio.create_task(handle_update(update))
    return {"ok": True}


async def handle_update(update: dict):
    try:
        if "callback_query" in update:
            await handle_callback(update["callback_query"]); return
        if "message" in update:
            await handle_message(update["message"]); return
    except Exception as e:
        print("handle_update error:", e)


@app.on_event("startup")
async def on_startup():
    if BOT_TOKEN and WEBHOOK_URL:
        payload = {"url": WEBHOOK_URL, "allowed_updates": ["message", "callback_query"]}
        if WEBHOOK_SECRET: payload["secret_token"] = WEBHOOK_SECRET
        r = await tg("setWebhook", payload)
        print("setWebhook:", r)


# ═══════════════════════════════════════════════════════════════
# MINI APP UI
# ═══════════════════════════════════════════════════════════════
MINI_APP_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
<meta name="theme-color" content="#050b18">
<title>Falcon World</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root{--bg:#050b18;--panel:#0b1830;--panel2:#0e1e3c;--line:rgba(80,150,255,.16);--text:#f5f9ff;--muted:#8ba0be;--blue:#2ea8ff;--gold:#ffc63f;--green:#34e6a4;--red:#ff6178;--violet:#7c68ff;--r:20px;--rs:14px}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;background:var(--bg);color:var(--text);font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;overflow-x:hidden}
body{min-height:100vh;padding-bottom:90px}
a{color:var(--blue);text-decoration:none}
button{font-family:inherit;cursor:pointer;border:0;outline:0;color:inherit}
.hidden{display:none!important}
.header{position:sticky;top:0;z-index:20;padding:14px 18px;display:flex;align-items:center;gap:12px;background:linear-gradient(180deg,rgba(5,11,24,.96),rgba(5,11,24,.82));backdrop-filter:blur(14px);border-bottom:1px solid var(--line)}
.logo{width:40px;height:40px;border-radius:12px;background:linear-gradient(135deg,#0f6fff,#2ea8ff 60%,#7c68ff);display:grid;place-items:center;font-size:22px;box-shadow:0 8px 24px -8px rgba(46,168,255,.6)}
.brand{font-weight:800;letter-spacing:.3px;font-size:16px;line-height:1.1}
.brand small{display:block;color:var(--muted);font-weight:500;font-size:11px;letter-spacing:.5px}
.balance-chip{margin-left:auto;padding:8px 12px;border-radius:999px;background:linear-gradient(135deg,rgba(46,168,255,.16),rgba(124,104,255,.16));border:1px solid var(--line);font-weight:700;font-size:13px;display:flex;align-items:center;gap:6px;white-space:nowrap}
.balance-chip .amt{color:var(--gold)}
.wrap{padding:16px 16px 8px;max-width:640px;margin:0 auto}
.screen{display:none;animation:fade .25s ease}
.screen.active{display:block}
@keyframes fade{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.card{background:linear-gradient(180deg,var(--panel),var(--panel2));border:1px solid var(--line);border-radius:var(--r);padding:16px;margin-bottom:14px;position:relative;overflow:hidden}
.hero{background:radial-gradient(120% 90% at 100% 0%,rgba(46,168,255,.22),transparent 55%),radial-gradient(90% 80% at 0% 100%,rgba(124,104,255,.22),transparent 55%),linear-gradient(180deg,#0b1830,#0a1428);border:1px solid rgba(80,150,255,.22)}
.hero .label{color:var(--muted);font-size:12px;letter-spacing:.6px;text-transform:uppercase;font-weight:600}
.hero .amount{font-size:38px;font-weight:800;letter-spacing:-1px;margin:6px 0 2px;line-height:1}
.hero .amount .cur{font-size:18px;color:var(--muted);font-weight:600;margin-left:6px}
.hero .sub{color:var(--muted);font-size:12px;margin-top:6px}
.stats{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-top:14px}
.stat{background:rgba(0,0,0,.22);border:1px solid var(--line);border-radius:14px;padding:10px;text-align:center}
.stat .v{font-weight:800;font-size:14px}
.stat .k{color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.4px;margin-top:3px;font-weight:600}
.sect{font-size:12px;color:var(--muted);font-weight:700;letter-spacing:1.4px;text-transform:uppercase;margin:20px 4px 10px}
.actions{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.action{background:linear-gradient(180deg,var(--panel),var(--panel2));border:1px solid var(--line);border-radius:var(--r);padding:14px;display:flex;align-items:center;gap:12px;text-align:left;width:100%;transition:transform .12s ease,border-color .12s ease}
.action:active{transform:scale(.98);border-color:rgba(46,168,255,.5)}
.action .ico{width:40px;height:40px;border-radius:12px;flex:0 0 40px;display:grid;place-items:center;font-size:20px;background:linear-gradient(135deg,rgba(46,168,255,.22),rgba(124,104,255,.22));border:1px solid var(--line)}
.action .ico.gold{background:linear-gradient(135deg,rgba(255,198,63,.22),rgba(255,140,0,.18));border-color:rgba(255,198,63,.32)}
.action .ico.green{background:linear-gradient(135deg,rgba(52,230,164,.2),rgba(0,180,110,.16));border-color:rgba(52,230,164,.3)}
.action .ico.violet{background:linear-gradient(135deg,rgba(124,104,255,.22),rgba(80,60,220,.18));border-color:rgba(124,104,255,.32)}
.action .ico.red{background:linear-gradient(135deg,rgba(255,97,120,.2),rgba(220,40,80,.16));border-color:rgba(255,97,120,.3)}
.action .t{font-weight:700;font-size:14px;line-height:1.15}
.action .s{color:var(--muted);font-size:11px;margin-top:3px}
.row{display:flex;align-items:center;gap:12px;padding:14px;background:linear-gradient(180deg,var(--panel),var(--panel2));border:1px solid var(--line);border-radius:var(--rs);margin-bottom:8px}
.row .ico{width:38px;height:38px;border-radius:11px;flex:0 0 38px;display:grid;place-items:center;background:linear-gradient(135deg,rgba(46,168,255,.18),rgba(124,104,255,.18));border:1px solid var(--line);font-size:18px}
.row .body{flex:1;min-width:0}
.row .title{font-weight:700;font-size:14px}
.row .desc{color:var(--muted);font-size:12px;margin-top:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.row .right{font-weight:800;color:var(--gold);font-size:14px;text-align:right}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;padding:14px 18px;border-radius:14px;font-weight:700;font-size:14px;width:100%;background:linear-gradient(135deg,#2ea8ff,#0f6fff);color:#fff;box-shadow:0 8px 24px -10px rgba(46,168,255,.7);transition:transform .12s ease,opacity .12s ease}
.btn:active{transform:scale(.98)}
.btn.ghost{background:rgba(46,168,255,.12);color:var(--blue);border:1px solid rgba(46,168,255,.3);box-shadow:none}
.btn.gold{background:linear-gradient(135deg,#ffc63f,#ff9500);color:#1a1200;box-shadow:0 8px 24px -10px rgba(255,198,63,.7)}
.btn.dark{background:rgba(255,255,255,.05);border:1px solid var(--line);color:var(--text);box-shadow:none}
.btn:disabled{opacity:.45;pointer-events:none}
.btn-row{display:flex;gap:8px;margin-top:12px}
.btn-row .btn{flex:1}
.label{display:block;font-size:12px;color:var(--muted);font-weight:600;margin:12px 0 6px;letter-spacing:.3px}
.input,textarea.input{width:100%;padding:14px;border-radius:14px;background:rgba(0,0,0,.32);border:1px solid var(--line);color:var(--text);font-size:15px;outline:none;transition:border-color .15s}
.input:focus{border-color:var(--blue)}
.chips{display:flex;gap:8px;flex-wrap:wrap;margin-top:6px}
.chip{padding:10px 14px;border-radius:999px;font-size:13px;font-weight:600;background:rgba(255,255,255,.05);border:1px solid var(--line);color:var(--muted)}
.chip.active{background:linear-gradient(135deg,rgba(46,168,255,.3),rgba(124,104,255,.24));color:#fff;border-color:rgba(46,168,255,.5)}
.badge{display:inline-flex;padding:4px 8px;border-radius:999px;font-size:10px;font-weight:800;letter-spacing:.5px;text-transform:uppercase}
.badge.pending{background:rgba(255,198,63,.16);color:var(--gold);border:1px solid rgba(255,198,63,.32)}
.badge.approved{background:rgba(52,230,164,.16);color:var(--green);border:1px solid rgba(52,230,164,.32)}
.badge.rejected{background:rgba(255,97,120,.16);color:var(--red);border:1px solid rgba(255,97,120,.32)}
.nav{position:fixed;left:0;right:0;bottom:0;z-index:30;display:grid;grid-template-columns:repeat(4,1fr);padding:8px 8px calc(8px + env(safe-area-inset-bottom));background:linear-gradient(180deg,rgba(5,11,24,.86),rgba(5,11,24,.98));backdrop-filter:blur(18px);border-top:1px solid var(--line)}
.nav button{background:none;display:flex;flex-direction:column;align-items:center;gap:3px;padding:8px 4px;color:var(--muted);font-size:10px;font-weight:700;letter-spacing:.3px}
.nav button .ni{font-size:20px;line-height:1}
.nav button.active{color:var(--blue)}
.modal-bg{position:fixed;inset:0;z-index:40;background:rgba(3,8,18,.72);backdrop-filter:blur(6px);display:flex;align-items:flex-end;justify-content:center}
.modal{width:100%;max-width:640px;max-height:88vh;overflow-y:auto;background:linear-gradient(180deg,#0d1c38,#0a1528);border-radius:24px 24px 0 0;border:1px solid var(--line);border-bottom:0;padding:20px 18px calc(24px + env(safe-area-inset-bottom));animation:slideUp .28s cubic-bezier(.2,.8,.2,1)}
@keyframes slideUp{from{transform:translateY(30px);opacity:.5}to{transform:none;opacity:1}}
.modal h3{margin:0 0 4px;font-size:19px;letter-spacing:-.3px}
.modal .muted{color:var(--muted);font-size:13px;margin-bottom:14px}
.mh{display:flex;align-items:center;gap:10px;margin-bottom:14px}
.mh .close{margin-left:auto;background:rgba(255,255,255,.06);border:1px solid var(--line);border-radius:10px;width:34px;height:34px;display:grid;place-items:center;font-size:16px}
.toast{position:fixed;left:50%;bottom:110px;transform:translateX(-50%);padding:12px 18px;border-radius:14px;background:rgba(20,35,65,.96);border:1px solid var(--line);font-size:13px;font-weight:600;z-index:80;box-shadow:0 12px 40px -12px rgba(0,0,0,.7);animation:toastIn .25s ease}
@keyframes toastIn{from{transform:translate(-50%,14px);opacity:0}to{transform:translate(-50%,0);opacity:1}}
.center{display:grid;place-items:center;min-height:60vh;text-align:center;padding:20px}
.spinner{width:44px;height:44px;border-radius:50%;border:3px solid rgba(46,168,255,.18);border-top-color:var(--blue);animation:spin 1s linear infinite;margin:0 auto 14px}
@keyframes spin{to{transform:rotate(360deg)}}
.captcha-box{background:rgba(0,0,0,.3);border:1px solid var(--line);border-radius:18px;padding:20px;text-align:center;margin-bottom:14px}
.captcha-box .q{font-size:26px;font-weight:800;letter-spacing:1px;margin:8px 0}
</style>
</head>
<body>

<div id="loading" class="center">
  <div><div class="spinner"></div><div style="color:var(--muted);font-size:13px">Loading Falcon World…</div></div>
</div>

<div id="app" class="hidden">
  <header class="header">
    <div class="logo">🦅</div>
    <div class="brand">Falcon World<small>Earn • Complete • Grow</small></div>
    <div class="balance-chip">💼 <span class="amt" id="chipBalance">0.00</span> ETB</div>
  </header>

  <main class="wrap">
    <section id="screen-verify" class="screen">
      <div class="card hero" style="text-align:center;padding:24px 18px">
        <div style="font-size:48px;line-height:1;margin-bottom:8px">🦅</div>
        <h2 style="margin:0 0 6px;font-size:20px">Welcome to Falcon World</h2>
        <div style="color:var(--muted);font-size:13px">Complete verification to continue.</div>
      </div>
      <div id="captchaSection">
        <div class="sect">Step 1 · Human Verification</div>
        <div class="captcha-box">
          <div style="color:var(--muted);font-size:12px">Solve this to prove you are human</div>
          <div class="q" id="captchaQ">—</div>
          <input class="input" id="captchaA" type="number" inputmode="numeric" placeholder="Your answer" style="text-align:center;font-size:18px;font-weight:700">
          <button class="btn" id="captchaBtn" style="margin-top:12px">✅ Verify</button>
        </div>
      </div>
      <div id="channelsSection" class="hidden">
        <div class="sect">Step 2 · Required Channels</div>
        <div id="channelsList"></div>
        <button class="btn" id="verifyBtn" style="margin-top:10px">🔄 Verify Membership</button>
      </div>
    </section>

    <section id="screen-overview" class="screen">
      <div class="card hero">
        <div class="label">Available Balance</div>
        <div class="amount"><span id="ovBalance">0.00</span><span class="cur">ETB</span></div>
        <div class="sub" id="ovGreeting">Hello 👋</div>
        <div class="stats">
          <div class="stat"><div class="v" id="ovTotal">0.00</div><div class="k">Earned</div></div>
          <div class="stat"><div class="v" id="ovRefs">0</div><div class="k">Invites</div></div>
          <div class="stat"><div class="v" id="ovOut">0.00</div><div class="k">Withdrawn</div></div>
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
      <div class="sect">Daily Reward</div>
      <div class="card hero" style="text-align:center">
        <div style="font-size:40px;line-height:1">🎁</div>
        <div style="font-size:26px;font-weight:800;color:var(--gold);margin-top:4px" id="dailyAmount">+0.50 ETB</div>
        <div style="color:var(--muted);font-size:12px;margin:4px 0 14px">Claim once every 24 hours</div>
        <button class="btn gold" id="dailyBtn">Claim Daily Bonus</button>
      </div>
      <div class="sect">Tasks</div>
      <div id="tasksList"><div style="color:var(--muted);font-size:13px;text-align:center;padding:20px">No active tasks.</div></div>
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
          <div class="logo" style="width:52px;height:52px;font-size:26px">🦅</div>
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
let deviceId = localStorage.getItem('fid');
if (!deviceId) { deviceId = 'd_' + Math.random().toString(36).slice(2) + Date.now(); localStorage.setItem('fid', deviceId); }
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
let STATE = { me:null, tasks:[], captchaToken:null };

async function api(path, opts={}){
  const r = await fetch(path, {
    method: opts.method || 'GET',
    headers: { 'Content-Type':'application/json', 'X-Telegram-Init-Data': initData, 'X-Device-Id': deviceId },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  let data = {};
  try { data = await r.json(); } catch(e){}
  return { ok: r.ok, status: r.status, data };
}
function toast(msg, ms=2200){
  const t = document.createElement('div'); t.className='toast'; t.textContent=msg;
  document.body.appendChild(t); setTimeout(()=>t.remove(), ms);
}
function fmt(n){ return (Number(n)||0).toFixed(2); }
function esc(s){ return String(s ?? '').replace(/[&<>"']/g, c=>({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c])); }

function showScreen(name){
  $$('.screen').forEach(s => s.classList.remove('active'));
  const el = $('#screen-'+name); if (el) el.classList.add('active');
  $$('.nav button').forEach(b => b.classList.toggle('active', b.dataset.nav === name));
  if (name === 'activity') loadActivity();
}
document.addEventListener('click', e => {
  const b = e.target.closest('[data-nav]');
  if (b) showScreen(b.dataset.nav);
});

function updateHeader(){ if (STATE.me) $('#chipBalance').textContent = fmt(STATE.me.balance); }

function renderApp(){
  const m = STATE.me;
  $('#ovBalance').textContent = fmt(m.balance);
  $('#ovGreeting').textContent = 'Hello, ' + (m.first_name || m.username || 'Falcon') + ' 👋';
  $('#ovTotal').textContent = fmt(m.total_earned);
  $('#ovRefs').textContent = m.referral_count || 0;
  $('#ovOut').textContent = fmt(m.total_withdrawn);
  $('#dailyAmount').textContent = '+' + fmt(m.settings.daily_reward) + ' ETB';
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
  updateHeader();
}

async function loadMe(){
  const r = await api('/api/me', { method:'POST' });
  if (!r.ok) {
    if (r.status === 401) { $('#loading').innerHTML = '<div class="center"><div>Open from Telegram.</div></div>'; return false; }
    if (r.status === 403) { $('#loading').innerHTML = '<div class="center"><div style="color:var(--red)">🚫 Account restricted.</div></div>'; return false; }
    if (r.status === 503) { $('#loading').innerHTML = '<div class="center"><div>🛠 Maintenance mode. Try later.</div></div>'; return false; }
    toast('Failed to load'); return false;
  }
  STATE.me = r.data; return true;
}

async function startCaptcha(){
  const r = await api('/api/captcha', { method:'POST' });
  if (r.ok) { STATE.captchaToken = r.data.token; $('#captchaQ').textContent = r.data.question; }
}

async function loadChannels(){
  const r = await api('/api/channels');
  if (!r.ok) return;
  const box = $('#channelsList');
  box.innerHTML = (r.data.channels||[]).map(c => `
    <a class="row" href="${esc(c.url)}" target="_blank" rel="noopener">
      <div class="ico">📢</div>
      <div class="body"><div class="title">${esc(c.name)}</div><div class="desc">${esc(c.username)}</div></div>
      <div class="right" style="color:var(--blue);font-size:12px">Join →</div>
    </a>`).join('');
}

async function loadTasks(){
  const r = await api('/api/tasks');
  if (r.ok) STATE.tasks = r.data.tasks || [];
  renderTasks();
}
function renderTasks(){
  const box = $('#tasksList');
  if (!STATE.tasks.length) { box.innerHTML = '<div style="color:var(--muted);font-size:13px;text-align:center;padding:20px">No active tasks.</div>'; return; }
  box.innerHTML = STATE.tasks.map(t => {
    const st = t.status ? `<span class="badge ${t.status}">${t.status}</span>` : '';
    const disabled = (t.status === 'pending' || t.status === 'approved') ? 'disabled' : '';
    return `<div class="row" style="flex-direction:column;align-items:stretch;gap:10px">
      <div style="display:flex;gap:12px;align-items:center">
        <div class="ico">📋</div>
        <div class="body"><div class="title">${esc(t.title)}</div><div class="desc">${esc(t.description)}</div></div>
        <div class="right">+${fmt(t.reward)} ETB</div>
      </div>
      ${st ? `<div>${st}</div>` : ''}
      <div class="btn-row">
        ${t.url ? `<a class="btn dark" href="${esc(t.url)}" target="_blank" style="text-decoration:none">Open</a>` : ''}
        <button class="btn" data-task="${t.id}" ${disabled}>Submit</button>
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
  const wrap = document.createElement('div'); wrap.className='modal-bg';
  wrap.innerHTML = `<div class="modal">${html}</div>`;
  wrap.addEventListener('click', e => { if (e.target === wrap) closeModal(); });
  document.body.appendChild(wrap);
  wrap.querySelectorAll('[data-close]').forEach(b => b.addEventListener('click', closeModal));
}

function openSubmit(taskId){
  const t = STATE.tasks.find(x => x.id === taskId); if (!t) return;
  openModal(`<div class="mh"><h3>Submit Proof</h3><button class="close" data-close>✕</button></div>
    <div class="muted">${esc(t.title)} • +${fmt(t.reward)} ETB</div>
    <label class="label">Proof (text or link)</label>
    <textarea class="input" id="proofInput" rows="5" placeholder="Paste your proof…"></textarea>
    <div class="btn-row"><button class="btn dark" data-close>Cancel</button><button class="btn" id="submitProofBtn">Submit</button></div>`);
  $('#submitProofBtn').addEventListener('click', async () => {
    const proof = ($('#proofInput').value || '').trim();
    if (!proof) { toast('Proof required'); return; }
    const r = await api(`/api/tasks/${taskId}/submit`, { method:'POST', body:{ proof_text: proof } });
    if (r.ok) { toast('✅ Submitted for review'); closeModal(); loadTasks(); }
    else { toast(r.data.error || 'Failed'); }
  });
}

function openInvite(){
  const m = STATE.me;
  openModal(`<div class="mh"><h3>Invite Friends</h3><button class="close" data-close>✕</button></div>
    <div class="muted">Earn <b style="color:var(--gold)">${fmt(m.settings.referral_reward)} ETB</b> per verified referral.</div>
    <div class="card hero" style="text-align:center;margin-top:8px">
      <div class="label">Your Referral Link</div>
      <div style="word-break:break-all;font-size:13px;margin:8px 0;color:var(--blue)" id="refLink">https://t.me/${esc(m.settings.bot_username)}?start=ref_${m.user_id}</div>
      <button class="btn" id="copyRef">📋 Copy Link</button>
    </div>
    <div class="card">
      <div style="display:flex;justify-content:space-between"><span style="color:var(--muted)">Verified referrals</span><b>${m.referral_count}</b></div>
      <div style="display:flex;justify-content:space-between;margin-top:6px"><span style="color:var(--muted)">Referral earnings</span><b style="color:var(--gold)">${fmt(m.referral_earnings)} ETB</b></div>
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
    if (r.ok) { toast('✅ Wallet saved'); closeModal(); await refresh(); }
    else toast(r.data.error || 'Invalid');
  });
}

function openWithdraw(){
  const m = STATE.me;
  if (!m.wallet_type || !m.wallet_number) { toast('Save wallet first'); openWallet(); return; }
  openModal(`<div class="mh"><h3>Request Payout</h3><button class="close" data-close>✕</button></div>
    <div class="muted">Available: <b style="color:var(--gold)">${fmt(m.balance)} ETB</b> · Min: ${fmt(m.settings.minimum_withdrawal)} ETB</div>
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
    else toast(r.data.error || 'Failed');
  });
}

function openServices(){
  const items = [
    ['📢','Channel Growth','Grow your channels'],
    ['👥','Group Growth','Build community'],
    ['📣','Advertising & Promotion','Promote your brand'],
    ['💱','USDT Buy / Sell','Exchange USDT'],
    ['📺','Channel Buy / Sell','Marketplace'],
    ['📱','Social Promotion','Boost socials'],
  ];
  openModal(`<div class="mh"><h3>Services & Support</h3><button class="close" data-close>✕</button></div>
    <div class="muted">Contact <b>@AmanM_12</b> for any service.</div>
    ${items.map(([i,t,d]) => `<a class="row" href="https://t.me/AmanM_12" target="_blank" style="text-decoration:none;color:inherit;margin-bottom:8px">
      <div class="ico">${i}</div><div class="body"><div class="title">${t}</div><div class="desc">${d}</div></div></a>`).join('')}`);
}

async function refresh(){
  if (!(await loadMe())) return;
  renderApp();
  if (!STATE.me.captcha_passed) { await startCaptcha(); showScreen('verify'); return; }
  if (!STATE.me.verified) { await loadChannels(); showScreen('verify'); return; }
  await loadTasks();
  showScreen('overview');
}

async function verifyCaptcha(){
  const ans = ($('#captchaA').value || '').trim();
  if (!ans) { toast('Enter answer'); return; }
  const btn = $('#captchaBtn'); btn.disabled = true; btn.textContent = 'Checking…';
  const r = await api('/api/captcha/verify', { method:'POST', body:{ token: STATE.captchaToken, answer: ans } });
  if (r.ok) {
    toast('✅ Verified');
    await loadMe(); renderApp();
    $('#captchaSection').classList.add('hidden');
    $('#channelsSection').classList.remove('hidden');
    await loadChannels();
  } else {
    STATE.captchaToken = r.data.token; $('#captchaQ').textContent = r.data.question;
    $('#captchaA').value = ''; toast('❌ Wrong. Try again');
  }
  btn.disabled = false; btn.textContent = '✅ Verify';
}

async function verifyChannels(){
  const btn = $('#verifyBtn'); btn.disabled = true; btn.textContent = 'Checking…';
  const r = await api('/api/verify', { method:'POST' });
  if (r.ok && r.data.verified) { toast('✅ Verification complete'); await refresh(); }
  else {
    const missing = (r.data.channels || []).filter(c => !c.joined).length;
    toast(`⚠️ ${missing} channel(s) still needed`);
  }
  btn.disabled = false; btn.textContent = '🔄 Verify Membership';
}

$('#captchaBtn')?.addEventListener('click', verifyCaptcha);
$('#verifyBtn')?.addEventListener('click', verifyChannels);
$('#dailyBtn')?.addEventListener('click', async () => {
  const r = await api('/api/daily-bonus', { method:'POST' });
  if (r.ok) { toast('🎁 +' + fmt(r.data.reward) + ' ETB'); await refresh(); }
  else toast(r.data.error === 'cooldown' ? 'Already claimed — wait 24h' : (r.data.error || 'Failed'));
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
    $('#loading').classList.add('hidden');
    $('#app').classList.remove('hidden');
    renderApp();
    if (!STATE.me.captcha_passed) { await startCaptcha(); showScreen('verify'); }
    else if (!STATE.me.verified) { $('#captchaSection').classList.add('hidden'); $('#channelsSection').classList.remove('hidden'); await loadChannels(); showScreen('verify'); }
    else { await loadTasks(); showScreen('overview'); }
  } catch(e) {
    console.error(e);
    $('#loading').innerHTML = '<div class="center"><div>Failed to load. Refresh.</div></div>';
  }
})();
</script>
</body>
</html>
"""
