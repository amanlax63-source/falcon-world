# Falcon World — single-file Telegram Bot + FastAPI Mini App
# Render Start Command:
# uvicorn server:app --host 0.0.0.0 --port $PORT

import json
import hmac
import hashlib
import time
import asyncio
import os
import re
import sqlite3
import html
from urllib.parse import parse_qsl
from typing import Optional

from fastapi import FastAPI, Request, Body
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
import httpx

# ─────────────────────────── CONFIG ───────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", os.getenv("ADMIN_ID", "")).strip()
ADMIN_IDS = {int(x.strip()) for x in ADMIN_IDS_RAW.split(",") if x.strip().isdigit()}

BOT_USERNAME = os.getenv("BOT_USERNAME", "FalconWorld_Bot").strip().lstrip("@")
MINI_APP_URL = os.getenv("MINI_APP_URL", "https://falcon-world.onrender.com/app").strip()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FALCON_BG_PATH = os.path.join(BASE_DIR, "falcon-bg.webp")
DB_PATH = os.getenv("DB_PATH", "falcon_world.db").strip() or "falcon_world.db"
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://falcon-world.onrender.com/webhook").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()

DEFAULT_DAILY_BONUS = 0.50
DEFAULT_REFERRAL_REWARD = 2.00
DEFAULT_MIN_WITHDRAW = 30.00

REQUIRED_CHANNELS = [
    {"username": "@Sheger_tech1", "name": "Sheger Tech", "url": "https://t.me/Sheger_tech1"},
    {"username": "@EthioVortex1", "name": "Ethio Vortex", "url": "https://t.me/EthioVortex1"},
    {"username": "@ethiocashflow", "name": "Ethio Cash Flow", "url": "https://t.me/ethiocashflow"},
    {"username": "@AmanIncomeLab", "name": "Aman Income Lab", "url": "https://t.me/AmanIncomeLab"},
    {"username": "@OnlineIncomeHub07", "name": "Online Income Hub", "url": "https://t.me/OnlineIncomeHub07"},
    {"username": "@Paymentprooff2", "name": "Payment Proof", "url": "https://t.me/Paymentprooff2"},
]

SUPPORT_USERNAME = "@AmanM_12"
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""

# ─────────────────────────── DATABASE ───────────────────────────
def db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = db()
    try:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            balance REAL NOT NULL DEFAULT 0,
            referral_earnings REAL NOT NULL DEFAULT 0,
            daily_bonus_earnings REAL NOT NULL DEFAULT 0,
            task_earnings REAL NOT NULL DEFAULT 0,
            withdrawn_total REAL NOT NULL DEFAULT 0,
            verified INTEGER NOT NULL DEFAULT 0,
            banned INTEGER NOT NULL DEFAULT 0,
            referred_by INTEGER,
            referral_reward_paid INTEGER NOT NULL DEFAULT 0,
            daily_last_claim INTEGER NOT NULL DEFAULT 0,
            wallet_type TEXT,
            wallet_number TEXT,
            wallet_suspicious INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            wallet_type TEXT NOT NULL,
            wallet_number TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            suspicious INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL,
            processed_at INTEGER,
            processed_by INTEGER
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            reward REAL NOT NULL DEFAULT 0,
            url TEXT NOT NULL DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1,
            created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS task_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            proof TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at INTEGER NOT NULL,
            reviewed_at INTEGER,
            reviewed_by INTEGER
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS required_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            created_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_withdrawals_status ON withdrawals(status);
        CREATE INDEX IF NOT EXISTS idx_withdrawals_user ON withdrawals(user_id);
        CREATE INDEX IF NOT EXISTS idx_submissions_status ON task_submissions(status);
        CREATE INDEX IF NOT EXISTS idx_submissions_user ON task_submissions(user_id);
        """)
        existing = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
        for col, definition in {
            "referral_earnings": "REAL NOT NULL DEFAULT 0",
            "daily_bonus_earnings": "REAL NOT NULL DEFAULT 0",
            "task_earnings": "REAL NOT NULL DEFAULT 0",
            "withdrawn_total": "REAL NOT NULL DEFAULT 0",
        }.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE users ADD COLUMN {col} {definition}")

        if conn.execute("SELECT COUNT(*) c FROM required_channels").fetchone()["c"] == 0:
            now_seed = int(time.time())
            conn.executemany(
                "INSERT OR IGNORE INTO required_channels(username,name,url,active,created_at) VALUES(?,?,?,?,?)",
                [(c["username"], c["name"], c["url"], 1, now_seed) for c in REQUIRED_CHANNELS],
            )

        for key, value in {
            "daily_bonus": DEFAULT_DAILY_BONUS,
            "referral_reward": DEFAULT_REFERRAL_REWARD,
            "min_withdraw": DEFAULT_MIN_WITHDRAW,
        }.items():
            conn.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (key, str(value)))
        conn.commit()
    finally:
        conn.close()


def get_setting(key: str, default=None):
    conn = db()
    try:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        if not row:
            return default
        v = row["value"]
        if isinstance(default, int):
            return int(float(v))
        if isinstance(default, float):
            return float(v)
        return v
    finally:
        conn.close()


def set_setting(key: str, value):
    conn = db()
    try:
        conn.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
        conn.commit()
    finally:
        conn.close()

# ─────────────────────────── BOT HELPERS ───────────────────────────
async def telegram_request(method: str, data: Optional[dict] = None):
    if not BOT_TOKEN:
        return {"ok": False, "description": "BOT_TOKEN is missing"}
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            r = await client.post(f"{TELEGRAM_API}/{method}", json=data or {})
            try:
                return r.json()
            except Exception:
                return {"ok": False, "description": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"ok": False, "description": str(e)}


async def send_message(chat_id: int, text: str, reply_markup=None):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return await telegram_request("sendMessage", payload)


async def send_admin_message(text: str, keyboard=None):
    results = []
    for admin_id in ADMIN_IDS:
        results.append(await send_message(admin_id, text, keyboard))
    return results


def is_admin(user_id: int) -> bool:
    return int(user_id) in ADMIN_IDS

# ─────────────────────────── USER LOGIC ───────────────────────────
def ensure_user(user_id: int, username="", first_name="", referred_by=None):
    now = int(time.time())
    conn = db()
    try:
        row = conn.execute("SELECT user_id, referred_by FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            conn.execute(
                """INSERT INTO users
                (user_id,username,first_name,balance,verified,banned,referred_by,
                 referral_reward_paid,daily_last_claim,wallet_suspicious,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (user_id, username or "", first_name or "", 0, 0, 0, referred_by, 0, 0, 0, now, now),
            )
        else:
            conn.execute(
                "UPDATE users SET username=?, first_name=?, updated_at=? WHERE user_id=?",
                (username or "", first_name or "", now, user_id),
            )
            if referred_by and not row["referred_by"] and referred_by != user_id:
                conn.execute("UPDATE users SET referred_by=? WHERE user_id=?", (referred_by, user_id))
        conn.commit()
    finally:
        conn.close()


def get_user(user_id: int):
    conn = db()
    try:
        return conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    finally:
        conn.close()


def is_banned(user_id: int) -> bool:
    row = get_user(user_id)
    return bool(row and row["banned"])


