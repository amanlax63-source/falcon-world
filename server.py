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

        CREATE INDEX IF NOT EXISTS idx_withdrawals_status ON withdrawals(status);
        CREATE INDEX IF NOT EXISTS idx_submissions_task_user ON task_submissions(task_id, user_id);
        """)
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


def claim_daily_bonus(user_id: int):
    now = int(time.time())
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
        remaining = 86400 - (now - int(row["daily_last_claim"] or 0))
        if remaining > 0:
            conn.rollback()
            return False, {"error": "cooldown", "remaining": remaining}
        conn.execute(
            "UPDATE users SET balance=ROUND(balance+?,8),daily_last_claim=?,updated_at=? WHERE user_id=?",
            (reward, now, now, user_id),
        )
        conn.commit()
        return True, {"reward": reward, "balance": float(row["balance"]) + reward}
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
            "UPDATE users SET balance=ROUND(balance+?,8),updated_at=? WHERE user_id=?",
            (reward, now, referrer_id),
        )
        conn.execute(
            "UPDATE users SET referral_reward_paid=1,updated_at=? WHERE user_id=?",
            (now, now, user_id),
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


def create_withdrawal(user_id: int):
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
        amount = float(user["balance"])
        if amount < minimum:
            conn.rollback()
            return False, f"Minimum withdrawal is {minimum:.2f} ETB."
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
            "UPDATE users SET balance=0,updated_at=? WHERE user_id=?",
            (now, user_id),
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
                    "UPDATE users SET balance=ROUND(balance+?,8),updated_at=? WHERE user_id=?",
                    (row["reward"], now, row["user_id"]),
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
    return {
        "keyboard": [
            [{"text": "💰 Balance"}, {"text": "🎁 Daily Bonus"}],
            [{"text": "👥 Invite Friends"}, {"text": "📋 Tasks"}],
            [{"text": "💳 Wallet Settings"}, {"text": "💸 Withdraw"}],
            [{"text": "❓ Help"}, {"text": "🆘 Support"}],
        ],
        "resize_keyboard": True,
    }


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
                "📢 Ads & Promotions: Contact us\n\n"
                "🚀 Open Falcon World from the Menu below."
            ),
            {"inline_keyboard": [[{"text": "🚀 Open Falcon World", "web_app": {"url": MINI_APP_URL}}]]},
        )
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

    results = await asyncio.gather(
        *(check(ch) for ch in REQUIRED_CHANNELS)
    )

    verified_count = sum(
        1 for channel in results if channel["joined"]
    )

    verified = verified_count == len(REQUIRED_CHANNELS)

    return {
        "verified": verified,
        "verified_count": verified_count,
        "total": len(REQUIRED_CHANNELS),
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
    html = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<title>Falcon World</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
*{box-sizing:border-box}
body{
margin:0;
font-family:Arial,sans-serif;
background:#07152e;
color:#fff;
min-height:100vh;
}
button{
font-family:inherit;
cursor:pointer;
}
.container{
max-width:520px;
margin:auto;
padding:18px;
}
.loading{
position:fixed;
inset:0;
background:#07152e;
display:flex;
flex-direction:column;
justify-content:center;
align-items:center;
z-index:20;
}
.logo{
font-size:72px;
margin-bottom:12px;
}
.loading h1{
margin:0;
font-size:28px;
}
.loading p{
opacity:.7;
margin:8px 0 20px;
}
.progress{
width:75%;
height:8px;
background:#172b4f;
border-radius:20px;
overflow:hidden;
}
.progress span{
display:block;
height:100%;
width:0;
background:#2f8cff;
transition:.15s;
}
.header{
display:flex;
align-items:center;
justify-content:space-between;
margin-bottom:18px;
}
.brand{
font-size:24px;
font-weight:800;
}
.status{
font-size:12px;
padding:7px 10px;
border-radius:15px;
background:#12335f;
}
.card{
background:#0e2244;
border:1px solid #19375f;
border-radius:20px;
padding:18px;
margin-bottom:14px;
box-shadow:0 8px 25px rgba(0,0,0,.15);
}
.balance{
font-size:34px;
font-weight:800;
margin-top:8px;
}
.muted{
color:#91a5c4;
font-size:13px;
}
.verify-title{
font-size:20px;
font-weight:800;
margin-bottom:8px;
}
.channel{
display:flex;
align-items:center;
justify-content:space-between;
gap:10px;
background:#0a1b37;
border:1px solid #18365e;
border-radius:14px;
padding:12px;
margin:8px 0;
}
.channel-name{
font-weight:700;
font-size:14px;
}
.channel small{
display:block;
color:#7f95b6;
margin-top:3px;
}
.join{
border:0;
background:#2388ff;
color:#fff;
padding:9px 13px;
border-radius:10px;
font-weight:700;
}
.joined{
background:#123e2b;
color:#62e69b;
padding:9px 11px;
border-radius:10px;
font-weight:700;
}
.primary{
width:100%;
border:0;
padding:14px;
border-radius:14px;
background:#2388ff;
color:#fff;
font-size:16px;
font-weight:800;
margin-top:12px;
}
.secondary{
width:100%;
border:1px solid #284c79;
padding:13px;
border-radius:14px;
background:#0c1d39;
color:#fff;
font-size:15px;
font-weight:700;
margin-top:9px;
}
.grid{
display:grid;
grid-template-columns:1fr 1fr;
gap:10px;
}
.action{
border:1px solid #1b3c68;
background:#0d2142;
color:#fff;
padding:16px 10px;
border-radius:16px;
font-weight:800;
font-size:14px;
min-height:72px;
}
.section{
display:none;
}
.section.active{
display:block;
}
input,textarea,select{
width:100%;
background:#081a35;
border:1px solid #24476f;
color:#fff;
border-radius:12px;
padding:13px;
margin-top:8px;
outline:none;
}
textarea{
min-height:110px;
resize:vertical;
}
.task{
background:#0a1b37;
border:1px solid #18375f;
padding:14px;
border-radius:14px;
margin:9px 0;
}
.task h3{
margin:0 0 7px;
font-size:16px;
}
.task p{
margin:0 0 8px;
color:#9db0cc;
font-size:13px;
line-height:1.4;
}
.task a{
color:#53a2ff;
}
.hidden{display:none!important}
.center{text-align:center}
.small{font-size:12px}
.warning{
background:#392d0c;
border:1px solid #6e5b1e;
color:#f5d77c;
padding:12px;
border-radius:12px;
margin-top:10px;
font-size:13px;
}
.success{
background:#0d3927;
border:1px solid #1f704e;
color:#72efaa;
padding:12px;
border-radius:12px;
margin-top:10px;
font-size:13px;
}
</style>
</head>
<body>

<div class="loading" id="loading">
<div class="logo">🦅</div>
<h1>Falcon World</h1>
<p>Loading your account...</p>
<div class="progress"><span id="progress"></span></div>
<div class="small" id="progressText">0%</div>
</div>

<div class="container">

<div id="verifyPage">
<div class="header">
<div class="brand">🦅 Falcon World</div>
<div class="status">Verification</div>
</div>

<div class="card">
<div class="verify-title">Join Required Channels</div>
<div class="muted">Join all channels, then press Verify.</div>
<div id="channels"></div>
<button class="primary" onclick="verify()">✅ Verify Membership</button>
<div id="verifyMessage"></div>
</div>
</div>

<div id="dashboard" class="section">
<div class="header">
<div class="brand">🦅 Falcon World</div>
<div class="status">Verified</div>
</div>

<div class="card">
<div class="muted">Available Balance</div>
<div class="balance" id="balance">0.00 ETB</div>
</div>

<div class="grid">
<button class="action" onclick="showSection('daily')">🎁<br>Daily Bonus</button>
<button class="action" onclick="showSection('referral')">👥<br>Referral</button>
<button class="action" onclick="showSection('tasks')">📋<br>Tasks</button>
<button class="action" onclick="showSection('wallet')">💳<br>Wallet</button>
<button class="action" onclick="showSection('withdraw')">💸<br>Withdraw</button>
<button class="action" onclick="showSection('help')">❓<br>Help</button>
</div>

<div class="card" style="margin-top:14px">
<div class="muted">Account</div>
<div id="accountInfo" style="margin-top:7px"></div>
</div>
</div>

<div id="daily" class="section">
<div class="header"><div class="brand">🎁 Daily Bonus</div></div>
<div class="card">
<div class="muted">Daily reward</div>
<div class="balance">+0.50 ETB</div>
<div id="dailyMsg"></div>
<button class="primary" onclick="claimDaily()">🎁 Claim Bonus</button>
<button class="secondary" onclick="showSection('dashboard')">← Back</button>
</div>
</div>

<div id="referral" class="section">
<div class="header"><div class="brand">👥 Invite Friends</div></div>
<div class="card">
<div class="muted">Your referral link</div>
<input id="refLink" readonly>
<button class="primary" onclick="copyReferral()">📋 Copy Link</button>
<div id="refStats" style="margin-top:14px"></div>
<button class="secondary" onclick="showSection('dashboard')">← Back</button>
</div>
</div>

<div id="tasks" class="section">
<div class="header"><div class="brand">📋 Tasks</div></div>
<div class="card">
<div id="tasksList">Loading...</div>
<button class="secondary" onclick="showSection('dashboard')">← Back</button>
</div>
</div>

<div id="wallet" class="section">
<div class="header"><div class="brand">💳 Wallet</div></div>
<div class="card">
<div class="muted">Wallet type</div>
<select id="walletType">
<option value="CBE">CBE</option>
<option value="Telebirr">Telebirr</option>
</select>
<div class="muted" style="margin-top:12px">Wallet number</div>
<input id="walletNumber" inputmode="numeric" placeholder="Enter wallet number">
<button class="primary" onclick="saveWallet()">💾 Save Wallet</button>
<div id="walletMsg"></div>
<button class="secondary" onclick="showSection('dashboard')">← Back</button>
</div>
</div>

<div id="withdraw" class="section">
<div class="header"><div class="brand">💸 Withdraw</div></div>
<div class="card">
<div class="muted">Current balance</div>
<div class="balance" id="withdrawBalance">0.00 ETB</div>
<div class="muted" style="margin-top:10px">Minimum withdrawal: 30 ETB</div>
<div id="withdrawMsg"></div>
<button class="primary" onclick="withdraw()">💸 Request Withdrawal</button>
<button class="secondary" onclick="showSection('dashboard')">← Back</button>
</div>
</div>

<div id="help" class="section">
<div class="header"><div class="brand">❓ Help</div></div>
<div class="card">
<b>How Falcon World works</b>
<p class="muted">1. Join all required channels.</p>
<p class="muted">2. Verify your account.</p>
<p class="muted">3. Claim the daily bonus.</p>
<p class="muted">4. Invite friends.</p>
<p class="muted">5. Complete available tasks.</p>
<p class="muted">6. Save CBE or Telebirr and withdraw when you reach the minimum.</p>
<button class="secondary" onclick="showSection('dashboard')">← Back</button>
</div>
</div>

</div>

<script>
const tg = window.Telegram?.WebApp;
if(tg){
tg.ready();
tg.expand();
}

const initData = tg?.initData || "";
const headers = {
"Content-Type":"application/json",
"X-Telegram-Init-Data":initData
};

let userData = null;

function esc(s){
return String(s ?? "").replace(/[&<>"']/g,m=>({
"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"
}[m]));
}

function showSection(name){
document.querySelectorAll(".section").forEach(x=>x.classList.remove("active"));
if(name==="dashboard"){
document.getElementById("dashboard").classList.add("active");
loadMe();
}else{
document.getElementById(name).classList.add("active");
if(name==="referral") loadReferral();
if(name==="tasks") loadTasks();
if(name==="withdraw") loadMe();
}
}

async function api(url, options={}){
const res = await fetch(url,{
...options,
headers:{...headers,...(options.headers||{})}
});
let data={};
try{data=await res.json()}catch(e){}
if(!res.ok) throw new Error(data.error || "Request failed");
return data;
}

async function renderChannels(){
const box=document.getElementById("channels");
box.innerHTML="";
try{
const data=await api("/api/verify",{method:"POST",body:"{}"});
data.channels.forEach(ch=>{
const div=document.createElement("div");
div.className="channel";
div.innerHTML=`
<div>
<div class="channel-name">${esc(ch.name)}</div>
<small>${esc(ch.username)}</small>
</div>
${ch.joined
?'<div class="joined">✓ Joined</div>'
:`<button class="join" onclick="openChannel('${ch.url}')">Join</button>`}
`;
box.appendChild(div);
});
}catch(e){
box.innerHTML='<div class="warning">Telegram authentication is required. Open Falcon World from Telegram.</div>';
}
}

function openChannel(url){
if(tg && tg.openTelegramLink) tg.openTelegramLink(url);
else window.open(url,"_blank");
}

async function verify(){
const msg=document.getElementById("verifyMessage");
msg.innerHTML='<div class="muted" style="margin-top:10px">Checking...</div>';
try{
const data=await api("/api/verify",{method:"POST",body:"{}"});
if(data.verified){
msg.innerHTML='<div class="success">✅ Verification successful.</div>';
await loadMe();
document.getElementById("verifyPage").classList.add("hidden");
document.getElementById("dashboard").classList.add("active");
}else{
msg.innerHTML=`<div class="warning">⚠️ ${data.verified_count}/${data.total} channels joined. Join the remaining channels and verify again.</div>`;
renderChannels();
}
}catch(e){
msg.innerHTML=`<div class="warning">❌ ${esc(e.message)}</div>`;
}
}

async function loadMe(){
try{
const data=await api("/api/me");
userData=data;
document.getElementById("balance").textContent=(data.balance||0).toFixed(2)+" ETB";
document.getElementById("withdrawBalance").textContent=(data.balance||0).toFixed(2)+" ETB";
document.getElementById("accountInfo").innerHTML=
`ID: <code>${esc(data.user_id)}</code><br>
Verified: ${data.verified ? "✅ Yes":"❌ No"}<br>
Wallet: ${data.wallet_type ? esc(data.wallet_type)+" / "+esc(data.wallet_number):"Not set"}`;
if(data.wallet_type) document.getElementById("walletType").value=data.wallet_type;
if(data.wallet_number) document.getElementById("walletNumber").value=data.wallet_number;
}catch(e){
console.error(e);
}
}

async function loadReferral(){
try{
const data=await api("/api/referral");
document.getElementById("refLink").value=data.link;
document.getElementById("refStats").innerHTML=
`👥 Successful referrals: <b>${data.count}</b><br>
💰 Reward per verified referral: <b>${Number(data.reward).toFixed(2)} ETB</b>`;
}catch(e){}
}

async function copyReferral(){
const el=document.getElementById("refLink");
try{
await navigator.clipboard.writeText(el.value);
if(tg) tg.showPopup({title:"Copied",message:"Referral link copied.",buttons:[{type:"ok"}]});
}catch(e){el.select();document.execCommand("copy");}
}

async function claimDaily(){
const msg=document.getElementById("dailyMsg");
try{
const data=await api("/api/daily-bonus",{method:"POST",body:"{}"});
msg.innerHTML=`<div class="success">🎁 +${Number(data.reward).toFixed(2)} ETB added. Balance: ${Number(data.balance).toFixed(2)} ETB</div>`;
loadMe();
}catch(e){
msg.innerHTML=`<div class="warning">⚠️ ${esc(e.message)}</div>`;
}
}

async function loadTasks(){
const box=document.getElementById("tasksList");
box.innerHTML="Loading...";
try{
const data=await api("/api/tasks");
if(!data.tasks.length){
box.innerHTML='<div class="muted">No active tasks right now.</div>';
return;
}
box.innerHTML=data.tasks.map(t=>`
<div class="task">
<h3>${esc(t.title)}</h3>
<p>${esc(t.description)}</p>
<p>💰 Reward: <b>${Number(t.reward).toFixed(2)} ETB</b></p>
${t.url?`<p><a href="${esc(t.url)}" target="_blank">🔗 Open Task</a></p>`:""}
<p class="small">Status: ${esc(t.submission_status || "not submitted")}</p>
${t.submission_status!=="approved" && t.submission_status!=="pending"
?`<textarea id="proof_${t.id}" placeholder="Write your proof here..."></textarea>
<button class="primary" onclick="submitTask(${t.id})">📤 Submit Proof</button>`
:""}
</div>
`).join("");
}catch(e){
box.innerHTML=`<div class="warning">${esc(e.message)}</div>`;
}
}

async function submitTask(id){
const proof=document.getElementById("proof_"+id)?.value?.trim();
if(!proof){
alert("Please enter proof.");
return;
}
try{
await api("/api/tasks/"+id+"/submit",{
method:"POST",
body:JSON.stringify({proof})
});
alert("Proof submitted successfully.");
loadTasks();
}catch(e){
alert(e.message);
}
}

async function saveWallet(){
const msg=document.getElementById("walletMsg");
const wallet_type=document.getElementById("walletType").value;
const wallet_number=document.getElementById("walletNumber").value.trim();
try{
const data=await api("/api/wallet",{
method:"POST",
body:JSON.stringify({wallet_type,wallet_number})
});
msg.innerHTML=`<div class="${data.suspicious?'warning':'success'}">${esc(data.message)}${data.suspicious?"<br>⚠️ This wallet is already linked to another account.":""}</div>`;
loadMe();
}catch(e){
msg.innerHTML=`<div class="warning">${esc(e.message)}</div>`;
}
}

async function withdraw(){
const msg=document.getElementById("withdrawMsg");
try{
const data=await api("/api/withdraw",{method:"POST",body:"{}"});
msg.innerHTML=`<div class="success">✅ Withdrawal #${data.withdrawal_id} created for ${Number(data.amount).toFixed(2)} ETB.</div>`;
loadMe();
}catch(e){
msg.innerHTML=`<div class="warning">⚠️ ${esc(e.message)}</div>`;
}
}

window.addEventListener("load",async()=>{
let p=0;
const timer=setInterval(()=>{
p+=5;
document.getElementById("progress").style.width=p+"%";
document.getElementById("progressText").textContent=p+"%";
if(p>=100){
clearInterval(timer);
setTimeout(async()=>{
document.getElementById("loading").classList.add("hidden");
try{
const me=await api("/api/me");
if(me.verified){
document.getElementById("verifyPage").classList.add("hidden");
document.getElementById("dashboard").classList.add("active");
loadMe();
}else{
document.getElementById("verifyPage").classList.remove("hidden");
renderChannels();
}
}catch(e){
document.getElementById("verifyPage").classList.remove("hidden");
renderChannels();
}
},250);
}
},35);
});
</script>
</body>
</html>"""
    return HTMLResponse(content=html)


@app.post("/api/verify")
async def verify_user(request: Request):
    user, error = await require_user(request)
    if error:
        return error

    user_id = int(user["id"])

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

    return {
        "user_id": row["user_id"],
        "username": row["username"],
        "first_name": row["first_name"],
        "balance": float(row["balance"]),
        "verified": bool(row["verified"]),
        "wallet_type": row["wallet_type"],
        "wallet_number": row["wallet_number"],
        "wallet_suspicious": bool(row["wallet_suspicious"]),
    }


@app.post("/api/daily-bonus")
async def api_daily_bonus(request: Request):
    user, error = await require_user(request)
    if error:
        return error

    ok, result = claim_daily_bonus(int(user["id"]))

    if not ok:
        if result.get("error") == "cooldown":
            return JSONResponse(
                {
                    "error": "Daily bonus is on cooldown.",
                    "remaining": result["remaining"],
                },
                status_code=429,
            )
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

    return {
        "link": link,
        "count": count,
        "reward": reward,
    }


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

    ok, result = create_withdrawal(int(user["id"]))

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
            "text": "🚀 Open Falcon",
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
