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
from fastapi.responses import HTMLResponse, JSONResponse

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
:root{--bg:#050a13;--panel:#0b1423;--panel2:#101d30;--line:rgba(255,255,255,.09);--text:#f6f8fb;--muted:#8fa1b8;--accent:#4da3ff;--accent2:#7b61ff;--good:#45e39b;--warn:#ffcc66;--danger:#ff6b7a;--r:22px}
*{box-sizing:border-box}html,body{margin:0;background:var(--bg);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;-webkit-font-smoothing:antialiased}body{min-height:100vh;overflow-x:hidden}
body:before{content:"";position:fixed;inset:0;pointer-events:none;background:radial-gradient(circle at 15% 0%,rgba(77,163,255,.14),transparent 34%),radial-gradient(circle at 90% 15%,rgba(123,97,255,.12),transparent 32%),linear-gradient(180deg,#08111f 0%,#050a13 58%);z-index:-2}
body:after{content:"";position:fixed;inset:0;pointer-events:none;opacity:.28;background-image:radial-gradient(rgba(255,255,255,.18) .6px,transparent .6px);background-size:18px 18px;mask-image:linear-gradient(to bottom,black,transparent 75%);z-index:-1}
button,input,textarea{font:inherit}button{border:0;color:inherit;cursor:pointer}.app{max-width:520px;margin:auto;padding:calc(16px + env(safe-area-inset-top)) 16px calc(92px + env(safe-area-inset-bottom))}.hidden{display:none!important}.fade{animation:fade .28s ease}@keyframes fade{from{opacity:0;transform:translateY(7px)}to{opacity:1;transform:none}}
.splash{position:fixed;inset:0;z-index:50;display:flex;align-items:center;justify-content:center;background:#050a13}.splashInner{text-align:center}.falcon svg{width:72px;height:72px;filter:drop-shadow(0 0 18px rgba(77,163,255,.35))}.falcon{width:112px;height:112px;margin:auto;border-radius:34px;display:grid;place-items:center;font-size:62px;color:#8fc7ff;background:linear-gradient(145deg,#10233c,#0b1220);border:1px solid rgba(255,255,255,.1);box-shadow:0 0 80px rgba(77,163,255,.18),inset 0 1px rgba(255,255,255,.08)}.splash h1{margin:20px 0 5px;font-size:30px;letter-spacing:-.8px}.splash p{margin:0;color:var(--muted);font-size:13px}.loader{width:190px;height:4px;background:#182438;border-radius:99px;overflow:hidden;margin:24px auto 0}.loader i{display:block;width:45%;height:100%;background:linear-gradient(90deg,var(--accent),var(--accent2));animation:load 1.1s infinite}@keyframes load{0%{transform:translateX(-120%)}100%{transform:translateX(330%)}}
.top{display:flex;align-items:center;justify-content:space-between;margin-bottom:18px}.brand{display:flex;align-items:center;gap:10px}.brandIcon{width:42px;height:42px;border-radius:14px;display:grid;place-items:center;background:linear-gradient(145deg,#132c49,#0d1728);border:1px solid var(--line);font-size:23px}.brandText b{display:block;font-size:16px}.brandText span{font-size:11px;color:var(--muted)}.pill{padding:8px 11px;border:1px solid var(--line);border-radius:999px;background:rgba(255,255,255,.035);font-size:11px;color:#b9c8da}
.page{display:none}.page.active{display:block}.hero{position:relative;overflow:hidden;padding:22px;border-radius:28px;background:linear-gradient(145deg,rgba(17,36,61,.98),rgba(8,17,30,.98));border:1px solid rgba(255,255,255,.1);box-shadow:0 20px 55px rgba(0,0,0,.28)}.hero:after{content:"";position:absolute;width:180px;height:180px;right:-75px;top:-75px;border-radius:50%;background:rgba(77,163,255,.16);filter:blur(12px)}.eyebrow{font-size:11px;color:#9bb1ca;text-transform:uppercase;letter-spacing:1.4px}.bigBalance{font-size:40px;line-height:1;margin:9px 0 6px;font-weight:850;letter-spacing:-1.4px}.heroSub{font-size:12px;color:var(--muted)}
.sectionTitle{display:flex;justify-content:space-between;align-items:end;margin:22px 2px 11px}.sectionTitle h2{font-size:17px;margin:0}.sectionTitle span{font-size:11px;color:var(--muted)}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:11px}.action{min-height:92px;text-align:left;padding:16px;border-radius:20px;background:linear-gradient(145deg,#0e1b2d,#091321);border:1px solid var(--line);box-shadow:0 10px 25px rgba(0,0,0,.14);transition:.18s}.action:active{transform:scale(.98)}.ico{font-size:22px;margin-bottom:14px}.action b{display:block;font-size:14px}.action small{display:block;margin-top:3px;color:var(--muted);font-size:10px}
.card{padding:18px;border-radius:var(--r);background:rgba(11,20,35,.88);border:1px solid var(--line);box-shadow:0 15px 38px rgba(0,0,0,.18);margin-bottom:12px}.statGrid{display:grid;grid-template-columns:1fr 1fr;gap:9px}.stat{padding:14px;border-radius:17px;background:rgba(255,255,255,.035);border:1px solid var(--line)}.stat span{display:block;color:var(--muted);font-size:10px;margin-bottom:6px}.stat b{font-size:15px}.money{font-weight:800}.muted{color:var(--muted);font-size:12px;line-height:1.55}.back{background:transparent;color:#a9bdd4;padding:8px 0;font-size:13px;margin-bottom:12px}.primary{width:100%;padding:14px;border-radius:16px;background:linear-gradient(135deg,#3f9dff,#6c70ff);font-weight:800;box-shadow:0 10px 28px rgba(77,163,255,.2);margin-top:10px}.secondary{width:100%;padding:13px;border-radius:16px;background:#0b1727;border:1px solid var(--line);font-weight:700;margin-top:9px}.danger{background:rgba(255,107,122,.08);border-color:rgba(255,107,122,.22)}
.field{margin-top:12px}.field label{font-size:11px;color:#a7b7ca}.field input,.field textarea,.field select{width:100%;margin-top:7px;padding:14px;border-radius:14px;border:1px solid var(--line);background:#07111e;color:#fff;outline:none}.field textarea{min-height:110px;resize:none}.field input:focus,.field textarea:focus,.field select:focus{border-color:rgba(77,163,255,.7)}
.notice{padding:12px 13px;border-radius:14px;font-size:12px;margin-top:10px}.ok{background:rgba(69,227,155,.08);border:1px solid rgba(69,227,155,.2);color:#8af0bc}.warn{background:rgba(255,204,102,.08);border:1px solid rgba(255,204,102,.2);color:#ffd98a}.err{background:rgba(255,107,122,.08);border:1px solid rgba(255,107,122,.2);color:#ff9ca7}
.channel{display:flex;align-items:center;gap:12px;padding:13px;margin:9px 0;border-radius:16px;background:#081321;border:1px solid var(--line)}.channelIcon{width:38px;height:38px;border-radius:12px;display:grid;place-items:center;background:#10253e}.channelMain{flex:1}.channelMain b{display:block;font-size:13px}.channelMain span{font-size:10px;color:var(--muted)}.join{padding:9px 11px;border-radius:11px;background:#153a60;color:#8fc7ff;font-size:11px;font-weight:800}.joined{font-size:11px;color:var(--good);font-weight:800}
.task{padding:15px;border-radius:18px;background:linear-gradient(145deg,#0d1b2d,#08121f);border:1px solid var(--line);margin:10px 0}.taskTop{display:flex;justify-content:space-between;gap:10px}.task h3{margin:0;font-size:14px}.reward{color:#79b9ff;font-weight:800;font-size:12px;white-space:nowrap}.task p{color:var(--muted);font-size:11px;line-height:1.5}.task a{color:#83bfff;text-decoration:none}.taskStatus{font-size:10px;color:#a9bbcf}.task textarea{width:100%;padding:12px;border-radius:12px;background:#07111e;border:1px solid var(--line);color:#fff;margin-top:8px;min-height:80px}
.walletChoice{display:grid;grid-template-columns:1fr 1fr;gap:10px}.walletBtn{padding:18px 12px;border-radius:18px;background:#081321;border:1px solid var(--line);text-align:left}.walletBtn.active{border-color:rgba(77,163,255,.65);background:linear-gradient(145deg,#102845,#0a1728)}.walletBtn b{display:block;margin-top:8px}.walletBtn small{color:var(--muted);font-size:10px}.mask{font-family:monospace;letter-spacing:1px;color:#bcd0e8}.copyBox{display:flex;gap:8px}.copyBox input{flex:1}.copyBox button{width:52px;border-radius:14px;background:#12263d;border:1px solid var(--line)}
.nav{position:fixed;left:50%;bottom:10px;transform:translateX(-50%);width:min(488px,calc(100% - 22px));display:grid;grid-template-columns:repeat(4,1fr);padding:7px;border-radius:22px;background:rgba(7,15,26,.88);backdrop-filter:blur(20px);border:1px solid rgba(255,255,255,.09);z-index:20}.nav button{background:transparent;padding:8px 3px;border-radius:15px;color:#7f92a9;font-size:10px}.nav button.active{background:#13263d;color:#fff}.nav i{font-style:normal;display:block;font-size:18px;margin-bottom:2px}
@media(max-width:360px){.grid{gap:8px}.action{padding:13px}.bigBalance{font-size:35px}}
</style>
</head>
<body>
<div class="splash" id="splash"><div class="splashInner"><div class="falcon"><svg viewBox="0 0 120 120" aria-hidden="true"><path d="M15 70c18-7 28-19 38-39 9 8 18 13 31 15 9 1 17 6 21 14-14-5-26-2-38 7-12 9-27 13-52 3z" fill="none" stroke="currentColor" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/><path d="M43 76c10 2 20 1 29-5M51 53c6 8 12 12 21 14M72 42l10 13" fill="none" stroke="currentColor" stroke-width="4" stroke-linecap="round"/></svg></div><h1>Falcon World</h1><p>Securely loading your account</p><div class="loader"><i></i></div></div></div>
<div class="app" id="app">
  <div class="top"><div class="brand"><div class="brandIcon">🦅</div><div class="brandText"><b>Falcon World</b><span>Earn • Grow • Withdraw</span></div></div><div class="pill" id="userPill">Online</div></div>

  <section id="verifyPage" class="page active fade">
    <div class="hero"><div class="eyebrow">Secure access</div><div style="font-size:25px;font-weight:850;margin-top:7px">Human verification</div><div class="muted" style="margin-top:7px">Complete the quick check before entering Falcon World.</div></div>
    <div class="card" id="captchaCard" style="margin-top:12px"><div class="eyebrow">Step 1 of 2</div><h2 style="margin:7px 0;font-size:18px">Quick verification</h2><div id="captchaQuestion" style="font-size:24px;font-weight:850;margin:16px 0">Loading…</div><div class="field"><label>Your answer</label><input id="captchaAnswer" inputmode="numeric" placeholder="Enter answer"></div><button class="primary" onclick="verifyCaptcha()">Verify & Continue</button><div id="captchaMsg"></div></div>
    <div class="card hidden" id="channelsCard"><div class="eyebrow">Step 2 of 2</div><h2 style="margin:7px 0;font-size:18px">Required channels</h2><div class="muted">Join every required channel, then verify membership.</div><div id="channels" style="margin-top:12px"></div><button class="primary" onclick="verifyMembership()">✓ Verify Membership</button><div id="verifyMsg"></div></div>
  </section>

  <section id="home" class="page">
    <div class="hero"><div class="eyebrow">Total balance</div><div class="bigBalance" id="balance">0.00 ETB</div><div class="heroSub">Available for your next withdrawal</div></div>
    <div class="sectionTitle"><h2>Quick actions</h2><span>7 features</span></div>
    <div class="grid">
      <button class="action" onclick="go('balancePage')"><div class="ico">💰</div><b>Balance</b><small>View earnings</small></button>
      <button class="action" onclick="go('referral')"><div class="ico">👥</div><b>Referral</b><small>Invite & earn</small></button>
      <button class="action" onclick="go('daily')"><div class="ico">🎁</div><b>Daily Bonus</b><small>Claim every day</small></button>
      <button class="action" onclick="go('wallet')"><div class="ico">💳</div><b>Wallet</b><small>CBE / Telebirr</small></button>
      <button class="action" onclick="go('tasks')"><div class="ico">📋</div><b>Tasks</b><small>Earn rewards</small></button>
      <button class="action" onclick="go('withdraw')"><div class="ico">💸</div><b>Withdraw</b><small>Request payout</small></button>
      <button class="action" onclick="go('support')"><div class="ico">🆘</div><b>Support</b><small>Get assistance</small></button>
    </div>
    <div class="sectionTitle"><h2>Account</h2><span id="homeStatus">Verified</span></div>
    <div class="card"><div class="statGrid"><div class="stat"><span>USER ID</span><b id="homeId">—</b></div><div class="stat"><span>WALLET</span><b id="homeWallet">Not set</b></div></div></div>
  </section>

  <section id="balancePage" class="page"><button class="back" onclick="go('home')">← Back to Home</button><div class="hero"><div class="eyebrow">Total balance</div><div class="bigBalance" id="balance2">0.00 ETB</div><div class="heroSub">Your earnings at a glance</div></div><div class="sectionTitle"><h2>Earnings breakdown</h2></div><div class="statGrid"><div class="stat"><span>REFERRAL EARNINGS</span><b id="refEarn">0.00 ETB</b></div><div class="stat"><span>DAILY BONUS</span><b id="dailyEarn">0.00 ETB</b></div><div class="stat"><span>TASK EARNINGS</span><b id="taskEarn">0.00 ETB</b></div><div class="stat"><span>TOTAL EARNED</span><b id="totalEarn">0.00 ETB</b></div><div class="stat"><span>TOTAL WITHDRAWN</span><b id="totalWithdrawn">0.00 ETB</b></div><div class="stat"><span>PENDING WITHDRAWAL</span><b id="pendingWithdraw">0.00 ETB</b></div></div></section>

  <section id="referral" class="page"><button class="back" onclick="go('home')">← Back to Home</button><div class="hero"><div class="eyebrow">Referral program</div><div style="font-size:25px;font-weight:850;margin-top:7px">Invite friends & earn</div><div class="muted" style="margin-top:7px">You earn when your invited user completes verification.</div></div><div class="card" style="margin-top:12px"><div class="statGrid"><div class="stat"><span>INVITED USERS</span><b id="refCount">0</b></div><div class="stat"><span>REWARD / REFERRAL</span><b id="refReward">2.00 ETB</b></div><div class="stat"><span>REFERRAL EARNINGS</span><b id="refPageEarn">0.00 ETB</b></div></div><div class="field"><label>Your referral link</label><div class="copyBox"><input id="refLink" readonly><button onclick="copyReferral()">⧉</button></div></div><button class="primary" onclick="shareReferral()">↗ Share Referral Link</button><div id="refMsg"></div></div></section>

  <section id="daily" class="page"><button class="back" onclick="go('home')">← Back to Home</button><div class="hero"><div class="eyebrow">Daily reward</div><div style="font-size:25px;font-weight:850;margin-top:7px">+<span id="dailyReward">0.50</span> ETB</div><div class="muted" style="margin-top:7px">One claim per Gregorian calendar date.</div></div><div class="card" style="margin-top:12px"><div class="statGrid"><div class="stat"><span>TODAY</span><b id="todayDate">—</b></div><div class="stat"><span>NEXT CLAIM</span><b id="nextClaim">Available</b></div></div><button class="primary" id="claimBtn" onclick="claimDaily()">🎁 Claim Daily Bonus</button><div id="dailyMsg"></div></div></section>

  <section id="wallet" class="page"><button class="back" onclick="go('home')">← Back to Home</button><div class="hero"><div class="eyebrow">Withdrawal wallet</div><div style="font-size:25px;font-weight:850;margin-top:7px">Connect your wallet</div><div class="muted" style="margin-top:7px">Use a valid CBE or Telebirr number for payouts.</div></div><div class="card" style="margin-top:12px"><div class="walletChoice"><button id="cbeBtn" class="walletBtn" onclick="selectWallet('CBE')">🔵<b>CBE</b><small>13 digits • starts with 1000</small></button><button id="teleBtn" class="walletBtn" onclick="selectWallet('Telebirr')">🟢<b>Telebirr</b><small>10 digits • starts 09 / 07</small></button></div><div class="field"><label>Wallet number</label><input id="walletNumber" inputmode="numeric" maxlength="13" placeholder="Enter wallet number"></div><button class="primary" onclick="saveWallet()">Save Wallet</button><div id="walletMsg"></div><div id="savedWallet" style="margin-top:14px"></div></div></section>

  <section id="tasks" class="page"><button class="back" onclick="go('home')">← Back to Home</button><div class="hero"><div class="eyebrow">Earn more</div><div style="font-size:25px;font-weight:850;margin-top:7px">Active tasks</div><div class="muted" style="margin-top:7px">New opportunities appear here when they are added.</div></div><div id="tasksList" class="card" style="margin-top:12px">Loading…</div></section>

  <section id="withdraw" class="page"><button class="back" onclick="go('home')">← Back to Home</button><div class="hero"><div class="eyebrow">Payout</div><div style="font-size:25px;font-weight:850;margin-top:7px">Withdraw earnings</div><div class="muted" style="margin-top:7px">Minimum withdrawal: <b id="minWithdraw">30.00 ETB</b></div></div><div class="card" style="margin-top:12px"><div class="statGrid"><div class="stat"><span>AVAILABLE</span><b id="withdrawBalance">0.00 ETB</b></div><div class="stat"><span>WALLET</span><b id="withdrawWallet">Not set</b></div></div><div class="field"><label>Withdrawal amount</label><input id="withdrawAmount" inputmode="decimal" placeholder="Enter amount"></div><button class="primary" onclick="withdraw()">💸 Request Withdrawal</button><div id="withdrawMsg"></div></div></section>

  <section id="support" class="page"><button class="back" onclick="go('home')">← Back to Home</button><div class="hero"><div class="eyebrow">Support & services</div><div style="font-size:25px;font-weight:850;margin-top:7px">How can we help?</div><div class="muted" style="margin-top:7px">For advertising, promotion or growth services, contact us directly.</div></div><div class="card" style="margin-top:12px"><div class="statGrid"><div class="stat"><span>SERVICE</span><b>Telegram Channel Growth</b></div><div class="stat"><span>SERVICE</span><b>Telegram Group Growth</b></div><div class="stat"><span>SERVICE</span><b>Social Media Growth</b></div><div class="stat"><span>SERVICE</span><b>Advertising</b></div><div class="stat"><span>SERVICE</span><b>Promotion</b></div><div class="stat"><span>SERVICE</span><b>Digital Marketing</b></div><div class="stat"><span>SERVICE</span><b>Social Media Account Promotion</b></div><div class="stat"><span>SERVICE</span><b>Channel / Group Promotion</b></div></div><button class="primary" onclick="openSupport()">🆘 Contact @AmanM_12</button></div></section>
</div>
<div class="nav" id="nav"><button id="navHome" onclick="go('home')"><i>⌂</i>Home</button><button onclick="go('balancePage')"><i>◈</i>Balance</button><button onclick="go('referral')"><i>♧</i>Referral</button><button onclick="go('support')"><i>?</i>Support</button></div>
<script>
const tg=window.Telegram?.WebApp; if(tg){tg.ready();tg.expand();try{tg.setHeaderColor('#07101f');tg.setBackgroundColor('#050a13')}catch(e){}}
const initData=tg?.initData||''; const headers={'Content-Type':'application/json','X-Telegram-Init-Data':initData}; let userData=null; let walletType='CBE'; let captchaToken='';
function esc(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}
async function api(url,options={}){const r=await fetch(url,{...options,headers:{...headers,...(options.headers||{})}});let d={};try{d=await r.json()}catch(e){}if(!r.ok)throw new Error(d.error||'Request failed');return d}
function setPage(id){document.querySelectorAll('.page').forEach(x=>x.classList.remove('active'));document.getElementById(id)?.classList.add('active');document.getElementById(id)?.classList.add('fade');window.scrollTo({top:0,behavior:'smooth'});document.getElementById('nav').style.display=id==='verifyPage'?'none':'grid';['navHome'].forEach(x=>document.getElementById(x)?.classList.toggle('active',id==='home'))}
function go(id){setPage(id);if(id==='home'||id==='balancePage'||id==='withdraw')loadMe();if(id==='balancePage')loadMe();if(id==='referral')loadReferral();if(id==='daily')loadDaily();if(id==='wallet')renderWallet();if(id==='tasks')loadTasks()}
function openLink(url){if(tg?.openTelegramLink)tg.openTelegramLink(url);else window.open(url,'_blank')}
async function start(){try{tg?.ready?.();tg?.expand?.();const me=await api('/api/me');userData=me;if(me.verified){setPage('home');loadMe()}else{setPage('verifyPage');await loadCaptcha()}}catch(e){setPage('verifyPage');const msg=document.getElementById('captchaMsg');if(e.message==='telegram_required'){msg.innerHTML='<div class="notice warn">Open Falcon World from Telegram to continue.</div>'}else{await loadCaptcha()}}}
async function loadCaptcha(){try{const d=await api('/api/captcha');captchaToken=d.token;document.getElementById('captchaQuestion').textContent=d.question;document.getElementById('captchaAnswer').value='';document.getElementById('captchaAnswer').focus()}catch(e){document.getElementById('captchaMsg').innerHTML='<div class="notice err">'+esc(e.message)+'</div>'}}
async function verifyCaptcha(){const msg=document.getElementById('captchaMsg');try{const d=await api('/api/captcha/verify',{method:'POST',body:JSON.stringify({token:captchaToken,answer:document.getElementById('captchaAnswer').value})});if(d.ok){document.getElementById('captchaCard').classList.add('hidden');document.getElementById('channelsCard').classList.remove('hidden');await renderChannels()}else msg.innerHTML='<div class="notice err">Incorrect answer. Please try again.</div>'}catch(e){msg.innerHTML='<div class="notice err">'+esc(e.message)+'</div>';await loadCaptcha()}}
async function renderChannels(){const box=document.getElementById('channels');box.innerHTML='Loading…';try{const d=await api('/api/verify');const missing=d.channels.filter(x=>!x.joined);const joined=d.verified_count||0;const total=d.total||d.channels.length;let html='<div class="notice warn">'+joined+'/'+total+' channels joined</div>';html+=missing.map((ch,i)=>`<div class="channel"><div class="channelIcon">📣</div><div class="channelMain"><b>${esc(ch.name)}</b><span>${esc(ch.username)}</span></div><button class="join" data-url="${esc(ch.url)}" onclick="openLink(this.dataset.url)">Join</button></div>`).join('');if(!missing.length)html+='<div class="notice ok">All required channels appear joined. Tap Verify Membership.</div>';box.innerHTML=html}catch(e){box.innerHTML='<div class="notice err">'+esc(e.message)+'</div>'}}
async function verifyMembership(){const msg=document.getElementById('verifyMsg');msg.innerHTML='<div class="notice warn">Checking membership…</div>';try{const d=await api('/api/verify',{method:'POST',body:'{}'});if(d.verified){msg.innerHTML='<div class="notice ok">Verification successful. Welcome to Falcon World!</div>';setTimeout(()=>{setPage('home');loadMe()},350)}else{msg.innerHTML='<div class="notice warn">'+d.verified_count+'/'+d.total+' channels joined. Join the remaining channels and try again.</div>';renderChannels()}}catch(e){msg.innerHTML='<div class="notice err">'+esc(e.message)+'</div>'}}
function money(n){return Number(n||0).toFixed(2)+' ETB'}
async function loadMe(){try{const d=await api('/api/me');userData=d;document.getElementById('balance').textContent=money(d.balance);document.getElementById('balance2').textContent=money(d.balance);document.getElementById('withdrawBalance').textContent=money(d.balance);document.getElementById('homeId').textContent=d.user_id;document.getElementById('homeWallet').textContent=d.wallet_type||'Not set';document.getElementById('withdrawWallet').textContent=d.wallet_type?d.wallet_type:'Not set';document.getElementById('refEarn').textContent=money(d.referral_earnings);document.getElementById('dailyEarn').textContent=money(d.daily_bonus_earnings);document.getElementById('taskEarn').textContent=money(d.task_earnings);document.getElementById('totalEarn').textContent=money(d.total_earned);document.getElementById('totalWithdrawn').textContent=money(d.total_withdrawn);document.getElementById('pendingWithdraw').textContent=money(d.pending_withdrawal);document.getElementById('minWithdraw').textContent=money(d.min_withdraw);if(d.wallet_type){walletType=d.wallet_type;renderWallet()}}catch(e){}}
async function loadReferral(){try{const d=await api('/api/referral');document.getElementById('refLink').value=d.link;document.getElementById('refCount').textContent=d.count;document.getElementById('refReward').textContent=money(d.reward);document.getElementById('refPageEarn').textContent=money(d.earnings)}catch(e){}}
async function copyReferral(){try{await navigator.clipboard.writeText(document.getElementById('refLink').value);tg?.showPopup?.({title:'Copied',message:'Referral link copied.',buttons:[{type:'ok'}]})}catch(e){}}
function shareReferral(){const link=document.getElementById('refLink').value;const text=encodeURIComponent('Join Falcon World and start earning rewards!');openLink('https://t.me/share/url?url='+encodeURIComponent(link)+'&text='+text)}
async function loadDaily(){try{const d=await api('/api/daily-status');document.getElementById('dailyReward').textContent=Number(d.reward).toFixed(2);document.getElementById('todayDate').textContent=d.today;document.getElementById('nextClaim').textContent=d.can_claim?'Available':d.next_date;const b=document.getElementById('claimBtn');b.disabled=!d.can_claim;b.style.opacity=d.can_claim?'1':'.55'}catch(e){}}
async function claimDaily(){const msg=document.getElementById('dailyMsg');try{const d=await api('/api/daily-bonus',{method:'POST',body:'{}'});msg.innerHTML='<div class="notice ok">+'+Number(d.reward).toFixed(2)+' ETB added. Your balance is '+money(d.balance)+'.</div>';loadMe();loadDaily()}catch(e){msg.innerHTML='<div class="notice warn">'+esc(e.message)+'</div>';loadDaily()}}
function selectWallet(t){walletType=t;document.getElementById('cbeBtn').classList.toggle('active',t==='CBE');document.getElementById('teleBtn').classList.toggle('active',t==='Telebirr');const inp=document.getElementById('walletNumber');inp.maxLength=t==='CBE'?13:10;inp.placeholder=t==='CBE'?'1000XXXXXXXXX':'09XXXXXXXX / 07XXXXXXXX'}
function renderWallet(){selectWallet(walletType);const w=userData?.wallet_type&&userData?.wallet_number?userData:null;if(w){document.getElementById('walletNumber').value=w.wallet_number;document.getElementById('savedWallet').innerHTML='<div class="notice ok">Connected wallet: <b>'+esc(w.wallet_type)+'</b> <span class="mask">'+esc(maskWallet(w.wallet_number))+'</span></div>'}}
function maskWallet(n){if(n.length===13)return n.slice(0,4)+'*********';return n.slice(0,2)+'********'}
async function saveWallet(){const msg=document.getElementById('walletMsg');try{const d=await api('/api/wallet',{method:'POST',body:JSON.stringify({wallet_type:walletType,wallet_number:document.getElementById('walletNumber').value.trim()})});msg.innerHTML='<div class="notice '+(d.suspicious?'warn':'ok')+'">'+esc(d.message)+(d.suspicious?' Duplicate wallet detected and flagged for admin review.':'')+'</div>';await loadMe();renderWallet()}catch(e){msg.innerHTML='<div class="notice err">'+esc(e.message)+'</div>'}}
async function loadTasks(){const box=document.getElementById('tasksList');box.innerHTML='Loading…';try{const d=await api('/api/tasks');if(!d.tasks.length){box.innerHTML='<div class="muted">📋 No active tasks available right now. Please check back later.</div>';return}box.innerHTML=d.tasks.map(t=>`<div class="task"><div class="taskTop"><h3>${esc(t.title)}</h3><div class="reward">+${Number(t.reward).toFixed(2)} ETB</div></div><p>${esc(t.description||'Complete the task and submit your proof.')}</p>${t.url?`<p><a href="${esc(t.url)}" target="_blank">Open task →</a></p>`:''}<div class="taskStatus">Status: ${esc(t.submission_status||'not submitted')}</div>${t.submission_status!=='approved'&&t.submission_status!=='pending'?`<textarea id="proof_${t.id}" placeholder="Write your proof here…"></textarea><button class="primary" onclick="submitTask(${t.id})">Submit Proof</button>`:''}</div>`).join('')}catch(e){box.innerHTML='<div class="notice err">'+esc(e.message)+'</div>'}}
async function submitTask(id){const proof=document.getElementById('proof_'+id)?.value.trim();if(!proof)return;try{await api('/api/tasks/'+id+'/submit',{method:'POST',body:JSON.stringify({proof})});tg?.showPopup?.({title:'Submitted',message:'Your proof has been submitted for review.',buttons:[{type:'ok'}]});loadTasks()}catch(e){tg?.showPopup?.({title:'Error',message:e.message,buttons:[{type:'ok'}]})}}
async function withdraw(){const msg=document.getElementById('withdrawMsg');const amount=Number(document.getElementById('withdrawAmount').value);if(!amount||amount<=0){msg.innerHTML='<div class="notice err">Enter a valid withdrawal amount.</div>';return}try{const d=await api('/api/withdraw',{method:'POST',body:JSON.stringify({amount})});msg.innerHTML='<div class="notice ok">Withdrawal #'+d.withdrawal_id+' created for '+money(d.amount)+'.</div>';document.getElementById('withdrawAmount').value='';loadMe()}catch(e){msg.innerHTML='<div class="notice warn">'+esc(e.message)+'</div>'}}
function openSupport(){openLink('https://t.me/AmanM_12')}
window.addEventListener('load',async()=>{setTimeout(()=>document.getElementById('splash').classList.add('hidden'),700);await start()});
</script>
</body></html>"""
    return HTMLResponse(content=html)


CAPTCHA_SESSIONS = {}


def _new_captcha(user_id: int):
    import secrets
    import random
    a, b = random.randint(11, 39), random.randint(3, 18)
    token = secrets.token_urlsafe(18)
    CAPTCHA_SESSIONS[user_id] = {"token": token, "answer": a + b, "expires": time.time() + 300}
    return {"token": token, "question": f"What is {a} + {b}?"}


@app.get("/api/captcha")
async def api_captcha(request: Request):
    user, error = await require_user(request)
    if error:
        return error
    return _new_captcha(int(user["id"]))


@app.post("/api/captcha/verify")
async def api_captcha_verify(request: Request):
    user, error = await require_user(request)
    if error:
        return error
    uid = int(user["id"])
    session = CAPTCHA_SESSIONS.get(uid)
    if not session or session["expires"] < time.time():
        return JSONResponse({"error": "CAPTCHA expired. Please request a new one."}, status_code=400)
    try:
        body = await request.json()
        if str(body.get("token", "")) != str(session.get("token", "")):
            return JSONResponse({"error": "Invalid verification session."}, status_code=400)
        answer = int(str(body.get("answer", "")).strip())
    except Exception:
        return JSONResponse({"error": "Please enter a valid number."}, status_code=400)
    if answer != session["answer"]:
        CAPTCHA_SESSIONS.pop(uid, None)
        return JSONResponse({"ok": False, "error": "Incorrect answer. Please try again."}, status_code=400)
    session["human"] = True
    session["expires"] = time.time() + 600
    return {"ok": True}


@app.api_route("/api/verify", methods=["GET", "POST"])
async def verify_user(request: Request):
    user, error = await require_user(request)
    if error:
        return error

    user_id = int(user["id"])

    if request.method == "POST":
        session = CAPTCHA_SESSIONS.get(user_id)
        if not session or not session.get("human") or session.get("expires", 0) < time.time():
            return JSONResponse({"error": "Complete human verification first."}, status_code=403)

    verification = await check_all_channels(user_id)

    if verification["verified"]:
        ensure_user(
            user_id,
            user.get("username", ""),
            user.get("first_name", ""),
        )

        conn = __import__("sqlite3").connect(
            os.getenv("DB_PATH", "falcon_world.db")
        )
        try:
            conn.execute(
                "UPDATE users SET verified=1,updated_at=? WHERE user_id=?",
                (int(time.time()), user_id),
            )
            conn.commit()
        finally:
            conn.close()

        reward_referrer_after_verification(user_id)

    return JSONResponse(verification)


@app.get("/api/me")
async def api_me(request: Request):
    user, error = await require_user(request)
    if error:
        return error

    user_id = int(user["id"])
    ensure_user(
        user_id,
        user.get("username", ""),
        user.get("first_name", ""),
    )

    row = get_user(user_id)
    if not row:
        return JSONResponse({"error": "user_not_found"}, status_code=404)

    conn = db()
    try:
        total_withdrawn = conn.execute("SELECT COALESCE(SUM(amount),0) s FROM withdrawals WHERE user_id=? AND status='approved'", (user_id,)).fetchone()["s"]
        pending_withdrawal = conn.execute("SELECT COALESCE(SUM(amount),0) s FROM withdrawals WHERE user_id=? AND status='pending'", (user_id,)).fetchone()["s"]
    finally:
        conn.close()
    referral_earnings = float(row["referral_earnings"] or 0)
    daily_bonus_earnings = float(row["daily_bonus_earnings"] or 0)
    task_earnings = float(row["task_earnings"] or 0)
    return {
        "user_id": row["user_id"], "username": row["username"], "first_name": row["first_name"],
        "balance": float(row["balance"]), "verified": bool(row["verified"]),
        "wallet_type": row["wallet_type"], "wallet_number": row["wallet_number"],
        "wallet_suspicious": bool(row["wallet_suspicious"]),
        "referral_earnings": referral_earnings, "daily_bonus_earnings": daily_bonus_earnings,
        "task_earnings": task_earnings, "total_earned": referral_earnings + daily_bonus_earnings + task_earnings,
        "total_withdrawn": float(total_withdrawn or 0), "pending_withdrawal": float(pending_withdrawal or 0),
        "min_withdraw": float(get_setting("min_withdraw", DEFAULT_MIN_WITHDRAW)),
    }


@app.get("/api/daily-status")
async def api_daily_status(request: Request):
    user, error = await require_user(request)
    if error:
        return error
    from datetime import timedelta
    uid = int(user["id"])
    row = get_user(uid)
    today = _local_gregorian_date()
    last = int(row["daily_last_claim"] or 0)
    can = not last or _local_gregorian_date(last) != today
    return {"today": str(today), "can_claim": can, "reward": float(get_setting("daily_bonus", DEFAULT_DAILY_BONUS)), "next_date": str(today + timedelta(days=1)) if not can else str(today)}


@app.post("/api/daily-bonus")
async def api_daily_bonus(request: Request):
    user, error = await require_user(request)
    if error:
        return error

    ok, result = claim_daily_bonus(int(user["id"]))

    if not ok:
        if result.get("error") == "already_claimed":
            return JSONResponse({"error": "Daily bonus already claimed for today.", "date": result.get("date")}, status_code=429)
        if result.get("error") == "not_verified":
            return JSONResponse(
                {"error": "Please verify all required channels first."},
                status_code=403,
            )
        return JSONResponse(
            {"error": result.get("error", "Could not claim bonus.")},
            status_code=400,
        )

    return {
        "reward": result["reward"],
        "balance": result["balance"],
    }


@app.get("/api/referral")
async def api_referral(request: Request):
    user, error = await require_user(request)
    if error:
        return error

    user_id = int(user["id"])
    link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"
    count = get_referral_count(user_id)
    reward = get_setting(
        "referral_reward",
        DEFAULT_REFERRAL_REWARD,
    )

    row = get_user(user_id)
    return {"link": link, "count": count, "reward": reward, "earnings": float(row["referral_earnings"] or 0)}


@app.post("/api/wallet")
async def api_wallet(request: Request):
    user, error = await require_user(request)
    if error:
        return error

    try:
        body = await request.json()
    except Exception:
        body = {}

    wallet_type = str(body.get("wallet_type", "")).strip()
    wallet_number = str(body.get("wallet_number", "")).strip()

    ok, message, suspicious = save_wallet(
        int(user["id"]),
        wallet_type,
        wallet_number,
    )

    if not ok:
        return JSONResponse(
            {"error": message},
            status_code=400,
        )

    if suspicious:
        await send_admin_message(
            f"⚠️ <b>Duplicate Wallet Alert</b>\n\n"
            f"User ID: <code>{user['id']}</code>\n"
            f"Wallet: <b>{wallet_type}</b>\n"
            f"Number: <code>{wallet_number}</code>"
        )

    return {
        "ok": True,
        "message": message,
        "suspicious": suspicious,
    }


@app.get("/api/tasks")
async def api_tasks(request: Request):
    user, error = await require_user(request)
    if error:
        return error

    rows = get_active_tasks(int(user["id"]))

    return {
        "tasks": [
            {
                "id": row["id"],
                "title": row["title"],
                "description": row["description"],
                "reward": float(row["reward"]),
                "url": row["url"],
                "submission_status": row["submission_status"],
            }
            for row in rows
        ]
    }


@app.post("/api/tasks/{task_id}/submit")
async def api_submit_task(
    task_id: int,
    request: Request,
):
    user, error = await require_user(request)
    if error:
        return error

    try:
        body = await request.json()
    except Exception:
        body = {}

    proof = str(body.get("proof", "")).strip()

    ok, result = submit_task(
        int(user["id"]),
        task_id,
        proof,
    )

    if not ok:
        return JSONResponse(
            {"error": result},
            status_code=400,
        )

    await notify_task_submission(result["submission_id"])

    return {
        "ok": True,
        "submission_id": result["submission_id"],
    }


@app.post("/api/withdraw")
async def api_withdraw(request: Request):
    user, error = await require_user(request)
    if error:
        return error

    try:
        body = await request.json()
    except Exception:
        body = {}
    requested_amount = body.get("amount")
    ok, result = create_withdrawal(int(user["id"]), requested_amount)

    if not ok:
        return JSONResponse(
            {"error": result},
            status_code=400,
        )

    await notify_withdrawal(result["withdrawal_id"])

    return {
        "ok": True,
        "withdrawal_id": result["withdrawal_id"],
        "amount": result["amount"],
        "wallet_type": result["wallet_type"],
        "wallet_number": result["wallet_number"],
        "suspicious": result["suspicious"],
    }


@app.post("/webhook")
async def webhook(request: Request):
    if WEBHOOK_SECRET:
        supplied = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(supplied, WEBHOOK_SECRET):
            return JSONResponse({"ok": False}, status_code=403)

    try:
        update = await request.json()
    except Exception:
        return {"ok": True}

    try:
        await handle_update(update)
    except Exception as e:
        print("Webhook error:", repr(e))

    return {"ok": True}


@app.on_event("startup")
async def startup():
    configure_bot()
    init_db()

    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN is missing.")
        return

    await telegram_request(
        "setMyCommands",
        {
            "commands": [
                {"command": "start", "description": "Open Falcon World"},
                {"command": "admin", "description": "Admin dashboard"},
            ]
        },
    )

    menu_data = {
        "menu_button": {
            "type": "web_app",
            "text": "🦅 Open Falcon World",
            "web_app": {"url": MINI_APP_URL},
        }
    }

    await telegram_request(
        "setChatMenuButton",
        menu_data,
    )

    webhook_data = {
        "url": WEBHOOK_URL,
        "allowed_updates": ["message", "callback_query"],
    }

    if WEBHOOK_SECRET:
        webhook_data["secret_token"] = WEBHOOK_SECRET

    result = await telegram_request(
        "setWebhook",
        webhook_data,
    )

    print("Webhook setup:", result)