def add_balance(user_id: int, amount: float):
    conn = db()
    try:
        conn.execute(
            "UPDATE users SET balance=ROUND(balance+?,8), updated_at=? WHERE user_id=?",
            (float(amount), int(time.time()), user_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_referral_count(user_id: int) -> int:
    conn = db()
    try:
        return int(conn.execute(
            "SELECT COUNT(*) c FROM users WHERE referred_by=? AND referral_reward_paid=1",
            (user_id,),
        ).fetchone()["c"])
    finally:
        conn.close()


def _local_date(ts: Optional[int] = None):
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Africa/Addis_Ababa")
        return datetime.fromtimestamp(ts or time.time(), tz).date()
    except Exception:
        return datetime.utcfromtimestamp(ts or time.time()).date()


def claim_daily_bonus(user_id: int):
    now = int(time.time())
    today = _local_date(now)
    reward = float(get_setting("daily_bonus", DEFAULT_DAILY_BONUS))
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT banned,verified,daily_last_claim,balance FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()
        if not row:
            conn.rollback(); return False, {"error": "user_not_found"}
        if row["banned"]:
            conn.rollback(); return False, {"error": "banned"}
        if not row["verified"]:
            conn.rollback(); return False, {"error": "not_verified"}
        last = int(row["daily_last_claim"] or 0)
        if last and _local_date(last) == today:
            conn.rollback(); return False, {"error": "already_claimed", "date": str(today)}
        conn.execute(
            """UPDATE users SET balance=ROUND(balance+?,8),
               daily_bonus_earnings=ROUND(daily_bonus_earnings+?,8),
               daily_last_claim=?,updated_at=? WHERE user_id=?""",
            (reward, reward, now, now, user_id),
        )
        conn.commit()
        from datetime import timedelta
        return True, {
            "reward": reward,
            "balance": float(row["balance"]) + reward,
            "date": str(today),
            "next_date": str(today + timedelta(days=1)),
        }
    except Exception:
        conn.rollback(); raise
    finally:
        conn.close()


def reward_referrer_after_verification(user_id: int):
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        child = conn.execute(
            "SELECT referred_by,verified,referral_reward_paid FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()
        if not child or not child["verified"] or child["referral_reward_paid"]:
            conn.rollback(); return None
        referrer_id = child["referred_by"]
        if not referrer_id or referrer_id == user_id:
            conn.execute("UPDATE users SET referral_reward_paid=1,updated_at=? WHERE user_id=?",
                         (int(time.time()), user_id))
            conn.commit(); return None
        referrer = conn.execute("SELECT banned FROM users WHERE user_id=?", (referrer_id,)).fetchone()
        if not referrer or referrer["banned"]:
            conn.execute("UPDATE users SET referral_reward_paid=1,updated_at=? WHERE user_id=?",
                         (int(time.time()), user_id))
            conn.commit(); return None
        reward = float(get_setting("referral_reward", DEFAULT_REFERRAL_REWARD))
        now = int(time.time())
        conn.execute(
            """UPDATE users SET balance=ROUND(balance+?,8),
               referral_earnings=ROUND(referral_earnings+?,8),updated_at=? WHERE user_id=?""",
            (reward, reward, now, referrer_id),
        )
        conn.execute("UPDATE users SET referral_reward_paid=1,updated_at=? WHERE user_id=?",
                     (now, user_id))
        conn.commit()
        return reward
    except Exception:
        conn.rollback(); raise
    finally:
        conn.close()


def save_wallet(user_id: int, wallet_type: str, wallet_number: str):
    wallet_type = (wallet_type or "").strip().lower()
    wallet_number = (wallet_number or "").strip()
    if wallet_type == "cbe":
        valid = bool(re.fullmatch(r"1000\d{9}", wallet_number))
        normalized = "CBE"
    elif wallet_type == "telebirr":
        valid = bool(re.fullmatch(r"(09|07)\d{8}", wallet_number))
        normalized = "Telebirr"
    else:
        return False, "Invalid wallet type", False
    if not valid:
        return False, ("CBE must be 13 digits starting with 1000." if normalized == "CBE"
                       else "Telebirr must be 10 digits starting with 09 or 07."), False
    conn = db()
    try:
        duplicate = conn.execute(
            "SELECT user_id FROM users WHERE wallet_type=? AND wallet_number=? AND user_id!=?",
            (normalized, wallet_number, user_id),
        ).fetchone()
        suspicious = bool(duplicate)
        conn.execute(
            "UPDATE users SET wallet_type=?,wallet_number=?,wallet_suspicious=?,updated_at=? WHERE user_id=?",
            (normalized, wallet_number, 1 if suspicious else 0, int(time.time()), user_id),
        )
        conn.commit()
        return True, "Wallet saved successfully.", suspicious
    finally:
        conn.close()


def create_withdrawal(user_id: int, requested_amount=None):
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        user = conn.execute(
            "SELECT balance,banned,wallet_type,wallet_number,wallet_suspicious FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()
        if not user:
            conn.rollback(); return False, "User not found."
        if user["banned"]:
            conn.rollback(); return False, "Your account is banned."
        if not user["wallet_type"] or not user["wallet_number"]:
            conn.rollback(); return False, "Please save your wallet first."
        minimum = float(get_setting("min_withdraw", DEFAULT_MIN_WITHDRAW))
        available = float(user["balance"])
        amount = available if requested_amount in (None, "", 0) else float(requested_amount)
        if amount < minimum:
            conn.rollback(); return False, f"Minimum withdrawal is {minimum:.2f} ETB."
        if amount > available:
            conn.rollback(); return False, "Insufficient balance."
        pending = conn.execute(
            "SELECT id FROM withdrawals WHERE user_id=? AND status='pending' LIMIT 1", (user_id,)
        ).fetchone()
        if pending:
            conn.rollback(); return False, "You already have a pending withdrawal."
        now = int(time.time())
        cur = conn.execute(
            """INSERT INTO withdrawals
               (user_id,amount,wallet_type,wallet_number,status,suspicious,created_at)
               VALUES(?,?,?,?,?,?,?)""",
            (user_id, amount, user["wallet_type"], user["wallet_number"], "pending",
             int(bool(user["wallet_suspicious"])), now),
        )
        wid = cur.lastrowid
        conn.execute("UPDATE users SET balance=ROUND(balance-?,8),updated_at=? WHERE user_id=?",
                     (amount, now, user_id))
        conn.commit()
        return True, {
            "withdrawal_id": wid, "amount": amount,
            "wallet_type": user["wallet_type"], "wallet_number": user["wallet_number"],
            "suspicious": bool(user["wallet_suspicious"]),
        }
    except Exception:
        conn.rollback(); raise
    finally:
        conn.close()


def get_active_tasks(user_id: int):
    conn = db()
    try:
        return conn.execute(
            """SELECT t.*,
               (SELECT status FROM task_submissions s
                WHERE s.task_id=t.id AND s.user_id=?
                ORDER BY s.id DESC LIMIT 1) AS submission_status
               FROM tasks t WHERE t.active=1 ORDER BY t.id DESC""",
            (user_id,),
        ).fetchall()
    finally:
        conn.close()


def submit_task(user_id: int, task_id: int, proof: str):
    proof = (proof or "").strip()
    if not proof:
        return False, "Proof is required."
    if len(proof) > 4000:
        return False, "Proof is too long."
    conn = db()
    try:
        task = conn.execute("SELECT * FROM tasks WHERE id=? AND active=1", (task_id,)).fetchone()
        if not task:
            return False, "Task not found or inactive."
        latest = conn.execute(
            "SELECT id,status FROM task_submissions WHERE task_id=? AND user_id=? ORDER BY id DESC LIMIT 1",
            (task_id, user_id),
        ).fetchone()
        if latest and latest["status"] == "pending":
            return False, "Your previous submission is still pending."
        if latest and latest["status"] == "approved":
            return False, "This task is already approved."
        now = int(time.time())
        cur = conn.execute(
            "INSERT INTO task_submissions(task_id,user_id,proof,status,created_at) VALUES(?,?,?,?,?)",
            (task_id, user_id, proof, "pending", now),
        )
        conn.commit()
        return True, {
            "submission_id": cur.lastrowid, "task_id": task_id,
            "user_id": user_id, "reward": float(task["reward"]),
            "title": task["title"], "proof": proof,
        }
    finally:
        conn.close()


def get_required_channels():
    conn = db()
    try:
        rows = conn.execute(
            "SELECT username,name,url FROM required_channels WHERE active=1 ORDER BY id ASC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()

# ─────────────────────────── TELEGRAM CHECKS ───────────────────────────
async def check_channel_membership(user_id: int, channel_username: str):
    result = await telegram_request("getChatMember", {"chat_id": channel_username, "user_id": user_id})
    if not result.get("ok"):
        return False
    m = result.get("result", {})
    status = m.get("status")
    if status in {"member", "administrator", "creator"}:
        return True
    if status == "restricted" and m.get("is_member") is True:
        return True
    return False


async def check_all_channels(user_id: int):
    async def check(channel):
        joined = await check_channel_membership(user_id, channel["username"])
        return {**channel, "joined": joined}
    channels = get_required_channels()
    results = await asyncio.gather(*(check(ch) for ch in channels))
    verified_count = sum(1 for c in results if c["joined"])
    return {
        "verified": verified_count == len(channels) and len(channels) > 0,
        "verified_count": verified_count,
        "total": len(channels),
        "channels": results,
    }

# ─────────────────────────── ADMIN CALLBACKS (FIXED ROUTING) ───────────────────────────
def withdrawal_keyboard(wid: int):
    return {"inline_keyboard": [
        [{"text": "✅ Approve", "callback_data": f"wd_approve:{wid}"},
         {"text": "❌ Reject", "callback_data": f"wd_reject:{wid}"}],
        [{"text": "🚫 Ban User", "callback_data": f"wd_ban:{wid}"},
         {"text": "👥 Referral List", "callback_data": f"wd_refs:{wid}"}],
    ]}


def task_keyboard(sid: int):
    return {"inline_keyboard": [[
        {"text": "✅ Approve", "callback_data": f"task_approve:{sid}"},
        {"text": "❌ Reject", "callback_data": f"task_reject:{sid}"},
    ]]}


def format_user(row):
    name = html.escape(row["first_name"] or row["username"] or str(row["user_id"]))
    uname = f"@{html.escape(row['username'])}" if row["username"] else "No username"
    return f"{name} ({uname}) — <code>{row['user_id']}</code>"


async def notify_withdrawal(wid: int):
    conn = db()
    try:
        row = conn.execute(
            """SELECT w.*,u.username,u.first_name FROM withdrawals w
               JOIN users u ON u.user_id=w.user_id WHERE w.id=?""", (wid,)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return
    text = (
        "💸 <b>New Withdrawal</b>\n\n"
        f"🎯 ID: <code>{row['id']}</code>\n"
        f"👤 {format_user(row)}\n"
        f"💰 Amount: <b>{row['amount']:.2f} ETB</b>\n"
        f"🏦 Wallet: <b>{html.escape(row['wallet_type'])}</b>\n"
        f"📱 Number: <code>{html.escape(row['wallet_number'])}</code>\n"
        f"⚠️ Suspicious: {'YES' if row['suspicious'] else 'No'}"
    )
    await send_admin_message(text, withdrawal_keyboard(wid))


async def notify_task_submission(sid: int):
    conn = db()
    try:
        row = conn.execute(
            """SELECT s.*,t.title,t.reward,u.username,u.first_name
               FROM task_submissions s JOIN tasks t ON t.id=s.task_id
               JOIN users u ON u.user_id=s.user_id WHERE s.id=?""", (sid,)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return
    text = (
        "📋 <b>New Task Submission</b>\n\n"
        f"🎯 Submission: <code>{row['id']}</code>\n"
        f"📌 Task: <b>{html.escape(row['title'])}</b>\n"
        f"💰 Reward: <b>{row['reward']:.2f} ETB</b>\n"
        f"👤 {format_user(row)}\n\n"
        f"🧾 <b>Proof:</b>\n{html.escape(row['proof'])}"
    )
    await send_admin_message(text, task_keyboard(sid))


async def edit_callback_message(query, text, keyboard=None):
    data = {
        "chat_id": query["message"]["chat"]["id"],
        "message_id": query["message"]["message_id"],
        "text": text,
        "parse_mode": "HTML",
    }
    if keyboard is not None:
        data["reply_markup"] = keyboard
    return await telegram_request("editMessageText", data)


async def answer_callback(cb_id: str, text="", alert=False):
    return await telegram_request("answerCallbackQuery", {
        "callback_query_id": cb_id, "text": text, "show_alert": alert
    })


async def handle_admin_callback(query, data):
    admin_id = int(query["from"]["id"])
    if not is_admin(admin_id):
        await answer_callback(query["id"], "Not authorized.", True); return

    # IMPORTANT: wd_refs: MUST be checked BEFORE the generic wd_ handler
    if data.startswith("wd_refs:"):
        wid = int(data.split(":", 1)[1])
        conn = db()
        try:
            row = conn.execute("SELECT user_id FROM withdrawals WHERE id=?", (wid,)).fetchone()
            if not row:
                await answer_callback(query["id"], "Withdrawal not found.", True); return
            refs = conn.execute(
                "SELECT user_id,username,first_name,verified FROM users WHERE referred_by=? ORDER BY user_id DESC",
                (row["user_id"],),
            ).fetchall()
        finally:
            conn.close()
        if not refs:
            await answer_callback(query["id"], "No referrals found.", True); return
        lines = ["👥 <b>Referral List</b>"]
        for r in refs:
            name = html.escape(r["first_name"] or r["username"] or str(r["user_id"]))
            uname = f"@{html.escape(r['username'])}" if r["username"] else "No username"
            lines.append(f"• {name} ({uname}) — <code>{r['user_id']}</code> — {'Verified' if r['verified'] else 'Unverified'}")
        await send_message(admin_id, "\n".join(lines))
        await answer_callback(query["id"], "Referral list sent.")
        return

    if data.startswith(("wd_approve:", "wd_reject:", "wd_ban:")):
        action, raw_id = data.split(":", 1)
        wid = int(raw_id)
        conn = db()
        try:
            row = conn.execute("SELECT * FROM withdrawals WHERE id=?", (wid,)).fetchone()
            if not row:
                await answer_callback(query["id"], "Withdrawal not found.", True); return
            if row["status"] != "pending":
                await answer_callback(query["id"], f"Already {row['status']}.", True); return
            now = int(time.time())
            if action == "wd_approve":
                conn.execute(
                    "UPDATE withdrawals SET status='approved',processed_at=?,processed_by=? WHERE id=? AND status='pending'",
                    (now, admin_id, wid),
                )
                conn.execute("UPDATE users SET withdrawn_total=ROUND(withdrawn_total+?,8) WHERE user_id=?",
                             (row["amount"], row["user_id"]))
                status_text = "approved"
            elif action == "wd_reject":
                conn.execute(
                    "UPDATE withdrawals SET status='rejected',processed_at=?,processed_by=? WHERE id=? AND status='pending'",
                    (now, admin_id, wid),
                )
                conn.execute("UPDATE users SET balance=ROUND(balance+?,8),updated_at=? WHERE user_id=?",
                             (row["amount"], now, row["user_id"]))
                status_text = "rejected & refunded"
            else:  # wd_ban
                conn.execute("UPDATE users SET banned=1,updated_at=? WHERE user_id=?",
                             (now, row["user_id"]))
                status_text = "user banned"
            conn.commit()
        finally:
            conn.close()
        await answer_callback(query["id"], f"Withdrawal {status_text}.")
        await edit_callback_message(query, f"💸 <b>Withdrawal #{wid}</b>\n\nStatus: <b>{status_text}</b>")
        if action in {"wd_approve", "wd_reject"}:
            await send_message(row["user_id"],
                f"💸 <b>Withdrawal Update</b>\n\nAmount: <b>{row['amount']:.2f} ETB</b>\nStatus: <b>{status_text}</b>")
        elif action == "wd_ban":
            await send_message(row["user_id"], "🚫 Your Falcon World account has been banned.")
        return

    if data.startswith(("task_approve:", "task_reject:")):
        action, raw_id = data.split(":", 1)
        sid = int(raw_id)
        conn = db()
        try:
            row = conn.execute(
                """SELECT s.*,t.title,t.reward FROM task_submissions s
                   JOIN tasks t ON t.id=s.task_id WHERE s.id=?""", (sid,)
            ).fetchone()
            if not row:
                await answer_callback(query["id"], "Submission not found.", True); return
            if row["status"] != "pending":
                await answer_callback(query["id"], f"Already {row['status']}.", True); return
            now = int(time.time())
            if action == "task_approve":
                conn.execute(
                    "UPDATE task_submissions SET status='approved',reviewed_at=?,reviewed_by=? WHERE id=? AND status='pending'",
                    (now, admin_id, sid),
                )
                conn.execute(
                    "UPDATE users SET balance=ROUND(balance+?,8),task_earnings=ROUND(task_earnings+?,8),updated_at=? WHERE user_id=?",
                    (row["reward"], row["reward"], now, row["user_id"]),
                )
                status_text = "approved"
            else:
                conn.execute(
                    "UPDATE task_submissions SET status='rejected',reviewed_at=?,reviewed_by=? WHERE id=? AND status='pending'",
                    (now, admin_id, sid),
                )
                status_text = "rejected"
            conn.commit()
        finally:
            conn.close()
        await answer_callback(query["id"], f"Task {status_text}.")
        await edit_callback_message(query, f"📋 <b>Task Submission #{sid}</b>\n\nStatus: <b>{status_text}</b>")
        extra = f"\n💰 Reward: <b>+{row['reward']:.2f} ETB</b>" if status_text == "approved" else ""
        await send_message(row["user_id"],
            f"📋 <b>Task Update</b>\n\nTask: <b>{html.escape(row['title'])}</b>\nStatus: <b>{status_text}</b>{extra}")
        return

    await answer_callback(query["id"])


async def handle_callback(query):
    data = query.get("data", "")
    if data.startswith(("wd_", "task_")):
        await handle_admin_callback(query, data)
        return
    await answer_callback(query["id"])

# ─────────────────────────── MESSAGE HANDLER ───────────────────────────
def parse_start_ref(text: str):
    parts = text.split(maxsplit=1)
    if len(parts) != 2:
        return None
    payload = parts[1].strip()
    if payload.startswith("ref_") and payload[4:].isdigit():
        return int(payload[4:])
    return None


def main_keyboard():
    return {"inline_keyboard": [[{"text": "🚀 Open Falcon World", "web_app": {"url": MINI_APP_URL}}]]}


async def handle_message(message):
    chat = message.get("chat", {})
    user = message.get("from", {})
    chat_id = chat.get("id")
    user_id = user.get("id")
    if not chat_id or not user_id:
        return
    username = user.get("username", "")
    first_name = user.get("first_name", "")
    text = (message.get("text") or "").strip()
    referrer = parse_start_ref(text) if text.startswith("/start") else None
    ensure_user(user_id, username, first_name, referrer)

    if is_banned(user_id) and not is_admin(user_id):
        await send_message(chat_id, "🚫 Your account is currently banned.")
        return

    if text.startswith("/start"):
        await send_message(
            chat_id,
            "🦅 <b>WELCOME TO FALCON WORLD</b>\n\n"
            "💰 Earn & Complete Tasks\n"
            "🎁 Daily Rewards\n"
            "👥 Referral Rewards\n"
            "🚀 New Opportunities\n\n"
            "💱 USDT Exchange: Buy & Sell\n"
            f"📣 Ads & Promotions: DM {SUPPORT_USERNAME}\n\n"
            "🦅 <b>Tap the Falcon World button below to get started.</b>",
            main_keyboard(),
        )
        return

    # Web App is the user interface. Non-admin non-command text is ignored.
    if not is_admin(user_id) and not text.startswith("/"):
        return

    if text == "💼 Balance":
        row = get_user(user_id)
        await send_message(chat_id, f"💼 <b>Your Balance</b>\n\n<b>{row['balance']:.2f} ETB</b>", main_keyboard())
        return

    if text == "🎁 Daily Bonus":
        ok, result = claim_daily_bonus(user_id)
        if ok:
            await send_message(chat_id,
                f"🎁 <b>Daily Bonus Claimed!</b>\n\n+{result['reward']:.2f} ETB\n💼 Balance: {result['balance']:.2f} ETB",
                main_keyboard())
        elif result["error"] == "already_claimed":
            await send_message(chat_id, "⏳ Daily bonus already claimed today.", main_keyboard())
        elif result["error"] == "not_verified":
            await send_message(chat_id, "⚠️ Please verify all required channels first.", main_keyboard())
        else:
            await send_message(chat_id, "❌ Daily bonus could not be claimed.", main_keyboard())
        return

    if text == "👥 Invite Friends":
        link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"
        count = get_referral_count(user_id)
        reward = get_setting("referral_reward", DEFAULT_REFERRAL_REWARD)
        await send_message(chat_id,
            f"👥 <b>Invite Friends</b>\n\nInvite link:\n<code>{html.escape(link)}</code>\n\n"
            f"👤 Successful referrals: <b>{count}</b>\n"
            f"💵 Reward: <b>{reward:.2f} ETB</b> each\n\n"
            "Reward is credited after verification.",
            main_keyboard())
        return

    if text == "💳 Wallet Settings":
        row = get_user(user_id)
        wallet = "Not set"
        if row["wallet_type"] and row["wallet_number"]:
            wallet = f"{html.escape(row['wallet_type'])}: <code>{html.escape(row['wallet_number'])}</code>"
        await send_message(chat_id,
            f"💳 <b>Wallet Settings</b>\n\nCurrent: {wallet}\n\nUse the Mini App to save CBE or Telebirr.",
            main_keyboard())
        return

    if text == "💸 Withdraw":
        row = get_user(user_id)
        minimum = get_setting("min_withdraw", DEFAULT_MIN_WITHDRAW)
        await send_message(chat_id,
            f"💸 <b>Withdraw</b>\n\nBalance: <b>{row['balance']:.2f} ETB</b>\nMinimum: <b>{minimum:.2f} ETB</b>\n\nUse the Mini App to submit a withdrawal.",
            main_keyboard())
        return

    if text == "📋 Tasks":
        tasks = get_active_tasks(user_id)
        if not tasks:
            await send_message(chat_id, "📋 No active tasks right now.", main_keyboard())
            return
        lines = ["📋 <b>Active Tasks</b>\n"]
        for task in tasks[:10]:
            status = task["submission_status"] or "not submitted"
            lines.append(f"#{task['id']} <b>{html.escape(task['title'])}</b>\n💰 {task['reward']:.2f} ETB • {html.escape(status)}")
        lines.append("\n🚀 Open the Mini App to submit tasks.")
        await send_message(chat_id, "\n\n".join(lines), main_keyboard())
        return

    if text == "❓ Help":
        await send_message(chat_id,
            "❓ <b>Help</b>\n\n1. Join all required channels.\n2. Verify your account.\n"
            "3. Complete tasks and daily bonus.\n4. Save CBE or Telebirr.\n5. Withdraw when you reach the minimum.",
            main_keyboard())
        return

    if text == "🎧 Support":
        await send_message(chat_id, f"🎧 <b>Support</b>\n\nContact: {SUPPORT_USERNAME}", main_keyboard())
        return

    if text.startswith("/admin") and is_admin(user_id):
        await admin_dashboard(chat_id); return

    if text.startswith("/checkuser ") and is_admin(user_id):
        raw = text.split(maxsplit=1)[1].strip()
        if not raw.isdigit():
            await send_message(chat_id, "Usage: /checkuser USER_ID"); return
        t = get_user(int(raw))
        if not t:
            await send_message(chat_id, "User not found."); return
        refs = get_referral_count(t["user_id"])
        await send_message(chat_id,
            f"👤 <b>User</b>\n\nID: <code>{t['user_id']}</code>\nName: {html.escape(t['first_name'] or '')}\n"
            f"Username: @{html.escape(t['username'] or 'none')}\nBalance: <b>{t['balance']:.2f} ETB</b>\n"
            f"Referrals: {refs}\nVerified: {bool(t['verified'])}\nBanned: {bool(t['banned'])}\n"
            f"Wallet: {html.escape(t['wallet_type'] or 'none')} / <code>{html.escape(t['wallet_number'] or 'none')}</code>\n"
            f"Suspicious wallet: {bool(t['wallet_suspicious'])}")
        return

    if text.startswith("/addbalance ") and is_admin(user_id):
        parts = text.split()
        if len(parts) != 3 or not parts[1].lstrip("-").isdigit():
            await send_message(chat_id, "Usage: /addbalance USER_ID AMOUNT"); return
        target_id = int(parts[1]); amount = float(parts[2])
        if not get_user(target_id):
            await send_message(chat_id, "User not found."); return
        add_balance(target_id, amount)
        await send_message(chat_id, f"✅ Adjusted {amount:+.2f} ETB for {target_id}.")
        await send_message(target_id, f"💼 Admin adjustment: <b>{amount:+.2f} ETB</b>")
        return

    if text.startswith("/ban ") and is_admin(user_id):
        raw = text.split(maxsplit=1)[1].strip()
        if not raw.isdigit():
            await send_message(chat_id, "Usage: /ban USER_ID"); return
        conn = db()
        try:
            conn.execute("UPDATE users SET banned=1,updated_at=? WHERE user_id=?", (int(time.time()), int(raw)))
            conn.commit()
        finally:
            conn.close()
        await send_message(chat_id, "🚫 User banned."); return

    if text.startswith("/unban ") and is_admin(user_id):
        raw = text.split(maxsplit=1)[1].strip()
        if not raw.isdigit():
            await send_message(chat_id, "Usage: /unban USER_ID"); return
        conn = db()
        try:
            conn.execute("UPDATE users SET banned=0,updated_at=? WHERE user_id=?", (int(time.time()), int(raw)))
            conn.commit()
        finally:
            conn.close()
        await send_message(chat_id, "✅ User unbanned."); return

    if text.startswith("/setminwithdraw ") and is_admin(user_id):
        set_setting("min_withdraw", float(text.split(maxsplit=1)[1]))
        await send_message(chat_id, "✅ Minimum withdrawal updated."); return

    if text.startswith("/setdaily ") and is_admin(user_id):
        set_setting("daily_bonus", float(text.split(maxsplit=1)[1]))
        await send_message(chat_id, "✅ Daily bonus updated."); return

    if text.startswith("/setref ") and is_admin(user_id):
        set_setting("referral_reward", float(text.split(maxsplit=1)[1]))
        await send_message(chat_id, "✅ Referral reward updated."); return

    if text == "/channels" and is_admin(user_id):
        channels = get_required_channels()
        if not channels:
            await send_message(chat_id, "No required channels configured.")
        else:
            lines = ["📣 <b>Required Channels</b>"]
            for i, c in enumerate(channels, 1):
                lines.append(f"{i}. <b>{html.escape(c['name'])}</b> — {html.escape(c['username'])}\n{html.escape(c['url'])}")
            lines.append("\n/addchannel @u | Name | https://t.me/u\n/removechannel @u\n/editchannel @old | @new | Name | https://t.me/new")
            await send_message(chat_id, "\n\n".join(lines))
        return

    if text.startswith("/addchannel ") and is_admin(user_id):
        parts = [x.strip() for x in text.split("|", 2)]
        if len(parts) != 3:
            await send_message(chat_id, "Usage: /addchannel @username | Name | https://t.me/username"); return
        username, name, url = parts
        if not username.startswith("@"): username = "@" + username
        conn = db()
        try:
            conn.execute("INSERT INTO required_channels(username,name,url,active,created_at) VALUES(?,?,?,?,?)",
                         (username, name, url, 1, int(time.time())))
            conn.commit()
        except sqlite3.IntegrityError:
            await send_message(chat_id, "❌ Channel already exists."); return
        finally:
            conn.close()
        await send_message(chat_id, f"✅ Channel added: {html.escape(username)}"); return

    if text.startswith("/removechannel ") and is_admin(user_id):
        username = text.split(maxsplit=1)[1].strip()
        if not username.startswith("@"): username = "@" + username
        conn = db()
        try:
            cur = conn.execute("DELETE FROM required_channels WHERE username=?", (username,))
            conn.commit()
        finally:
            conn.close()
        await send_message(chat_id, "✅ Channel removed." if cur.rowcount else "❌ Channel not found."); return

    if text.startswith("/editchannel ") and is_admin(user_id):
        parts = [x.strip() for x in text.split("|", 3)]
        if len(parts) != 4:
            await send_message(chat_id, "Usage: /editchannel @old | @new | Name | https://t.me/new"); return
        old, new, name, url = parts
        if not old.startswith("@"): old = "@" + old
        if not new.startswith("@"): new = "@" + new
        conn = db()
        try:
            cur = conn.execute("UPDATE required_channels SET username=?,name=?,url=? WHERE username=?",
                               (new, name, url, old))
            conn.commit()
        finally:
            conn.close()
        await send_message(chat_id, "✅ Channel updated." if cur.rowcount else "❌ Channel not found."); return

    if text.startswith("/addtask ") and is_admin(user_id):
        parts = text.split("|", 3)
        if len(parts) != 4:
            await send_message(chat_id, "Usage: /addtask TITLE|DESCRIPTION|REWARD|URL"); return
        title, description, reward, url = [x.strip() for x in parts]
        try:
            reward = float(reward)
        except ValueError:
            await send_message(chat_id, "Reward must be a number."); return
        conn = db()
        try:
            cur = conn.execute(
                "INSERT INTO tasks(title,description,reward,url,active,created_at) VALUES(?,?,?,?,1,?)",
                (title, description, reward, url, int(time.time())),
            )
            conn.commit()
            task_id = cur.lastrowid
        finally:
            conn.close()
        await send_message(chat_id, f"✅ Task #{task_id} created."); return

    await send_message(chat_id, "Use the buttons below or open Falcon World 🚀", main_keyboard())


async def admin_dashboard(chat_id):
    conn = db()
    try:
        users = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        verified = conn.execute("SELECT COUNT(*) c FROM users WHERE verified=1").fetchone()["c"]
        banned = conn.execute("SELECT COUNT(*) c FROM users WHERE banned=1").fetchone()["c"]
        pending_wd = conn.execute("SELECT COUNT(*) c FROM withdrawals WHERE status='pending'").fetchone()["c"]
        pending_tasks = conn.execute("SELECT COUNT(*) c FROM task_submissions WHERE status='pending'").fetchone()["c"]
        total_balance = conn.execute("SELECT COALESCE(SUM(balance),0) s FROM users").fetchone()["s"]
    finally:
        conn.close()
    await send_message(chat_id,
        f"🛡 <b>Falcon World Admin</b>\n\n"
        f"👥 Users: <b>{users}</b>\n✅ Verified: <b>{verified}</b>\n🚫 Banned: <b>{banned}</b>\n"
        f"💼 Balances: <b>{total_balance:.2f} ETB</b>\n💸 Pending withdrawals: <b>{pending_wd}</b>\n"
        f"📋 Pending tasks: <b>{pending_tasks}</b>\n\n"
        "<b>Commands</b>\n/checkuser USER_ID\n/addbalance USER_ID AMOUNT\n/ban USER_ID\n/unban USER_ID\n"
        "/addtask TITLE|DESC|REWARD|URL\n/channels\n/setminwithdraw AMOUNT\n/setdaily AMOUNT\n/setref AMOUNT")


async def handle_update(update: dict):
    if "callback_query" in update:
        await handle_callback(update["callback_query"]); return
    message = update.get("message")
    if message:
        await handle_message(message)

# ─────────────────────────── FASTAPI ───────────────────────────
app = FastAPI(title="Falcon World")

# init at import (Render)
init_db()


def validate_init_data(init_data: str):
    if not init_data or not BOT_TOKEN:
        return None
    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = parsed.pop("hash", None)
        if not received_hash:
            return None
        data_check_string = "\n".join(f"{k}={parsed[k]}" for k in sorted(parsed.keys()))
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, received_hash):
            return None
        auth_date = int(parsed.get("auth_date", "0"))
        if auth_date <= 0 or time.time() - auth_date > 86400:
            return None
        user_json = parsed.get("user")
        if not user_json:
            return None
        user = json.loads(user_json)
        if not user.get("id"):
            return None
        return user
    except Exception:
        return None


async def require_user(request: Request):
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    user = validate_init_data(init_data)
    if not user:
        return None, JSONResponse({"error": "telegram_required"}, status_code=401)
    user_id = int(user["id"])
    if is_banned(user_id):
        return None, JSONResponse({"error": "banned"}, status_code=403)
    return user, None


@app.get("/falcon-bg.webp")
async def falcon_background():
    if os.path.exists(FALCON_BG_PATH):
        return FileResponse(FALCON_BG_PATH, media_type="image/webp",
                            headers={"Cache-Control": "public, max-age=86400"})
    return JSONResponse({"error": "not_found"}, status_code=404)

# ─────────────────────────── API ───────────────────────────
@app.post("/api/me")
async def api_me(request: Request):
    user, err = await require_user(request)
    if err: return err
    uid = int(user["id"])
    ensure_user(uid, user.get("username", ""), user.get("first_name", ""))
    row = get_user(uid)
    refs = get_referral_count(uid)
    return {
        "user_id": uid,
        "username": row["username"],
        "first_name": row["first_name"],
        "balance": round(float(row["balance"]), 2),
        "verified": bool(row["verified"]),
        "banned": bool(row["banned"]),
        "referral_count": refs,
        "referral_earnings": round(float(row["referral_earnings"] or 0), 2),
        "daily_earnings": round(float(row["daily_bonus_earnings"] or 0), 2),
        "task_earnings": round(float(row["task_earnings"] or 0), 2),
        "withdrawn_total": round(float(row["withdrawn_total"] or 0), 2),
        "wallet_type": row["wallet_type"],
        "wallet_number": row["wallet_number"],
        "wallet_suspicious": bool(row["wallet_suspicious"]),
        "daily_bonus": float(get_setting("daily_bonus", DEFAULT_DAILY_BONUS)),
        "referral_reward": float(get_setting("referral_reward", DEFAULT_REFERRAL_REWARD)),
        "min_withdraw": float(get_setting("min_withdraw", DEFAULT_MIN_WITHDRAW)),
        "bot_username": BOT_USERNAME,
        "support": SUPPORT_USERNAME,
    }


@app.get("/api/channels")
async def api_channels(request: Request):
    user, err = await require_user(request)
    if err: return err
    return {"channels": get_required_channels()}


@app.post("/api/verify")
async def api_verify(request: Request):
    user, err = await require_user(request)
    if err: return err
    uid = int(user["id"])
    result = await check_all_channels(uid)
    if result["verified"]:
        conn = db()
        try:
            conn.execute("UPDATE users SET verified=1, updated_at=? WHERE user_id=?",
                         (int(time.time()), uid))
            conn.commit()
        finally:
            conn.close()
        reward = reward_referrer_after_verification(uid)
        if reward:
            ref_row = get_user(uid)
            if ref_row and ref_row["referred_by"]:
                try:
                    await send_message(int(ref_row["referred_by"]),
                        f"👥 <b>Referral Reward</b>\n\n+{reward:.2f} ETB — a new user verified!")
                except Exception:
                    pass
    return result


@app.post("/api/daily")
async def api_daily(request: Request):
    user, err = await require_user(request)
    if err: return err
    ok, result = claim_daily_bonus(int(user["id"]))
    if ok:
        return {"ok": True, **result}
    return JSONResponse({"ok": False, **result}, status_code=400)


@app.get("/api/tasks")
async def api_tasks(request: Request):
    user, err = await require_user(request)
    if err: return err
    tasks = get_active_tasks(int(user["id"]))
    return {"tasks": [{
        "id": t["id"], "title": t["title"], "description": t["description"],
        "reward": float(t["reward"]), "url": t["url"],
        "status": t["submission_status"],
    } for t in tasks]}


@app.post("/api/tasks/{task_id}/submit")
async def api_submit_task(task_id: int, request: Request, payload: dict = Body(...)):
    user, err = await require_user(request)
    if err: return err
    proof = (payload.get("proof") or "").strip()
    ok, result = submit_task(int(user["id"]), task_id, proof)
    if not ok:
        return JSONResponse({"ok": False, "error": result}, status_code=400)
    try:
        await notify_task_submission(result["submission_id"])
    except Exception:
        pass
    return {"ok": True, **result}


@app.get("/api/referrals")
async def api_referrals(request: Request):
    user, err = await require_user(request)
    if err: return err
    uid = int(user["id"])
    conn = db()
    try:
        refs = conn.execute(
            "SELECT user_id, username, first_name, verified FROM users WHERE referred_by=? ORDER BY user_id DESC LIMIT 50",
            (uid,),
        ).fetchall()
    finally:
        conn.close()
    return {
        "link": f"https://t.me/{BOT_USERNAME}?start=ref_{uid}",
        "count": get_referral_count(uid),
        "reward": float(get_setting("referral_reward", DEFAULT_REFERRAL_REWARD)),
        "referrals": [{
            "user_id": r["user_id"],
            "name": r["first_name"] or r["username"] or str(r["user_id"]),
            "username": r["username"],
            "verified": bool(r["verified"]),
        } for r in refs],
    }


@app.post("/api/wallet")
async def api_wallet(request: Request, payload: dict = Body(...)):
    user, err = await require_user(request)
    if err: return err
    ok, msg, suspicious = save_wallet(int(user["id"]),
                                       payload.get("wallet_type", ""),
                                       payload.get("wallet_number", ""))
    if not ok:
        return JSONResponse({"ok": False, "error": msg}, status_code=400)
    return {"ok": True, "message": msg, "suspicious": suspicious}


@app.post("/api/withdraw")
async def api_withdraw(request: Request, payload: dict = Body(...)):
    user, err = await require_user(request)
    if err: return err
    amount = payload.get("amount")
    ok, result = create_withdrawal(int(user["id"]), amount)
    if not ok:
        return JSONResponse({"ok": False, "error": result}, status_code=400)
    try:
        await notify_withdrawal(result["withdrawal_id"])
    except Exception:
        pass
    return {"ok": True, **result}


@app.get("/api/activity")
async def api_activity(request: Request):
    user, err = await require_user(request)
    if err: return err
    uid = int(user["id"])
    conn = db()
    try:
        wds = conn.execute(
            "SELECT id,amount,wallet_type,wallet_number,status,created_at FROM withdrawals WHERE user_id=? ORDER BY id DESC LIMIT 40",
            (uid,),
        ).fetchall()
        subs = conn.execute(
            """SELECT s.id,s.status,s.created_at,t.title,t.reward FROM task_submissions s
               JOIN tasks t ON t.id=s.task_id WHERE s.user_id=? ORDER BY s.id DESC LIMIT 40""",
            (uid,),
        ).fetchall()
    finally:
        conn.close()
    return {
        "withdrawals": [dict(w) for w in wds],
        "submissions": [dict(s) for s in subs],
    }

# ─────────────────────────── WEBHOOK ───────────────────────────
@app.post("/webhook")
async def webhook(request: Request):
    if WEBHOOK_SECRET:
        header = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if header != WEBHOOK_SECRET:
            return JSONResponse({"ok": False}, status_code=401)
    try:
        update = await request.json()
    except Exception:
        return {"ok": True}
    asyncio.create_task(handle_update(update))
    return {"ok": True}

# ─────────────────────────── MINI APP UI ───────────────────────────
@app.get("/", response_class=HTMLResponse)
@app.get("/app", response_class=HTMLResponse)
async def mini_app():
    return HTMLResponse(MINI_APP_HTML)

MINI_APP_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
<meta name="theme-color" content="#050b18">
<title>Falcon World</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root{
  --bg:#050b18;--panel:#0b1830;--panel2:#0e1e3c;--line:rgba(80,150,255,.16);
  --text:#f5f9ff;--muted:#8ba0be;--blue:#2ea8ff;--blue2:#0f6fff;
  --gold:#ffc63f;--green:#34e6a4;--red:#ff6178;--violet:#7c68ff;
  --r:20px;--rs:14px;
}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;background:var(--bg);color:var(--text);font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;overflow-x:hidden}
body{min-height:100vh;padding-bottom:88px}
a{color:var(--blue);text-decoration:none}
button{font-family:inherit;cursor:pointer;border:0;outline:0;color:inherit}
input,textarea{font-family:inherit}
.hidden{display:none!important}

/* ─── Header ─── */
.header{
  position:sticky;top:0;z-index:20;
  padding:14px 18px;display:flex;align-items:center;gap:12px;
  background:linear-gradient(180deg,rgba(5,11,24,.96),rgba(5,11,24,.82));
  backdrop-filter:blur(14px);border-bottom:1px solid var(--line);
}
.logo{
  width:40px;height:40px;border-radius:12px;
  background:linear-gradient(135deg,#0f6fff,#2ea8ff 60%,#7c68ff);
  display:grid;place-items:center;font-size:22px;
  box-shadow:0 8px 24px -8px rgba(46,168,255,.6);
}
.brand{font-weight:800;letter-spacing:.3px;font-size:16px;line-height:1.1}
.brand small{display:block;color:var(--muted);font-weight:500;font-size:11px;letter-spacing:.5px}
.balance-chip{
  margin-left:auto;padding:8px 12px;border-radius:999px;
  background:linear-gradient(135deg,rgba(46,168,255,.16),rgba(124,104,255,.16));
  border:1px solid var(--line);font-weight:700;font-size:13px;
  display:flex;align-items:center;gap:6px;white-space:nowrap;
}
.balance-chip .amt{color:var(--gold)}

/* ─── Container ─── */
.wrap{padding:16px 16px 8px;max-width:640px;margin:0 auto}
.screen{display:none;animation:fade .25s ease}
.screen.active{display:block}
@keyframes fade{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}

/* ─── Cards ─── */
.card{
  background:linear-gradient(180deg,var(--panel),var(--panel2));
  border:1px solid var(--line);border-radius:var(--r);padding:16px;
  margin-bottom:14px;position:relative;overflow:hidden;
}
.hero{
  background:
    radial-gradient(120% 90% at 100% 0%,rgba(46,168,255,.22),transparent 55%),
    radial-gradient(90% 80% at 0% 100%,rgba(124,104,255,.22),transparent 55%),
    linear-gradient(180deg,#0b1830,#0a1428);
  border:1px solid rgba(80,150,255,.22);
}
.hero .label{color:var(--muted);font-size:12px;letter-spacing:.6px;text-transform:uppercase;font-weight:600}
.hero .amount{font-size:38px;font-weight:800;letter-spacing:-1px;margin:6px 0 2px;line-height:1}
.hero .amount .cur{font-size:18px;color:var(--muted);font-weight:600;margin-left:6px}
.hero .sub{color:var(--muted);font-size:12px;margin-top:6px}

.stats{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-top:14px}
.stat{background:rgba(0,0,0,.22);border:1px solid var(--line);border-radius:14px;padding:10px;text-align:center}
.stat .v{font-weight:800;font-size:14px}
.stat .k{color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.4px;margin-top:3px;font-weight:600}

/* ─── Section title ─── */
.sect{font-size:12px;color:var(--muted);font-weight:700;letter-spacing:1.4px;text-transform:uppercase;margin:20px 4px 10px}

/* ─── Actions ─── */
.actions{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.action{
  background:linear-gradient(180deg,var(--panel),var(--panel2));
  border:1px solid var(--line);border-radius:var(--r);padding:14px;
  display:flex;align-items:center;gap:12px;text-align:left;width:100%;
  transition:transform .12s ease,border-color .12s ease;
}
.action:active{transform:scale(.98);border-color:rgba(46,168,255,.5)}
.action .ico{
  width:40px;height:40px;border-radius:12px;flex:0 0 40px;
  display:grid;place-items:center;font-size:20px;
  background:linear-gradient(135deg,rgba(46,168,255,.22),rgba(124,104,255,.22));
  border:1px solid var(--line);
}
.action .ico.gold{background:linear-gradient(135deg,rgba(255,198,63,.22),rgba(255,140,0,.18));border-color:rgba(255,198,63,.32)}
.action .ico.green{background:linear-gradient(135deg,rgba(52,230,164,.2),rgba(0,180,110,.16));border-color:rgba(52,230,164,.3)}
.action .ico.violet{background:linear-gradient(135deg,rgba(124,104,255,.22),rgba(80,60,220,.18));border-color:rgba(124,104,255,.32)}
.action .ico.red{background:linear-gradient(135deg,rgba(255,97,120,.2),rgba(220,40,80,.16));border-color:rgba(255,97,120,.3)}
.action .t{font-weight:700;font-size:14px;line-height:1.15}
.action .s{color:var(--muted);font-size:11px;margin-top:3px}

/* ─── List rows ─── */
.row{
  display:flex;align-items:center;gap:12px;padding:14px;
  background:linear-gradient(180deg,var(--panel),var(--panel2));
  border:1px solid var(--line);border-radius:var(--rs);
  margin-bottom:8px;
}
.row .ico{width:38px;height:38px;border-radius:11px;flex:0 0 38px;display:grid;place-items:center;
  background:linear-gradient(135deg,rgba(46,168,255,.18),rgba(124,104,255,.18));border:1px solid var(--line);font-size:18px}
.row .body{flex:1;min-width:0}
.row .title{font-weight:700;font-size:14px}
.row .desc{color:var(--muted);font-size:12px;margin-top:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.row .right{font-weight:800;color:var(--gold);font-size:14px;text-align:right}

/* ─── Buttons ─── */
.btn{
  display:inline-flex;align-items:center;justify-content:center;gap:8px;
  padding:14px 18px;border-radius:14px;font-weight:700;font-size:14px;width:100%;
  background:linear-gradient(135deg,#2ea8ff,#0f6fff);color:#fff;
  box-shadow:0 8px 24px -10px rgba(46,168,255,.7);
  transition:transform .12s ease,opacity .12s ease;
}
.btn:active{transform:scale(.98)}
.btn.ghost{background:rgba(46,168,255,.12);color:var(--blue);border:1px solid rgba(46,168,255,.3);box-shadow:none}
.btn.gold{background:linear-gradient(135deg,#ffc63f,#ff9500);color:#1a1200;box-shadow:0 8px 24px -10px rgba(255,198,63,.7)}
.btn.dark{background:rgba(255,255,255,.05);border:1px solid var(--line);color:var(--text);box-shadow:none}
.btn.red{background:linear-gradient(135deg,#ff6178,#d32a4d);color:#fff}
.btn:disabled{opacity:.45;pointer-events:none}
.btn-row{display:flex;gap:8px;margin-top:12px}
.btn-row .btn{flex:1}

/* ─── Inputs ─── */
.label{display:block;font-size:12px;color:var(--muted);font-weight:600;margin:12px 0 6px;letter-spacing:.3px}
.input,textarea.input{
  width:100%;padding:14px 14px;border-radius:14px;
  background:rgba(0,0,0,.32);border:1px solid var(--line);color:var(--text);font-size:15px;
  outline:none;transition:border-color .15s;
}
.input:focus{border-color:var(--blue)}
.chips{display:flex;gap:8px;flex-wrap:wrap;margin-top:6px}
.chip{
  padding:10px 14px;border-radius:999px;font-size:13px;font-weight:600;
  background:rgba(255,255,255,.05);border:1px solid var(--line);color:var(--muted);
}
.chip.active{background:linear-gradient(135deg,rgba(46,168,255,.3),rgba(124,104,255,.24));color:#fff;border-color:rgba(46,168,255,.5)}

/* ─── Badges ─── */
.badge{display:inline-flex;padding:4px 8px;border-radius:999px;font-size:10px;font-weight:800;letter-spacing:.5px;text-transform:uppercase}
.badge.pending{background:rgba(255,198,63,.16);color:var(--gold);border:1px solid rgba(255,198,63,.32)}
.badge.approved{background:rgba(52,230,164,.16);color:var(--green);border:1px solid rgba(52,230,164,.32)}
.badge.rejected{background:rgba(255,97,120,.16);color:var(--red);border:1px solid rgba(255,97,120,.32)}

/* ─── Bottom nav ─── */
.nav{
  position:fixed;left:0;right:0;bottom:0;z-index:30;
  display:grid;grid-template-columns:repeat(4,1fr);
  padding:8px 8px calc(8px + env(safe-area-inset-bottom));
  background:linear-gradient(180deg,rgba(5,11,24,.86),rgba(5,11,24,.98));
  backdrop-filter:blur(18px);border-top:1px solid var(--line);
}
.nav button{
  background:none;display:flex;flex-direction:column;align-items:center;gap:3px;
  padding:8px 4px;color:var(--muted);font-size:10px;font-weight:700;letter-spacing:.3px;
}
.nav button .ni{font-size:20px;line-height:1}
.nav button.active{color:var(--blue)}
.nav button.active .ni{filter:drop-shadow(0 4px 12px rgba(46,168,255,.6))}

/* ─── Modal ─── */
.modal-bg{
  position:fixed;inset:0;z-index:40;background:rgba(3,8,18,.72);backdrop-filter:blur(6px);
  display:flex;align-items:flex-end;justify-content:center;padding:0;
}
.modal{
  width:100%;max-width:640px;max-height:88vh;overflow-y:auto;
  background:linear-gradient(180deg,#0d1c38,#0a1528);
  border-radius:24px 24px 0 0;border:1px solid var(--line);border-bottom:0;
  padding:20px 18px calc(24px + env(safe-area-inset-bottom));
  animation:slideUp .28s cubic-bezier(.2,.8,.2,1);
}
@keyframes slideUp{from{transform:translateY(30px);opacity:.5}to{transform:none;opacity:1}}
.modal h3{margin:0 0 4px;font-size:19px;letter-spacing:-.3px}
.modal .muted{color:var(--muted);font-size:13px;margin-bottom:14px}
.mh{display:flex;align-items:center;gap:10px;margin-bottom:14px}
.mh .close{margin-left:auto;background:rgba(255,255,255,.06);border:1px solid var(--line);border-radius:10px;width:34px;height:34px;display:grid;place-items:center;font-size:16px}

/* ─── Toast ─── */
.toast{
  position:fixed;left:50%;bottom:110px;transform:translateX(-50%);
  padding:12px 18px;border-radius:14px;background:rgba(20,35,65,.96);
  border:1px solid var(--line);font-size:13px;font-weight:600;z-index:80;
  box-shadow:0 12px 40px -12px rgba(0,0,0,.7);
  animation:toastIn .25s ease;
}
@keyframes toastIn{from{transform:translate(-50%,14px);opacity:0}to{transform:translate(-50%,0);opacity:1}}

/* ─── Loader ─── */
.center{display:grid;place-items:center;min-height:60vh;text-align:center;padding:20px}
.spinner{width:44px;height:44px;border-radius:50%;border:3px solid rgba(46,168,255,.18);border-top-color:var(--blue);animation:spin 1s linear infinite;margin:0 auto 14px}
@keyframes spin{to{transform:rotate(360deg)}}
</style>
</head>
<body>

<div id="loading" class="center">
  <div>
    <div class="spinner"></div>
    <div style="color:var(--muted);font-size:13px">Loading Falcon World…</div>
  </div>
</div>

<div id="app" class="hidden">
  <header class="header">
    <div class="logo">🦅</div>
    <div class="brand">Falcon World<small>Earn • Complete • Grow</small></div>
    <div class="balance-chip">💼 <span class="amt" id="chipBalance">0.00</span> ETB</div>
  </header>

  <main class="wrap">
    <!-- VERIFY SCREEN -->
    <section id="screen-verify" class="screen">
      <div class="card hero" style="text-align:center;padding:24px 18px">
        <div style="font-size:48px;line-height:1;margin-bottom:8px">🦅</div>
        <h2 style="margin:0 0 6px;font-size:20px">Welcome to Falcon World</h2>
        <div class="sub" style="color:var(--muted);font-size:13px;margin-bottom:6px">Join the required channels to continue.</div>
      </div>
      <div class="sect">Required Channels</div>
      <div id="channelsList"></div>
      <button class="btn" id="verifyBtn" style="margin-top:10px">🔄 Verify &amp; Continue</button>
      <div style="text-align:center;color:var(--muted);font-size:12px;margin-top:12px">After joining all channels, tap Verify.</div>
    </section>

    <!-- OVERVIEW -->
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
        <button class="action" data-nav="earn">
          <div class="ico gold">🎁</div>
          <div><div class="t">Earn</div><div class="s">Daily &amp; Tasks</div></div>
        </button>
        <button class="action" id="inviteBtn">
          <div class="ico violet">👥</div>
          <div><div class="t">Invite</div><div class="s">Refer &amp; earn</div></div>
        </button>
        <button class="action" id="walletBtn">
          <div class="ico">💳</div>
          <div><div class="t">Wallet</div><div class="s">CBE / Telebirr</div></div>
        </button>
        <button class="action" id="withdrawBtn">
          <div class="ico green">💸</div>
          <div><div class="t">Payout</div><div class="s">Withdraw ETB</div></div>
        </button>
      </div>

      <div class="sect">Services &amp; Support</div>
      <button class="action" id="servicesBtn" style="width:100%">
        <div class="ico red">🛠</div>
        <div><div class="t">Services &amp; Support</div><div class="s">Promotions, USDT, growth…</div></div>
      </button>
    </section>

    <!-- EARN -->
    <section id="screen-earn" class="screen">
      <div class="sect">Daily Reward</div>
      <div class="card hero" style="text-align:center">
        <div style="font-size:40px;line-height:1">🎁</div>
        <div style="font-size:26px;font-weight:800;color:var(--gold);margin-top:4px" id="dailyAmount">+0.50 ETB</div>
        <div class="sub" style="color:var(--muted);font-size:12px;margin:4px 0 14px">Claim once every day</div>
        <button class="btn gold" id="dailyBtn">Claim Daily Bonus</button>
      </div>

      <div class="sect">Tasks</div>
      <div id="tasksList"><div style="color:var(--muted);font-size:13px;text-align:center;padding:20px">No active tasks right now.</div></div>
    </section>

    <!-- ACTIVITY -->
    <section id="screen-activity" class="screen">
      <div class="sect">Withdrawals</div>
      <div id="withdrawalsList"><div style="color:var(--muted);font-size:13px;text-align:center;padding:16px">No withdrawals yet.</div></div>
      <div class="sect">Task Submissions</div>
      <div id="submissionsList"><div style="color:var(--muted);font-size:13px;text-align:center;padding:16px">No task submissions yet.</div></div>
    </section>

    <!-- ACCOUNT -->
    <section id="screen-account" class="screen">
      <div class="card hero">
        <div style="display:flex;align-items:center;gap:12px">
          <div class="logo" style="width:52px;height:52px;font-size:26px">🦅</div>
          <div>
            <div style="font-weight:800;font-size:17px" id="accName">—</div>
            <div style="color:var(--muted);font-size:12px" id="accUser">—</div>
          </div>
        </div>
        <div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap">
          <span class="badge approved" id="accVerified">Verified</span>
          <span class="badge pending" id="accId">ID —</span>
        </div>
      </div>

      <div class="sect">Wallet</div>
      <div class="row">
        <div class="ico">💳</div>
        <div class="body">
          <div class="title" id="accWalletType">Not set</div>
          <div class="desc" id="accWalletNum">Save CBE or Telebirr</div>
        </div>
        <button class="btn ghost" style="width:auto;padding:10px 14px;font-size:12px" id="walletBtn2">Edit</button>
      </div>

      <div class="sect">Referral</div>
      <button class="row" id="refRow" style="width:100%;text-align:left">
        <div class="ico violet">👥</div>
        <div class="body">
          <div class="title">Invite Friends</div>
          <div class="desc" id="accRefDesc">Earn per verified referral</div>
        </div>
        <div class="right" id="accRefCount">0</div>
      </button>

      <div class="sect">Support</div>
      <a class="row" href="https://t.me/AmanM_12" target="_blank" style="text-decoration:none;color:inherit">
        <div class="ico red">🎧</div>
        <div class="body">
          <div class="title">Contact Support</div>
          <div class="desc">@AmanM_12</div>
        </div>
      </a>

      <div style="height:20px"></div>
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
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
let STATE = { me:null, tasks:[], channels:[] };

async function api(path, opts={}){
  const r = await fetch(path, {
    method: opts.method || 'GET',
    headers: { 'Content-Type':'application/json', 'X-Telegram-Init-Data': initData, ...(opts.headers||{}) },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  let data = {};
  try { data = await r.json(); } catch(e){}
  return { ok: r.ok, status: r.status, data };
}
function toast(msg, ms=2000){
  const t = document.createElement('div');
  t.className = 'toast'; t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(()=>t.remove(), ms);
}
function fmt(n){ return (Number(n)||0).toFixed(2); }
function esc(s){ return String(s ?? '').replace(/[&<>"']/g, c=>({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c])); }

function showScreen(name){
  $$('.screen').forEach(s => s.classList.remove('active'));
  const el = $('#screen-' + name);
  if (el) el.classList.add('active');
  $$('.nav button').forEach(b => b.classList.toggle('active', b.dataset.nav === name));
  if (name === 'activity') loadActivity();
}
document.addEventListener('click', e => {
  const btn = e.target.closest('[data-nav]');
  if (btn) showScreen(btn.dataset.nav);
});

function updateHeader(){
  if (STATE.me) $('#chipBalance').textContent = fmt(STATE.me.balance);
}

function renderVerify(data){
  STATE.channels = data.channels || [];
  const box = $('#channelsList');
  box.innerHTML = STATE.channels.map(c => `
    <a class="row" href="${esc(c.url)}" target="_blank" rel="noopener">
      <div class="ico">📢</div>
      <div class="body">
        <div class="title">${esc(c.name)}</div>
        <div class="desc">${esc(c.username)}</div>
      </div>
      <div class="right" style="color:var(--blue);font-size:12px">Join →</div>
    </a>
  `).join('');
}

function renderApp(){
  const m = STATE.me;
  $('#ovBalance').textContent = fmt(m.balance);
  $('#ovGreeting').textContent = 'Hello, ' + (m.first_name || m.username || 'Falcon') + ' 👋';
  $('#ovTotal').textContent = fmt(m.balance + m.withdrawn_total);
  $('#ovRefs').textContent = m.referral_count || 0;
  $('#ovOut').textContent = fmt(m.withdrawn_total);
  $('#dailyAmount').textContent = '+' + fmt(m.daily_bonus) + ' ETB';

  $('#accName').textContent = m.first_name || m.username || ('User ' + m.user_id);
  $('#accUser').textContent = m.username ? '@' + m.username : 'No username';
  $('#accId').textContent = 'ID ' + m.user_id;
  $('#accVerified').textContent = m.verified ? '✓ Verified' : 'Unverified';
  $('#accVerified').className = 'badge ' + (m.verified ? 'approved' : 'pending');

  $('#accWalletType').textContent = m.wallet_type ? m.wallet_type : 'Not set';
  $('#accWalletNum').textContent = m.wallet_number ? m.wallet_number : 'Save CBE or Telebirr';
  if (m.wallet_suspicious) {
    $('#accWalletNum').textContent += ' ⚠️';
  }
  $('#accRefDesc').textContent = 'Earn ' + fmt(m.referral_reward) + ' ETB per verified invite';
  $('#accRefCount').textContent = m.referral_count || 0;
  updateHeader();
}

async function loadMe(){
  const r = await api('/api/me', { method:'POST' });
  if (!r.ok) {
    if (r.status === 401) { $('#loading').innerHTML = '<div class="center"><div>Open this app from Telegram.</div></div>'; return; }
    if (r.status === 403) { $('#loading').innerHTML = '<div class="center"><div style="color:var(--red)">🚫 Your account has been restricted.</div></div>'; return; }
    toast('Failed to load'); return;
  }
  STATE.me = r.data;
}

async function loadTasks(){
  const r = await api('/api/tasks');
  if (r.ok) STATE.tasks = r.data.tasks || [];
  renderTasks();
}
function renderTasks(){
  const box = $('#tasksList');
  if (!STATE.tasks.length){
    box.innerHTML = '<div style="color:var(--muted);font-size:13px;text-align:center;padding:20px">No active tasks right now.</div>';
    return;
  }
  box.innerHTML = STATE.tasks.map(t => {
    const st = t.status ? `<span class="badge ${t.status}">${t.status}</span>` : '';
    const disabled = (t.status === 'pending' || t.status === 'approved') ? 'disabled' : '';
    return `
      <div class="row" style="flex-direction:column;align-items:stretch;gap:10px">
        <div style="display:flex;gap:12px;align-items:center">
          <div class="ico">📋</div>
          <div class="body">
            <div class="title">${esc(t.title)}</div>
            <div class="desc">${esc(t.description || '')}</div>
          </div>
          <div class="right">+${fmt(t.reward)} ETB</div>
        </div>
        ${st ? `<div>${st}</div>` : ''}
        <div class="btn-row">
          ${t.url ? `<a class="btn dark" href="${esc(t.url)}" target="_blank" rel="noopener" style="text-decoration:none">Open</a>` : ''}
          <button class="btn" data-task="${t.id}" ${disabled}>Submit</button>
        </div>
      </div>`;
  }).join('');
  $$('[data-task]').forEach(b => b.addEventListener('click', () => openSubmit(parseInt(b.dataset.task))));
}

async function loadActivity(){
  const r = await api('/api/activity');
  if (!r.ok) return;
  const { withdrawals, submissions } = r.data;
  const wbox = $('#withdrawalsList');
  wbox.innerHTML = (withdrawals || []).length ? withdrawals.map(w => `
    <div class="row">
      <div class="ico">💸</div>
      <div class="body">
        <div class="title">${fmt(w.amount)} ETB</div>
        <div class="desc">${esc(w.wallet_type)} • ${new Date(w.created_at*1000).toLocaleDateString()}</div>
      </div>
      <span class="badge ${w.status}">${w.status}</span>
    </div>`).join('') : '<div style="color:var(--muted);font-size:13px;text-align:center;padding:16px">No withdrawals yet.</div>';
  const sbox = $('#submissionsList');
  sbox.innerHTML = (submissions || []).length ? submissions.map(s => `
    <div class="row">
      <div class="ico">📋</div>
      <div class="body">
        <div class="title">${esc(s.title)}</div>
        <div class="desc">+${fmt(s.reward)} ETB • ${new Date(s.created_at*1000).toLocaleDateString()}</div>
      </div>
      <span class="badge ${s.status}">${s.status}</span>
    </div>`).join('') : '<div style="color:var(--muted);font-size:13px;text-align:center;padding:16px">No task submissions yet.</div>';
}

/* ─── Modals ─── */
function closeModal(){ const m = $('.modal-bg'); if (m) m.remove(); }
function openModal(html){
  closeModal();
  const wrap = document.createElement('div');
  wrap.className = 'modal-bg';
  wrap.innerHTML = `<div class="modal">${html}</div>`;
  wrap.addEventListener('click', e => { if (e.target === wrap) closeModal(); });
  document.body.appendChild(wrap);
  wrap.querySelectorAll('[data-close]').forEach(b => b.addEventListener('click', closeModal));
}

function openSubmit(taskId){
  const t = STATE.tasks.find(x => x.id === taskId);
  if (!t) return;
  openModal(`
    <div class="mh">
      <h3>Submit Proof</h3>
      <button class="close" data-close>✕</button>
    </div>
    <div class="muted">${esc(t.title)} • +${fmt(t.reward)} ETB</div>
    <label class="label">Proof (text, link, or screenshot URL)</label>
    <textarea class="input" id="proofInput" rows="5" placeholder="Paste proof or describe what you did…"></textarea>
    <div class="btn-row">
      <button class="btn dark" data-close>Cancel</button>
      <button class="btn" id="submitProofBtn">Submit</button>
    </div>
  `);
  $('#submitProofBtn').addEventListener('click', async () => {
    const proof = ($('#proofInput').value || '').trim();
    if (!proof) { toast('Proof is required'); return; }
    const r = await api(`/api/tasks/${taskId}/submit`, { method:'POST', body:{ proof } });
    if (r.ok) { toast('✅ Submitted for review'); closeModal(); loadTasks(); }
    else { toast(r.data.error || 'Failed'); }
  });
}

function openInvite(){
  const m = STATE.me;
  openModal(`
    <div class="mh"><h3>Invite Friends</h3><button class="close" data-close>✕</button></div>
    <div class="muted">Earn <b style="color:var(--gold)">${fmt(m.referral_reward)} ETB</b> per verified referral.</div>
    <div class="card hero" style="text-align:center;margin-top:8px">
      <div class="label">Your Referral Link</div>
      <div style="word-break:break-all;font-size:13px;margin:8px 0;color:var(--blue)" id="refLink">https://t.me/${esc(m.bot_username)}?start=ref_${m.user_id}</div>
      <button class="btn" id="copyRef">📋 Copy Link</button>
    </div>
    <div class="card">
      <div style="display:flex;justify-content:space-between"><span class="muted">Verified referrals</span><b>${m.referral_count}</b></div>
      <div style="display:flex;justify-content:space-between;margin-top:6px"><span class="muted">Referral earnings</span><b style="color:var(--gold)">${fmt(m.referral_earnings)} ETB</b></div>
    </div>
  `);
  $('#copyRef').addEventListener('click', async () => {
    const link = $('#refLink').textContent;
    try { await navigator.clipboard.writeText(link); toast('Copied!'); }
    catch(e){ tg?.openTelegramLink?.(`https://t.me/share/url?url=${encodeURIComponent(link)}`); }
  });
}

function openWallet(){
  const m = STATE.me;
  openModal(`
    <div class="mh"><h3>Wallet</h3><button class="close" data-close>✕</button></div>
    <div class="muted">Choose a payment method and enter your number.</div>
    <div class="chips">
      <button class="chip ${m.wallet_type==='CBE'?'active':''}" data-w="cbe">🏦 CBE</button>
      <button class="chip ${m.wallet_type==='Telebirr'?'active':''}" data-w="telebirr">📱 Telebirr</button>
    </div>
    <label class="label">Wallet Number</label>
    <input class="input" id="wnum" placeholder="${m.wallet_number || 'Enter number'}" value="${m.wallet_number || ''}">
    <div style="color:var(--muted);font-size:11px;margin-top:6px">CBE: 13 digits starting 1000 · Telebirr: 10 digits starting 09/07</div>
    <div class="btn-row">
      <button class="btn dark" data-close>Cancel</button>
      <button class="btn" id="saveWallet">Save</button>
    </div>
  `);
  let wt = m.wallet_type ? m.wallet_type.toLowerCase() : 'cbe';
  $$('.chip[data-w]').forEach(c => c.addEventListener('click', () => {
    wt = c.dataset.w;
    $$('.chip[data-w]').forEach(x => x.classList.toggle('active', x === c));
  }));
  $('#saveWallet').addEventListener('click', async () => {
    const num = ($('#wnum').value || '').trim();
    const r = await api('/api/wallet', { method:'POST', body:{ wallet_type: wt, wallet_number: num } });
    if (r.ok) { toast('✅ Wallet saved'); closeModal(); await refresh(); }
    else { toast(r.data.error || 'Invalid'); }
  });
}

function openWithdraw(){
  const m = STATE.me;
  if (!m.wallet_type || !m.wallet_number) { toast('Save your wallet first'); openWallet(); return; }
  openModal(`
    <div class="mh"><h3>Request Payout</h3><button class="close" data-close>✕</button></div>
    <div class="muted">Available: <b style="color:var(--gold)">${fmt(m.balance)} ETB</b> · Minimum: ${fmt(m.min_withdraw)} ETB</div>
    <label class="label">Amount (ETB)</label>
    <input class="input" id="wamount" type="number" step="0.01" value="${Math.max(m.balance, m.min_withdraw).toFixed(2)}">
    <div class="card" style="margin-top:12px">
      <div style="display:flex;justify-content:space-between"><span class="muted">Method</span><b>${esc(m.wallet_type)}</b></div>
      <div style="display:flex;justify-content:space-between;margin-top:6px"><span class="muted">Wallet</span><b>${esc(m.wallet_number)}</b></div>
    </div>
    <div class="btn-row">
      <button class="btn dark" data-close>Cancel</button>
      <button class="btn gold" id="doWithdraw">🚀 Request Withdrawal</button>
    </div>
  `);
  $('#doWithdraw').addEventListener('click', async () => {
    const amount = parseFloat($('#wamount').value || 0);
    const r = await api('/api/withdraw', { method:'POST', body:{ amount } });
    if (r.ok) { toast('⏳ Withdrawal requested'); closeModal(); await refresh(); }
    else { toast(r.data.error || 'Failed'); }
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
  openModal(`
    <div class="mh"><h3>Services &amp; Support</h3><button class="close" data-close>✕</button></div>
    <div class="muted">Contact <b>@AmanM_12</b> for any of these services.</div>
    ${items.map(([i,t,d]) => `
      <a class="row" href="https://t.me/AmanM_12" target="_blank" style="text-decoration:none;color:inherit;margin-bottom:8px">
        <div class="ico">${i}</div>
        <div class="body"><div class="title">${t}</div><div class="desc">${d}</div></div>
      </a>
    `).join('')}
  `);
}

async function refresh(){
  await loadMe();
  if (!STATE.me) return;
  renderApp();
  if (!STATE.me.verified) {
    const rc = await api('/api/channels');
    renderVerify(rc.data);
    showScreen('verify');
  } else {
    await loadTasks();
    if (!$('.screen.active')) showScreen('overview');
  }
}

async function verifyChannels(){
  const btn = $('#verifyBtn');
  btn.disabled = true; btn.textContent = 'Checking…';
  const r = await api('/api/verify', { method:'POST' });
  if (r.ok && r.data.verified) {
    toast('✅ Verification complete');
    await refresh();
  } else {
    const missing = (r.data.channels || []).filter(c => !c.joined).length;
    toast(`⚠️ ${missing} channel(s) still need to be joined`);
    renderVerify({ channels: r.data.channels });
  }
  btn.disabled = false; btn.textContent = '🔄 Verify & Continue';
}

/* ─── Wire buttons ─── */
$('#verifyBtn')?.addEventListener('click', verifyChannels);
$('#dailyBtn')?.addEventListener('click', async () => {
  const r = await api('/api/daily', { method:'POST' });
  if (r.ok) { toast('🎁 +' + fmt(r.data.reward) + ' ETB claimed'); await refresh(); }
  else { toast(r.data.error === 'already_claimed' ? 'Already claimed today' : (r.data.error || 'Failed')); }
});
$('#inviteBtn')?.addEventListener('click', openInvite);
$('#refRow')?.addEventListener('click', openInvite);
$('#walletBtn')?.addEventListener('click', openWallet);
$('#walletBtn2')?.addEventListener('click', openWallet);
$('#withdrawBtn')?.addEventListener('click', openWithdraw);
$('#servicesBtn')?.addEventListener('click', openServices);

/* ─── Boot ─── */
(async () => {
  try {
    await loadMe();
    if (!STATE.me) return;
    $('#loading').classList.add('hidden');
    $('#app').classList.remove('hidden');
    renderApp();
    if (!STATE.me.verified) {
      const rc = await api('/api/channels');
      renderVerify(rc.data);
      showScreen('verify');
    } else {
      await loadTasks();
      showScreen('overview');
    }
  } catch (e) {
    console.error(e);
    $('#loading').innerHTML = '<div class="center"><div>Failed to load. Please try again.</div></div>';
  }
})();
</script>
</body>
</html>
"""
