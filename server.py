# Falcon World — single-file Telegram Bot + FastAPI Mini App
# The complete bot/database/webhook logic and Mini App API live in this file.
# Render Start Command:
# uvicorn server:app --host 0.0.0.0 --port $PORT

import json
import hmac
import hashlib
import time
import asyncio
from urllib.parse import parse_qsl

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse

import os
import re
import sqlite3
import time
import html
from typing import Optional

import httpx

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", os.getenv("ADMIN_ID", "")).strip()
ADMIN_IDS = {int(x.strip()) for x in ADMIN_IDS_RAW.split(",") if x.strip().isdigit()}

BOT_USERNAME = os.getenv("BOT_USERNAME", "FalconWorld_Bot").strip().lstrip("@")
MINI_APP_URL = os.getenv("MINI_APP_URL", "https://falcon-world.onrender.com/app").strip()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FALCON_BG_PATH = os.path.join(BASE_DIR, "falcon-bg.webp")

DB_PATH = os.getenv("DB_PATH", "falcon_world.db").strip() or "falcon_world.db"

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

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""


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
            processed_by INTEGER,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
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
            reviewed_by INTEGER,
            FOREIGN KEY(task_id) REFERENCES tasks(id),
            FOREIGN KEY(user_id) REFERENCES users(user_id)
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
        CREATE INDEX IF NOT EXISTS idx_submissions_task_user ON task_submissions(task_id, user_id);
        """)
        # Safe migrations for existing Falcon World databases.
        existing = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
        for col, definition in {
            "referral_earnings": "REAL NOT NULL DEFAULT 0",
            "daily_bonus_earnings": "REAL NOT NULL DEFAULT 0",
            "task_earnings": "REAL NOT NULL DEFAULT 0",
        }.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE users ADD COLUMN {col} {definition}")

        if conn.execute("SELECT COUNT(*) c FROM required_channels").fetchone()["c"] == 0:
            now_seed = int(time.time())
            conn.executemany(
                "INSERT OR IGNORE INTO required_channels(username,name,url,active,created_at) VALUES(?,?,?,?,?)",
                [(c["username"], c["name"], c["url"], 1, now_seed) for c in REQUIRED_CHANNELS],
            )

        defaults = {
            "daily_bonus": DEFAULT_DAILY_BONUS,
            "referral_reward": DEFAULT_REFERRAL_REWARD,
            "min_withdraw": DEFAULT_MIN_WITHDRAW,
        }
        for key, value in defaults.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)",
                (key, str(value)),
            )
        conn.commit()
    finally:
        conn.close()


def get_setting(key: str, default=None):
    conn = db()
    try:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        if not row:
            return default
        value = row["value"]
        if isinstance(default, int):
            return int(float(value))
        if isinstance(default, float):
            return float(value)
        return value
    finally:
        conn.close()


def set_setting(key: str, value):
    conn = db()
    try:
        conn.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
        conn.commit()
    finally:
        conn.close()


def configure_bot():
    global BOT_TOKEN, TELEGRAM_API
    BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
    TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""


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
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        data["reply_markup"] = reply_markup
    return await telegram_request("sendMessage", data)


async def send_admin_message(text: str, keyboard=None):
    results = []
    for admin_id in ADMIN_IDS:
        results.append(await send_message(admin_id, text, keyboard))
    return results


def is_admin(user_id: int) -> bool:
    return int(user_id) in ADMIN_IDS


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
                (user_id, username or "", first_name or "", 0, 0, 0,
                 referred_by, 0, 0, 0, now, now),
            )
        else:
            conn.execute(
                "UPDATE users SET username=?, first_name=?, updated_at=? WHERE user_id=?",
                (username or "", first_name or "", now, user_id),
            )
            if referred_by and not row["referred_by"] and referred_by != user_id:
                conn.execute(
                    "UPDATE users SET referred_by=? WHERE user_id=?",
                    (referred_by, user_id),
                )
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
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM users WHERE referred_by=? AND referral_reward_paid=1",
            (user_id,),
        ).fetchone()
        return int(row["c"])
    finally:
        conn.close()


def _local_gregorian_date(ts: int | None = None):
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Africa/Addis_Ababa")
        return datetime.fromtimestamp(ts or time.time(), tz).date()
    except Exception:
        return datetime.utcfromtimestamp(ts or time.time()).date()


def claim_daily_bonus(user_id: int):
    now = int(time.time())
    today = _local_gregorian_date(now)
    reward = float(get_setting("daily_bonus", DEFAULT_DAILY_BONUS))
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT banned,verified,daily_last_claim,balance FROM users WHERE user_id=?",
            (user_id,),
        ).fetchone()
        if not row:
            conn.rollback()
            return False, {"error": "user_not_found"}
        if row["banned"]:
            conn.rollback()
            return False, {"error": "banned"}
        if not row["verified"]:
            conn.rollback()
            return False, {"error": "not_verified"}
        last = int(row["daily_last_claim"] or 0)
        if last and _local_gregorian_date(last) == today:
            conn.rollback()
            return False, {"error": "already_claimed", "date": str(today)}
        conn.execute(
            "UPDATE users SET balance=ROUND(balance+?,8),daily_bonus_earnings=ROUND(daily_bonus_earnings+?,8),daily_last_claim=?,updated_at=? WHERE user_id=?",
            (reward, reward, now, now, user_id),
        )
        conn.commit()
        from datetime import timedelta
        return True, {"reward": reward, "balance": float(row["balance"]) + reward,
                      "date": str(today), "next_date": str(today + timedelta(days=1))}
    except Exception:
        conn.rollback()
        raise
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
            conn.rollback()
            return None
        referrer_id = child["referred_by"]
        if not referrer_id or referrer_id == user_id:
            conn.execute(
                "UPDATE users SET referral_reward_paid=1,updated_at=? WHERE user_id=?",
                (int(time.time()), user_id),
            )
            conn.commit()
            return None
        referrer = conn.execute(
            "SELECT banned FROM users WHERE user_id=?", (referrer_id,)
        ).fetchone()
        if not referrer or referrer["banned"]:
            conn.execute(
                "UPDATE users SET referral_reward_paid=1,updated_at=? WHERE user_id=?",
                (int(time.time()), user_id),
            )
            conn.commit()
            return None
        reward = float(get_setting("referral_reward", DEFAULT_REFERRAL_REWARD))
        now = int(time.time())
        conn.execute(
            "UPDATE users SET balance=ROUND(balance+?,8),referral_earnings=ROUND(referral_earnings+?,8),updated_at=? WHERE user_id=?",
            (reward, reward, now, referrer_id),
        )
        conn.execute(
            "UPDATE users SET referral_reward_paid=1,updated_at=? WHERE user_id=?",
            (now, user_id),
        )
        conn.commit()
        return reward
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def save_wallet(user_id: int, wallet_type: str, wallet_number: str):
    wallet_type = wallet_type.strip().lower()
    wallet_number = wallet_number.strip()

    if wallet_type == "cbe":
        valid = bool(re.fullmatch(r"1000\d{9}", wallet_number))
        normalized = "CBE"
    elif wallet_type == "telebirr":
        valid = bool(re.fullmatch(r"(09|07)\d{8}", wallet_number))
        normalized = "Telebirr"
    else:
        return False, "Invalid wallet type", False

    if not valid:
        if normalized == "CBE":
            return False, "CBE must be 13 digits and start with 1000.", False
        return False, "Telebirr must be 10 digits and start with 09 or 07.", False

    conn = db()
    try:
        duplicate = conn.execute(
            """SELECT user_id FROM users
               WHERE wallet_type=? AND wallet_number=? AND user_id!=?""",
            (normalized, wallet_number, user_id),
        ).fetchone()
        suspicious = bool(duplicate)

        conn.execute(
            """UPDATE users SET wallet_type=?,wallet_number=?,wallet_suspicious=?,updated_at=?
               WHERE user_id=?""",
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
            conn.rollback()
            return False, "User not found."
        if user["banned"]:
            conn.rollback()
            return False, "Your account is banned."
        if not user["wallet_type"] or not user["wallet_number"]:
            conn.rollback()
            return False, "Please save your wallet first."
        minimum = float(get_setting("min_withdraw", DEFAULT_MIN_WITHDRAW))
        available = float(user["balance"])
        amount = available if requested_amount in (None, "", 0) else float(requested_amount)
        if amount < minimum:
            conn.rollback()
            return False, f"Minimum withdrawal is {minimum:.2f} ETB."
        if amount > available:
            conn.rollback()
            return False, "Insufficient balance."
        pending = conn.execute(
            "SELECT id FROM withdrawals WHERE user_id=? AND status='pending' LIMIT 1",
            (user_id,),
        ).fetchone()
        if pending:
            conn.rollback()
            return False, "You already have a pending withdrawal."

        now = int(time.time())
        cur = conn.execute(
            """INSERT INTO withdrawals
               (user_id,amount,wallet_type,wallet_number,status,suspicious,created_at)
               VALUES(?,?,?,?,?,?,?)""",
            (
                user_id,
                amount,
                user["wallet_type"],
                user["wallet_number"],
                "pending",
                int(bool(user["wallet_suspicious"])),
                now,
            ),
        )
        wid = cur.lastrowid
        conn.execute(
            "UPDATE users SET balance=ROUND(balance-?,8),updated_at=? WHERE user_id=?",
            (amount, now, user_id),
        )
        conn.commit()
        return True, {
            "withdrawal_id": wid,
            "amount": amount,
            "wallet_type": user["wallet_type"],
            "wallet_number": user["wallet_number"],
            "suspicious": bool(user["wallet_suspicious"]),
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_active_tasks(user_id: int):
    conn = db()
    try:
        rows = conn.execute(
            """SELECT t.*,
               (SELECT status FROM task_submissions s
                WHERE s.task_id=t.id AND s.user_id=?
                ORDER BY s.id DESC LIMIT 1) AS submission_status
               FROM tasks t WHERE t.active=1 ORDER BY t.id DESC""",
            (user_id,),
        ).fetchall()
        return rows
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
        task = conn.execute(
            "SELECT * FROM tasks WHERE id=? AND active=1", (task_id,)
        ).fetchone()
        if not task:
            return False, "Task not found or inactive."

        latest = conn.execute(
            """SELECT id,status FROM task_submissions
               WHERE task_id=? AND user_id=? ORDER BY id DESC LIMIT 1""",
            (task_id, user_id),
        ).fetchone()

        if latest and latest["status"] == "pending":
            return False, "Your previous submission is still pending."
        if latest and latest["status"] == "approved":
            return False, "This task is already approved."

        now = int(time.time())
        cur = conn.execute(
            """INSERT INTO task_submissions
               (task_id,user_id,proof,status,created_at)
               VALUES(?,?,?,?,?)""",
            (task_id, user_id, proof, "pending", now),
        )
        conn.commit()
        return True, {
            "submission_id": cur.lastrowid,
            "task_id": task_id,
            "user_id": user_id,
            "reward": float(task["reward"]),
            "title": task["title"],
            "proof": proof,
        }
    finally:
        conn.close()


def get_pending_submissions(limit=30):
    conn = db()
    try:
        return conn.execute(
            """SELECT s.*, t.title, t.reward, u.username, u.first_name
               FROM task_submissions s
               JOIN tasks t ON t.id=s.task_id
               JOIN users u ON u.user_id=s.user_id
               WHERE s.status='pending'
               ORDER BY s.id ASC LIMIT ?""",
            (limit,),
        ).fetchall()
    finally:
        conn.close()


def withdrawal_keyboard(withdrawal_id: int):
    return {
        "inline_keyboard": [[
            {"text": "✅ Approve", "callback_data": f"wd_approve:{withdrawal_id}"},
            {"text": "❌ Reject", "callback_data": f"wd_reject:{withdrawal_id}"},
        ], [
            {"text": "🚫 Ban User", "callback_data": f"wd_ban:{withdrawal_id}"}
        ], [
            {"text": "👥 Referral List", "callback_data": f"wd_refs:{withdrawal_id}"}
        ]]
    }


def task_keyboard(submission_id: int):
    return {
        "inline_keyboard": [[
            {"text": "✅ Approve", "callback_data": f"task_approve:{submission_id}"},
            {"text": "❌ Reject", "callback_data": f"task_reject:{submission_id}"},
        ]]
    }


def format_user(user):
    name = html.escape(user["first_name"] or user["username"] or str(user["user_id"]))
    username = f"@{html.escape(user['username'])}" if user["username"] else "No username"
    return f"{name} ({username}) — <code>{user['user_id']}</code>"


async def notify_withdrawal(wid: int):
    conn = db()
    try:
        row = conn.execute(
            """SELECT w.*,u.username,u.first_name
               FROM withdrawals w JOIN users u ON u.user_id=w.user_id
               WHERE w.id=?""",
            (wid,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return
    text = (
        "💸 <b>New Withdrawal</b>\n\n"
        f"🆔 ID: <code>{row['id']}</code>\n"
        f"👤 {format_user(row)}\n"
        f"💰 Amount: <b>{row['amount']:.2f} ETB</b>\n"
        f"🏦 Wallet: <b>{html.escape(row['wallet_type'])}</b>\n"
        f"📱 Number: <code>{html.escape(row['wallet_number'])}</code>\n"
        f"⚠️ Suspicious: {'YES' if row['suspicious'] else 'No'}"
    )
    await send_admin_message(text, withdrawal_keyboard(wid))


async def notify_task_submission(submission_id: int):
    conn = db()
    try:
        row = conn.execute(
            """SELECT s.*,t.title,t.reward,u.username,u.first_name
               FROM task_submissions s
               JOIN tasks t ON t.id=s.task_id
               JOIN users u ON u.user_id=s.user_id
               WHERE s.id=?""",
            (submission_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return
    text = (
        "📋 <b>New Task Submission</b>\n\n"
        f"🆔 Submission: <code>{row['id']}</code>\n"
        f"🎯 Task: <b>{html.escape(row['title'])}</b>\n"
        f"💰 Reward: <b>{row['reward']:.2f} ETB</b>\n"
        f"👤 {format_user(row)}\n\n"
        f"🧾 <b>Proof:</b>\n{html.escape(row['proof'])}"
    )
    await send_admin_message(text, task_keyboard(submission_id))


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


async def answer_callback(callback_id: str, text="", alert=False):
    return await telegram_request(
        "answerCallbackQuery",
        {"callback_query_id": callback_id, "text": text, "show_alert": alert},
    )


async def handle_admin_callback(query, data):
    admin_id = int(query["from"]["id"])
    if not is_admin(admin_id):
        await answer_callback(query["id"], "Not authorized.", True)
        return

    if data.startswith("wd_"):
        action, raw_id = data.split(":", 1)
        wid = int(raw_id)
        conn = db()
        try:
            row = conn.execute(
                "SELECT * FROM withdrawals WHERE id=?", (wid,)
            ).fetchone()
            if not row:
                await answer_callback(query["id"], "Withdrawal not found.", True)
                return
            if row["status"] != "pending":
                await answer_callback(query["id"], f"Already {row['status']}.", True)
                return

            now = int(time.time())
            if action == "wd_approve":
                conn.execute(
                    """UPDATE withdrawals SET status='approved',processed_at=?,processed_by=?
                       WHERE id=? AND status='pending'""",
                    (now, admin_id, wid),
                )
                status_text = "approved"
            elif action == "wd_reject":
                conn.execute(
                    """UPDATE withdrawals SET status='rejected',processed_at=?,processed_by=?
                       WHERE id=? AND status='pending'""",
                    (now, admin_id, wid),
                )
                conn.execute(
                    "UPDATE users SET balance=ROUND(balance+?,8),updated_at=? WHERE user_id=?",
                    (row["amount"], now, row["user_id"]),
                )
                status_text = "rejected and refunded"
            elif action == "wd_ban":
                conn.execute(
                    "UPDATE users SET banned=1,updated_at=? WHERE user_id=?",
                    (now, row["user_id"]),
                )
                status_text = "user banned"
            else:
                await answer_callback(query["id"], "Unknown action.", True)
                return
            conn.commit()
            await answer_callback(query["id"], f"Withdrawal {status_text}.")
            await edit_callback_message(
                query,
                f"💸 <b>Withdrawal #{wid}</b>\n\nStatus: <b>{status_text}</b>",
            )
            if action in {"wd_approve", "wd_reject"}:
                await send_message(
                    row["user_id"],
                    (
                        f"💸 <b>Withdrawal Update</b>\n\n"
                        f"Amount: <b>{row['amount']:.2f} ETB</b>\n"
                        f"Status: <b>{status_text}</b>"
                    ),
                )
            elif action == "wd_ban":
                await send_message(
                    row["user_id"],
                    "🚫 Your Falcon World account has been banned by an administrator.",
                )
        finally:
            conn.close()
        return

    if data.startswith("wd_refs:"):
        wid = int(data.split(":", 1)[1])
        conn = db()
        try:
            row = conn.execute("SELECT user_id FROM withdrawals WHERE id=?", (wid,)).fetchone()
            if not row:
                await answer_callback(query["id"], "Withdrawal not found.", True); return
            refs = conn.execute("SELECT user_id,username,first_name,verified FROM users WHERE referred_by=? ORDER BY user_id DESC", (row["user_id"],)).fetchall()
        finally:
            conn.close()
        if not refs:
            await answer_callback(query["id"], "No referrals found.", True); return
        lines=["👥 <b>Referral List</b>"]
        for r in refs:
            name=html.escape(r["first_name"] or r["username"] or str(r["user_id"]))
            uname=f"@{html.escape(r['username'])}" if r["username"] else "No username"
            lines.append(f"• {name} ({uname}) — <code>{r['user_id']}</code> — {'Verified' if r['verified'] else 'Unverified'}")
        await send_message(admin_id, "\n".join(lines))
        await answer_callback(query["id"], "Referral list sent.")
        return

    if data.startswith("task_"):
        action, raw_id = data.split(":", 1)
        sid = int(raw_id)
        conn = db()
        try:
            row = conn.execute(
                """SELECT s.*,t.title,t.reward
                   FROM task_submissions s JOIN tasks t ON t.id=s.task_id
                   WHERE s.id=?""",
                (sid,),
            ).fetchone()
            if not row:
                await answer_callback(query["id"], "Submission not found.", True)
                return
            if row["status"] != "pending":
                await answer_callback(query["id"], f"Already {row['status']}.", True)
                return

            now = int(time.time())
            if action == "task_approve":
                conn.execute(
                    """UPDATE task_submissions
                       SET status='approved',reviewed_at=?,reviewed_by=?
                       WHERE id=? AND status='pending'""",
                    (now, admin_id, sid),
                )
                conn.execute(
                    "UPDATE users SET balance=ROUND(balance+?,8),task_earnings=ROUND(task_earnings+?,8),updated_at=? WHERE user_id=?",
                    (row["reward"], row["reward"], now, row["user_id"]),
                )
                status_text = "approved"
            elif action == "task_reject":
                conn.execute(
                    """UPDATE task_submissions
                       SET status='rejected',reviewed_at=?,reviewed_by=?
                       WHERE id=? AND status='pending'""",
                    (now, admin_id, sid),
                )
                status_text = "rejected"
            else:
                await answer_callback(query["id"], "Unknown action.", True)
                return

            conn.commit()
            await answer_callback(query["id"], f"Task {status_text}.")
            await edit_callback_message(
                query,
                f"📋 <b>Task Submission #{sid}</b>\n\nStatus: <b>{status_text}</b>",
            )
            await send_message(
                row["user_id"],
                (
                    f"📋 <b>Task Update</b>\n\n"
                    f"Task: <b>{html.escape(row['title'])}</b>\n"
                    f"Status: <b>{status_text}</b>"
                    + (f"\n💰 Reward: <b>+{row['reward']:.2f} ETB</b>" if status_text == "approved" else "")
                ),
            )
        finally:
            conn.close()


async def handle_callback(query):
    data = query.get("data", "")
    if data.startswith(("wd_", "task_")):
        await handle_admin_callback(query, data)
        return

    await answer_callback(query["id"])


def parse_start_ref(text: str):
    parts = text.split(maxsplit=1)
    if len(parts) != 2:
        return None
    payload = parts[1].strip()
    if payload.startswith("ref_"):
        raw = payload[4:]
        if raw.isdigit():
            return int(raw)
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
            (
                "🦅 <b>WELCOME TO FALCON WORLD</b>\n\n"
                "💰 Earn & Complete Tasks\n"
                "🎁 Daily Rewards\n"
                "👥 Referral Rewards\n"
                "🚀 New Opportunities\n\n"
                "💱 USDT Exchange: Buy & Sell\n"
                "📢 Ads & Promotions: DM @AmanM_12\n\n"
                "🦅 <b>Tap the Falcon World button below to get started.</b>"
            ),
        )
        return

    # The Mini App is the user interface. Do not create a second normal-chat menu.
    if not is_admin(user_id) and not text.startswith("/"):
        return

    if text == "💰 Balance":
        row = get_user(user_id)
        await send_message(chat_id, f"💰 <b>Your Balance</b>\n\n<b>{row['balance']:.2f} ETB</b>", main_keyboard())
        return

    if text == "🎁 Daily Bonus":
        ok, result = claim_daily_bonus(user_id)
        if ok:
            await send_message(
                chat_id,
                f"🎁 <b>Daily Bonus Claimed!</b>\n\n+{result['reward']:.2f} ETB\n💰 Balance: {result['balance']:.2f} ETB",
                main_keyboard(),
            )
        elif result["error"] == "cooldown":
            hours = result["remaining"] // 3600
            minutes = (result["remaining"] % 3600) // 60
            await send_message(chat_id, f"⏳ Daily bonus already claimed.\nTry again in {hours}h {minutes}m.", main_keyboard())
        elif result["error"] == "not_verified":
            await send_message(chat_id, "⚠️ Please verify all required channels in Falcon World first.", main_keyboard())
        else:
            await send_message(chat_id, "❌ Daily bonus could not be claimed.", main_keyboard())
        return

    if text == "👥 Invite Friends":
        link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"
        count = get_referral_count(user_id)
        reward = get_setting("referral_reward", DEFAULT_REFERRAL_REWARD)
        await send_message(
            chat_id,
            f"👥 <b>Invite Friends</b>\n\n"
            f"Invite link:\n<code>{html.escape(link)}</code>\n\n"
            f"👤 Successful referrals: <b>{count}</b>\n"
            f"💰 Reward: <b>{reward:.2f} ETB</b> each\n\n"
            "Reward is credited after the invited user completes verification.",
            main_keyboard(),
        )
        return

    if text == "💳 Wallet Settings":
        row = get_user(user_id)
        wallet = "Not set"
        if row["wallet_type"] and row["wallet_number"]:
            wallet = f"{html.escape(row['wallet_type'])}: <code>{html.escape(row['wallet_number'])}</code>"
        await send_message(
            chat_id,
            f"💳 <b>Wallet Settings</b>\n\nCurrent: {wallet}\n\n"
            "Use the Mini App to save CBE or Telebirr.",
            main_keyboard(),
        )
        return

    if text == "💸 Withdraw":
        row = get_user(user_id)
        minimum = get_setting("min_withdraw", DEFAULT_MIN_WITHDRAW)
        await send_message(
            chat_id,
            f"💸 <b>Withdraw</b>\n\n"
            f"Balance: <b>{row['balance']:.2f} ETB</b>\n"
            f"Minimum: <b>{minimum:.2f} ETB</b>\n\n"
            "Use the Mini App to submit a withdrawal.",
            main_keyboard(),
        )
        return

    if text == "📋 Tasks":
        tasks = get_active_tasks(user_id)
        if not tasks:
            await send_message(chat_id, "📋 No active tasks right now.", main_keyboard())
            return
        lines = ["📋 <b>Active Tasks</b>\n"]
        for task in tasks[:10]:
            status = task["submission_status"] or "not submitted"
            lines.append(
                f"#{task['id']} <b>{html.escape(task['title'])}</b>\n"
                f"💰 {task['reward']:.2f} ETB • Status: {html.escape(status)}"
            )
        lines.append("\n🚀 Open the Mini App to complete and submit tasks.")
        await send_message(chat_id, "\n\n".join(lines), main_keyboard())
        return

    if text == "❓ Help":
        await send_message(
            chat_id,
            "❓ <b>Help</b>\n\n"
            "1. Join all required channels.\n"
            "2. Verify your account.\n"
            "3. Complete tasks and daily bonus.\n"
            "4. Save CBE or Telebirr.\n"
            "5. Withdraw when you reach the minimum.\n\n"
            "Use /start to open Falcon World.",
            main_keyboard(),
        )
        return

    if text == "🆘 Support":
        await send_message(
            chat_id,
            "🆘 <b>Support</b>\n\nFor support, contact the Falcon World administrator.",
            main_keyboard(),
        )
        return

    if text.startswith("/admin") and is_admin(user_id):
        await admin_dashboard(chat_id)
        return

    if text.startswith("/checkuser ") and is_admin(user_id):
        raw = text.split(maxsplit=1)[1].strip()
        if not raw.isdigit():
            await send_message(chat_id, "Usage: /checkuser USER_ID")
            return
        target = get_user(int(raw))
        if not target:
            await send_message(chat_id, "User not found.")
            return
        await send_message(
            chat_id,
            f"👤 <b>User</b>\n\n"
            f"ID: <code>{target['user_id']}</code>\n"
            f"Name: {html.escape(target['first_name'] or '')}\n"
            f"Username: @{html.escape(target['username'] or 'none')}\n"
            f"Balance: <b>{target['balance']:.2f} ETB</b>\n"
            f"Verified: {bool(target['verified'])}\n"
            f"Banned: {bool(target['banned'])}\n"
            f"Wallet: {html.escape(target['wallet_type'] or 'none')} / <code>{html.escape(target['wallet_number'] or 'none')}</code>\n"
            f"Suspicious wallet: {bool(target['wallet_suspicious'])}",
        )
        return

    if text.startswith("/addbalance ") and is_admin(user_id):
        parts = text.split()
        if len(parts) != 3 or not parts[1].isdigit():
            await send_message(chat_id, "Usage: /addbalance USER_ID AMOUNT")
            return
        target_id = int(parts[1])
        amount = float(parts[2])
        if not get_user(target_id):
            await send_message(chat_id, "User not found.")
            return
        add_balance(target_id, amount)
        await send_message(chat_id, f"✅ Added {amount:.2f} ETB to {target_id}.")
        await send_message(target_id, f"💰 Admin balance adjustment: <b>+{amount:.2f} ETB</b>")
        return

    if text.startswith("/ban ") and is_admin(user_id):
        raw = text.split(maxsplit=1)[1].strip()
        if not raw.isdigit():
            await send_message(chat_id, "Usage: /ban USER_ID")
            return
        conn = db()
        try:
            conn.execute("UPDATE users SET banned=1,updated_at=? WHERE user_id=?", (int(time.time()), int(raw)))
            conn.commit()
        finally:
            conn.close()
        await send_message(chat_id, "🚫 User banned.")
        return

    if text.startswith("/unban ") and is_admin(user_id):
        raw = text.split(maxsplit=1)[1].strip()
        if not raw.isdigit():
            await send_message(chat_id, "Usage: /unban USER_ID")
            return
        conn = db()
        try:
            conn.execute("UPDATE users SET banned=0,updated_at=? WHERE user_id=?", (int(time.time()), int(raw)))
            conn.commit()
        finally:
            conn.close()
        await send_message(chat_id, "✅ User unbanned.")
        return

    if text.startswith("/setminwithdraw ") and is_admin(user_id):
        value = float(text.split(maxsplit=1)[1])
        set_setting("min_withdraw", value)
        await send_message(chat_id, f"✅ Minimum withdrawal set to {value:.2f} ETB.")
        return

    if text.startswith("/setdaily ") and is_admin(user_id):
        value = float(text.split(maxsplit=1)[1])
        set_setting("daily_bonus", value)
        await send_message(chat_id, f"✅ Daily bonus set to {value:.2f} ETB.")
        return

    if text.startswith("/setref ") and is_admin(user_id):
        value = float(text.split(maxsplit=1)[1])
        set_setting("referral_reward", value)
        await send_message(chat_id, f"✅ Referral reward set to {value:.2f} ETB.")
        return

    if text == "/channels" and is_admin(user_id):
        channels = get_required_channels()
        if not channels:
            await send_message(chat_id, "No required channels configured.")
        else:
            lines = ["📣 <b>Required Channels</b>"]
            for i, c in enumerate(channels, 1):
                lines.append(f"{i}. <b>{html.escape(c['name'])}</b> — {html.escape(c['username'])}\n{html.escape(c['url'])}")
            lines.append("\n/addchannel @username | Name | https://t.me/username\n/removechannel @username\n/editchannel @old | @new | Name | https://t.me/new")
            await send_message(chat_id, "\n\n".join(lines))
        return

    if text.startswith("/addchannel ") and is_admin(user_id):
        parts = [x.strip() for x in text.split("|", 2)]
        if len(parts) != 3:
            await send_message(chat_id, "Usage: /addchannel @username | Name | https://t.me/username")
            return
        username, name, url = parts
        if not username.startswith("@"):
            username = "@" + username
        conn = db()
        try:
            conn.execute("INSERT INTO required_channels(username,name,url,active,created_at) VALUES(?,?,?,?,?)", (username,name,url,1,int(time.time())))
            conn.commit()
        except sqlite3.IntegrityError:
            await send_message(chat_id, "❌ That channel is already configured.")
            return
        finally:
            conn.close()
        await send_message(chat_id, f"✅ Channel added: {html.escape(username)}")
        return

    if text.startswith("/removechannel ") and is_admin(user_id):
        username = text.split(maxsplit=1)[1].strip()
        if not username.startswith("@"):
            username = "@" + username
        conn = db()
        try:
            cur = conn.execute("DELETE FROM required_channels WHERE username=?", (username,))
            conn.commit()
        finally:
            conn.close()
        await send_message(chat_id, "✅ Channel removed." if cur.rowcount else "❌ Channel not found.")
        return

    if text.startswith("/editchannel ") and is_admin(user_id):
        parts = [x.strip() for x in text.split("|", 3)]
        if len(parts) != 4:
            await send_message(chat_id, "Usage: /editchannel @old | @new | Name | https://t.me/new")
            return
        old, new, name, url = parts
        if not old.startswith("@"): old = "@" + old
        if not new.startswith("@"): new = "@" + new
        conn = db()
        try:
            cur = conn.execute("UPDATE required_channels SET username=?,name=?,url=? WHERE username=?", (new,name,url,old))
            conn.commit()
        finally:
            conn.close()
        await send_message(chat_id, "✅ Channel updated." if cur.rowcount else "❌ Channel not found.")
        return

    if text.startswith("/addtask ") and is_admin(user_id):
        parts = text.split("|", 3)
        if len(parts) != 4:
            await send_message(chat_id, "Usage: /addtask TITLE|DESCRIPTION|REWARD|URL")
            return
        title, description, reward, url = [x.strip() for x in parts]
        try:
            reward = float(reward)
        except ValueError:
            await send_message(chat_id, "Reward must be a number.")
            return
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
        await send_message(chat_id, f"✅ Task #{task_id} created.")
        return

    await send_message(
        chat_id,
        "Use the buttons below or open Falcon World 🚀",
        main_keyboard(),
    )


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

    await send_message(
        chat_id,
        f"🛠 <b>Falcon World Admin</b>\n\n"
        f"👥 Users: <b>{users}</b>\n"
        f"✅ Verified: <b>{verified}</b>\n"
        f"🚫 Banned: <b>{banned}</b>\n"
        f"💰 User balances: <b>{total_balance:.2f} ETB</b>\n"
        f"💸 Pending withdrawals: <b>{pending_wd}</b>\n"
        f"📋 Pending tasks: <b>{pending_tasks}</b>\n\n"
        "<b>Commands</b>\n"
        "/checkuser USER_ID\n"
        "/addbalance USER_ID AMOUNT\n"
        "/ban USER_ID\n"
        "/unban USER_ID\n"
        "/addtask TITLE|DESCRIPTION|REWARD|URL\n"
        "/setminwithdraw AMOUNT\n"
        "/setdaily AMOUNT\n"
        "/setref AMOUNT",
    )


async def handle_update(update: dict):
    if "callback_query" in update:
        await handle_callback(update["callback_query"])
        return

    message = update.get("message")
    if message:
        await handle_message(message)


WEBHOOK_URL = os.getenv(
    "WEBHOOK_URL",
    "https://falcon-world.onrender.com/webhook"
).strip()

# MINI_APP_URL is already defined above by the bot section.
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()

app = FastAPI(title="Falcon World")


def validate_init_data(init_data: str):
    if not init_data or not BOT_TOKEN:
        return None
    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = parsed.pop("hash", None)
        if not received_hash:
            return None

        data_check_string = "\n".join(
            f"{key}={parsed[key]}" for key in sorted(parsed.keys())
        )

        secret_key = hmac.new(
            b"WebAppData",
            BOT_TOKEN.encode(),
            hashlib.sha256,
        ).digest()

        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(calculated_hash, received_hash):
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


def get_required_channels():
    conn = db()
    try:
        rows = conn.execute("SELECT username,name,url FROM required_channels WHERE active=1 ORDER BY id ASC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


async def check_channel_membership(user_id: int, channel_username: str):
    result = await telegram_request(
        "getChatMember",
        {"chat_id": channel_username, "user_id": user_id},
    )

    if not result.get("ok"):
        return False

    member = result.get("result", {})
    status = member.get("status")

    if status in {"member", "administrator", "creator"}:
        return True

    if status == "restricted" and member.get("is_member") is True:
        return True

    return False


async def check_all_channels(user_id: int):
    async def check(channel):
        joined = await check_channel_membership(
            user_id,
            channel["username"],
        )
        return {**channel, "joined": joined}

    channels = get_required_channels()
    results = await asyncio.gather(*(check(ch) for ch in channels))
    verified_count = sum(1 for channel in results if channel["joined"])
    verified = verified_count == len(channels)
    return {
        "verified": verified,
        "verified_count": verified_count,
        "total": len(channels),
        "channels": results,
    }


async def require_user(request: Request):
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    user = validate_init_data(init_data)

    if not user:
        return None, JSONResponse(
            {"error": "telegram_required"},
            status_code=401,
        )

    user_id = int(user["id"])

    if is_banned(user_id):
        return None, JSONResponse(
            {"error": "banned"},
            status_code=403,
        )

    return user, None


@app.get("/")
async def home():
    return {
        "status": "online",
        "app": "Falcon World",
    }


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "app": "falcon-world",
    }



@app.get("/falcon-bg.webp")
async def falcon_background():
    if os.path.exists(FALCON_BG_PATH):
        return FileResponse(FALCON_BG_PATH, media_type="image/webp", headers={"Cache-Control": "public, max-age=86400"})
    return JSONResponse({"error": "background_not_found"}, status_code=404)

@app.get("/app", response_class=HTMLResponse)
async def mini_app():
    html = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
<meta name="theme-color" content="#07101f">
<title>Falcon World</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root{--bg:#020817;--panel:rgba(7,20,39,.74);--panel2:rgba(5,16,33,.82);--line:rgba(91,174,255,.26);--text:#f7fbff;--muted:#9bb0c9;--blue:#21a7ff;--blue2:#1767ff;--gold:#ffbf2f;--green:#35e7a4;--danger:#ff5f7a;--r:24px}
*{box-sizing:border-box}html,body{margin:0;background:#020817;color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;-webkit-font-smoothing:antialiased}body{min-height:100vh;overflow-x:hidden;background:#020817 url('data:image/webp;base64,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
Preview truncated for large file
