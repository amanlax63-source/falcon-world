import os
import re
import sqlite3
import time
import html
from typing import Optional

import httpx

# ============================================================
# FALCON WORLD - BOT BACKEND
# This file is designed to work with FastAPI/webhook in server.py.
# Do NOT run Telegram polling from this file.
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
BOT_USERNAME = os.getenv("BOT_USERNAME", "FalconWorld_Bot").strip().lstrip("@")
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", os.getenv("ADMIN_ID", "")).strip()
ADMIN_IDS = {
    int(x.strip()) for x in ADMIN_IDS_RAW.split(",")
    if x.strip().isdigit()
}

DB_PATH = os.getenv("DB_PATH", "falcon_world.db").strip()

SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "@AmanM_12").strip()
MINI_APP_URL = os.getenv(
    "MINI_APP_URL",
    "https://falcon-world.onrender.com/app"
).strip()

REQUIRED_CHANNELS = [
    {
        "username": "@Sheger_tech1",
        "name": "Sheger Tech",
        "url": "https://t.me/Sheger_tech1",
    },
    {
        "username": "@EthioVortex1",
        "name": "Ethio Vortex",
        "url": "https://t.me/EthioVortex1",
    },
    {
        "username": "@ethiocashflow",
        "name": "Ethio Cash Flow",
        "url": "https://t.me/ethiocashflow",
    },
    {
        "username": "@AmanIncomeLab",
        "name": "Aman Income Lab",
        "url": "https://t.me/AmanIncomeLab",
    },
    {
        "username": "@OnlineIncomeHub07",
        "name": "Online Income Hub",
        "url": "https://t.me/OnlineIncomeHub07",
    },
    {
        "username": "@Paymentprooff2",
        "name": "Payment Proof",
        "url": "https://t.me/Paymentprooff2",
    },
]

DEFAULT_REFERRAL_REWARD = 2.0
DEFAULT_DAILY_BONUS = 0.50
DEFAULT_MIN_WITHDRAW = 100.0

# ============================================================
# DATABASE
# ============================================================

def get_db():
    conn = sqlite3.connect(
        DB_PATH,
        timeout=30,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT DEFAULT '',
                first_name TEXT DEFAULT '',
                balance REAL NOT NULL DEFAULT 0,
                referred_by INTEGER,
                referral_reward_paid INTEGER NOT NULL DEFAULT 0,
                verified INTEGER NOT NULL DEFAULT 0,
                banned INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                last_seen INTEGER NOT NULL,
                last_daily_bonus INTEGER NOT NULL DEFAULT 0,
                wallet_type TEXT DEFAULT '',
                wallet_number TEXT DEFAULT '',
                wallet_suspicious INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(referred_by) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER NOT NULL,
                referred_id INTEGER NOT NULL UNIQUE,
                reward REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at INTEGER NOT NULL,
                paid_at INTEGER,
                FOREIGN KEY(referrer_id) REFERENCES users(id),
                FOREIGN KEY(referred_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                link TEXT DEFAULT '',
                reward REAL NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS task_submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                proof TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at INTEGER NOT NULL,
                reviewed_at INTEGER,
                UNIQUE(task_id, user_id),
                FOREIGN KEY(task_id) REFERENCES tasks(id),
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS withdrawals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                wallet_type TEXT NOT NULL,
                wallet_number TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at INTEGER NOT NULL,
                reviewed_at INTEGER,
                reviewed_by INTEGER,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_users_referred_by
                ON users(referred_by);

            CREATE INDEX IF NOT EXISTS idx_withdrawals_user
                ON withdrawals(user_id);

            CREATE INDEX IF NOT EXISTS idx_withdrawals_status
                ON withdrawals(status);

            CREATE INDEX IF NOT EXISTS idx_submissions_task
                ON task_submissions(task_id);

            CREATE INDEX IF NOT EXISTS idx_submissions_user
                ON task_submissions(user_id);
            """
        )

        defaults = {
            "referral_reward": DEFAULT_REFERRAL_REWARD,
            "daily_bonus": DEFAULT_DAILY_BONUS,
            "min_withdraw": DEFAULT_MIN_WITHDRAW,
        }

        for key, value in defaults.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
                (key, str(value)),
            )

        conn.commit()
    finally:
        conn.close()


def get_setting(key: str, default: float) -> float:
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?",
            (key,),
        ).fetchone()
        if not row:
            return default
        try:
            return float(row["value"])
        except (TypeError, ValueError):
            return default
    finally:
        conn.close()


def set_setting(key: str, value: float):
    conn = get_db()
    try:
        conn.execute(
            """
            INSERT INTO settings(key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, str(value)),
        )
        conn.commit()
    finally:
        conn.close()


def now() -> int:
    return int(time.time())


# ============================================================
# USERS / BALANCE
# ============================================================

def upsert_user(
    user_id: int,
    username: str = "",
    first_name: str = "",
):
    timestamp = now()
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()

        if row:
            conn.execute(
                """
                UPDATE users
                SET username = ?, first_name = ?, last_seen = ?
                WHERE id = ?
                """,
                (username or "", first_name or "", timestamp, user_id),
            )
        else:
            conn.execute(
                """
                INSERT INTO users(
                    id, username, first_name, created_at, last_seen
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    username or "",
                    first_name or "",
                    timestamp,
                    timestamp,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def get_user(user_id: int):
    conn = get_db()
    try:
        return conn.execute(
            "SELECT * FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    finally:
        conn.close()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def is_banned(user_id: int) -> bool:
    user = get_user(user_id)
    return bool(user and user["banned"])


def add_balance(user_id: int, amount: float) -> bool:
    if amount == 0:
        return True

    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT id FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()

        if not row:
            conn.rollback()
            return False

        conn.execute(
            "UPDATE users SET balance = balance + ? WHERE id = ?",
            (amount, user_id),
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ============================================================
# REFERRALS
# ============================================================

def save_referral(user_id: int, referrer_id: int) -> bool:
    if user_id == referrer_id:
        return False

    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")

        referred = conn.execute(
            "SELECT referred_by FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()

        referrer = conn.execute(
            "SELECT id, banned FROM users WHERE id = ?",
            (referrer_id,),
        ).fetchone()

        if not referrer or referrer["banned"]:
            conn.rollback()
            return False

        if referred and referred["referred_by"]:
            conn.rollback()
            return False

        conn.execute(
            "UPDATE users SET referred_by = ? WHERE id = ?",
            (referrer_id, user_id),
        )

        conn.execute(
            """
            INSERT OR IGNORE INTO referrals(
                referrer_id, referred_id, reward, status, created_at
            )
            VALUES (?, ?, ?, 'pending', ?)
            """,
            (
                referrer_id,
                user_id,
                get_setting("referral_reward", DEFAULT_REFERRAL_REWARD),
                now(),
            ),
        )

        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def reward_referrer_after_verification(user_id: int) -> Optional[float]:
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")

        user = conn.execute(
            """
            SELECT referred_by, referral_reward_paid, verified
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        ).fetchone()

        if not user or not user["verified"] or user["referral_reward_paid"]:
            conn.rollback()
            return None

        referrer_id = user["referred_by"]
        if not referrer_id:
            conn.rollback()
            return None

        referrer = conn.execute(
            "SELECT id, banned FROM users WHERE id = ?",
            (referrer_id,),
        ).fetchone()

        if not referrer or referrer["banned"]:
            conn.rollback()
            return None

        reward = get_setting(
            "referral_reward",
            DEFAULT_REFERRAL_REWARD,
        )

        conn.execute(
            "UPDATE users SET balance = balance + ? WHERE id = ?",
            (reward, referrer_id),
        )

        conn.execute(
            """
            UPDATE users
            SET referral_reward_paid = 1
            WHERE id = ?
            """,
            (user_id,),
        )

        conn.execute(
            """
            UPDATE referrals
            SET status = 'paid', reward = ?, paid_at = ?
            WHERE referred_id = ? AND referrer_id = ?
            """,
            (reward, now(), user_id, referrer_id),
        )

        conn.commit()
        return reward
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_referral_count(user_id: int) -> int:
    conn = get_db()
    try:
        row = conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM referrals
            WHERE referrer_id = ? AND status = 'paid'
            """,
            (user_id,),
        ).fetchone()
        return int(row["total"])
    finally:
        conn.close()


# ============================================================
# DAILY BONUS
# ============================================================

def claim_daily_bonus(user_id: int):
    bonus = get_setting("daily_bonus", DEFAULT_DAILY_BONUS)
    cooldown = 86400

    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")

        user = conn.execute(
            """
            SELECT banned, last_daily_bonus
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        ).fetchone()

        if not user:
            conn.rollback()
            return False, "User not found."

        if user["banned"]:
            conn.rollback()
            return False, "Your account is restricted."

        current = now()
        last_claim = int(user["last_daily_bonus"] or 0)
        remaining = cooldown - (current - last_claim)

        if remaining > 0:
            hours = remaining // 3600
            minutes = (remaining % 3600) // 60
            conn.rollback()
            return False, f"Already claimed. Try again in {hours}h {minutes}m."

        conn.execute(
            """
            UPDATE users
            SET balance = balance + ?, last_daily_bonus = ?
            WHERE id = ?
            """,
            (bonus, current, user_id),
        )
        conn.commit()

        return True, bonus
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ============================================================
# WALLET
# ============================================================

def validate_wallet(wallet_type: str, wallet_number: str):
    wallet_type = wallet_type.strip().lower()
    wallet_number = re.sub(r"\s+", "", wallet_number.strip())

    if wallet_type == "cbe":
        if not re.fullmatch(r"1000\d{9}", wallet_number):
            return False, "CBE must be exactly 13 digits and start with 1000."
    elif wallet_type == "telebirr":
        if not re.fullmatch(r"(09|07)\d{8}", wallet_number):
            return False, "Telebirr must be exactly 10 digits and start with 09 or 07."
    else:
        return False, "Only CBE and Telebirr are supported."

    return True, wallet_number


def save_wallet(user_id: int, wallet_type: str, wallet_number: str):
    valid, value = validate_wallet(wallet_type, wallet_number)
    if not valid:
        return False, value, False

    wallet_type = wallet_type.strip().lower()

    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")

        duplicate = conn.execute(
            """
            SELECT id
            FROM users
            WHERE wallet_type = ?
              AND wallet_number = ?
              AND id != ?
              AND wallet_number != ''
            LIMIT 1
            """,
            (wallet_type, value, user_id),
        ).fetchone()

        suspicious = bool(duplicate)

        conn.execute(
            """
            UPDATE users
            SET wallet_type = ?, wallet_number = ?, wallet_suspicious = ?
            WHERE id = ?
            """,
            (wallet_type, value, int(suspicious), user_id),
        )

        conn.commit()
        return True, "Wallet saved successfully.", suspicious
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ============================================================
# TASKS
# ============================================================

def get_active_tasks(user_id: int):
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT
                t.*,
                COALESCE(ts.status, '') AS submission_status
            FROM tasks t
            LEFT JOIN task_submissions ts
                ON ts.task_id = t.id AND ts.user_id = ?
            WHERE t.active = 1
            ORDER BY t.id DESC
            """,
            (user_id,),
        ).fetchall()
        return rows
    finally:
        conn.close()


def create_task(title: str, description: str, link: str, reward: float):
    conn = get_db()
    try:
        cursor = conn.execute(
            """
            INSERT INTO tasks(title, description, link, reward, active, created_at)
            VALUES (?, ?, ?, ?, 1, ?)
            """,
            (title, description, link, reward, now()),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def submit_task(user_id: int, task_id: int, proof: str):
    proof = (proof or "").strip()

    if not proof:
        return False, "Please send proof."

    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")

        task = conn.execute(
            """
            SELECT id, active, reward
            FROM tasks
            WHERE id = ?
            """,
            (task_id,),
        ).fetchone()

        if not task or not task["active"]:
            conn.rollback()
            return False, "This task is no longer available."

        existing = conn.execute(
            """
            SELECT id, status
            FROM task_submissions
            WHERE task_id = ? AND user_id = ?
            """,
            (task_id, user_id),
        ).fetchone()

        if existing and existing["status"] == "pending":
            conn.rollback()
            return False, "Your previous submission is still pending."

        if existing and existing["status"] == "approved":
            conn.rollback()
            return False, "This task has already been approved."

        if existing:
            conn.execute(
                """
                UPDATE task_submissions
                SET proof = ?, status = 'pending', created_at = ?, reviewed_at = NULL
                WHERE id = ?
                """,
                (proof, now(), existing["id"]),
            )
        else:
            conn.execute(
                """
                INSERT INTO task_submissions(
                    task_id, user_id, proof, status, created_at
                )
                VALUES (?, ?, ?, 'pending', ?)
                """,
                (task_id, user_id, proof, now()),
            )

        conn.commit()
        return True, "Proof submitted. Waiting for admin review."
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_pending_submissions():
    conn = get_db()
    try:
        return conn.execute(
            """
            SELECT
                ts.*,
                t.title,
                t.reward,
                u.username,
                u.first_name
            FROM task_submissions ts
            JOIN tasks t ON t.id = ts.task_id
            JOIN users u ON u.id = ts.user_id
            WHERE ts.status = 'pending'
            ORDER BY ts.id DESC
            """
        ).fetchall()
    finally:
        conn.close()


def review_task_submission(submission_id: int, approve: bool, admin_id: int):
    if not is_admin(admin_id):
        return False, "Not authorized."

    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")

        submission = conn.execute(
            """
            SELECT
                ts.id,
                ts.user_id,
                ts.status,
                t.reward,
                t.title
            FROM task_submissions ts
            JOIN tasks t ON t.id = ts.task_id
            WHERE ts.id = ?
            """,
            (submission_id,),
        ).fetchone()

        if not submission:
            conn.rollback()
            return False, "Submission not found."

        if submission["status"] != "pending":
            conn.rollback()
            return False, "This submission was already reviewed."

        if approve:
            conn.execute(
                """
                UPDATE users
                SET balance = balance + ?
                WHERE id = ?
                """,
                (submission["reward"], submission["user_id"]),
            )
            conn.execute(
                """
                UPDATE task_submissions
                SET status = 'approved', reviewed_at = ?
                WHERE id = ?
                """,
                (now(), submission_id),
            )
            conn.commit()
            return True, {
                "user_id": submission["user_id"],
                "reward": float(submission["reward"]),
                "title": submission["title"],
                "status": "approved",
            }

        conn.execute(
            """
            UPDATE task_submissions
            SET status = 'rejected', reviewed_at = ?
            WHERE id = ?
            """,
            (now(), submission_id),
        )
        conn.commit()

        return True, {
            "user_id": submission["user_id"],
            "reward": 0,
            "title": submission["title"],
            "status": "rejected",
        }

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ============================================================
# WITHDRAWALS
# ============================================================

def has_pending_withdrawal(user_id: int) -> bool:
    conn = get_db()
    try:
        row = conn.execute(
            """
            SELECT id
            FROM withdrawals
            WHERE user_id = ? AND status = 'pending'
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()
        return bool(row)
    finally:
        conn.close()


def create_withdrawal(user_id: int, amount: float):
    minimum = get_setting("min_withdraw", DEFAULT_MIN_WITHDRAW)

    try:
        amount = round(float(amount), 2)
    except (TypeError, ValueError):
        return False, "Invalid amount."

    if amount < minimum:
        return False, f"Minimum withdrawal is {minimum:.2f} ETB."

    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")

        user = conn.execute(
            """
            SELECT balance, wallet_type, wallet_number, wallet_suspicious, banned
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        ).fetchone()

        if not user:
            conn.rollback()
            return False, "User not found."

        if user["banned"]:
            conn.rollback()
            return False, "Your account is restricted."

        if not user["wallet_type"] or not user["wallet_number"]:
            conn.rollback()
            return False, "Please set your wallet first."

        if has_pending_withdrawal(user_id):
            conn.rollback()
            return False, "You already have a pending withdrawal."

        balance = float(user["balance"] or 0)

        if amount > balance:
            conn.rollback()
            return False, "Insufficient balance."

        cursor = conn.execute(
            """
            INSERT INTO withdrawals(
                user_id, amount, wallet_type, wallet_number, status, created_at
            )
            VALUES (?, ?, ?, ?, 'pending', ?)
            """,
            (
                user_id,
                amount,
                user["wallet_type"],
                user["wallet_number"],
                now(),
            ),
        )

        conn.execute(
            """
            UPDATE users
            SET balance = balance - ?
            WHERE id = ?
            """,
            (amount, user_id),
        )

        conn.commit()

        return True, {
            "withdrawal_id": cursor.lastrowid,
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


def review_withdrawal(withdrawal_id: int, approve: bool, admin_id: int):
    if not is_admin(admin_id):
        return False, "Not authorized."

    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")

        row = conn.execute(
            """
            SELECT *
            FROM withdrawals
            WHERE id = ?
            """,
            (withdrawal_id,),
        ).fetchone()

        if not row:
            conn.rollback()
            return False, "Withdrawal not found."

        if row["status"] != "pending":
            conn.rollback()
            return False, "This withdrawal was already reviewed."

        if approve:
            conn.execute(
                """
                UPDATE withdrawals
                SET status = 'approved', reviewed_at = ?, reviewed_by = ?
                WHERE id = ?
                """,
                (now(), admin_id, withdrawal_id),
            )
            conn.commit()
            return True, dict(row) | {"status": "approved"}

        conn.execute(
            """
            UPDATE users
            SET balance = balance + ?
            WHERE id = ?
            """,
            (row["amount"], row["user_id"]),
        )

        conn.execute(
            """
            UPDATE withdrawals
            SET status = 'rejected', reviewed_at = ?, reviewed_by = ?
            WHERE id = ?
            """,
            (now(), admin_id, withdrawal_id),
        )

        conn.commit()
        return True, dict(row) | {"status": "rejected"}

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ============================================================
# BAN / ADMIN
# ============================================================

def set_ban(user_id: int, banned: bool):
    conn = get_db()
    try:
        conn.execute(
            "UPDATE users SET banned = ? WHERE id = ?",
            (int(banned), user_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_admin_stats():
    conn = get_db()
    try:
        users = conn.execute(
            "SELECT COUNT(*) AS n FROM users"
        ).fetchone()["n"]

        verified = conn.execute(
            "SELECT COUNT(*) AS n FROM users WHERE verified = 1"
        ).fetchone()["n"]

        banned = conn.execute(
            "SELECT COUNT(*) AS n FROM users WHERE banned = 1"
        ).fetchone()["n"]

        balance = conn.execute(
            "SELECT COALESCE(SUM(balance), 0) AS n FROM users"
        ).fetchone()["n"]

        pending_withdrawals = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM withdrawals
            WHERE status = 'pending'
            """
        ).fetchone()["n"]

        pending_tasks = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM task_submissions
            WHERE status = 'pending'
            """
        ).fetchone()["n"]

        return {
            "users": int(users),
            "verified": int(verified),
            "banned": int(banned),
            "balance": float(balance or 0),
            "pending_withdrawals": int(pending_withdrawals),
            "pending_tasks": int(pending_tasks),
        }
    finally:
        conn.close()


# ============================================================
# TELEGRAM API
# ============================================================

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"


async def telegram_request(method: str, data: Optional[dict] = None):
    if not BOT_TOKEN:
        return {
            "ok": False,
            "description": "BOT_TOKEN environment variable is missing.",
        }

    try:
        async with httpx.AsyncClient(timeout=25) as client:
            response = await client.post(
                f"{TELEGRAM_API}/{method}",
                json=data or {},
            )
            return response.json()
    except Exception as exc:
        return {
            "ok": False,
            "description": str(exc),
        }


async def send_message(
    chat_id: int,
    text: str,
    reply_markup: Optional[dict] = None,
):
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    if reply_markup:
        data["reply_markup"] = reply_markup

    return await telegram_request("sendMessage", data)


async def answer_callback(callback_id: str, text: str = "", show_alert=False):
    return await telegram_request(
        "answerCallbackQuery",
        {
            "callback_query_id": callback_id,
            "text": text,
            "show_alert": show_alert,
        },
    )


async def edit_message(
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup: Optional[dict] = None,
):
    data = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    if reply_markup:
        data["reply_markup"] = reply_markup

    return await telegram_request("editMessageText", data)


async def send_admin_message(text: str, reply_markup: Optional[dict] = None):
    results = []
    for admin_id in ADMIN_IDS:
        results.append(
            await send_message(admin_id, text, reply_markup)
        )
    return results


# ============================================================
# TELEGRAM KEYBOARDS
# ============================================================

def main_keyboard():
    return {
        "keyboard": [
            [
                {"text": "💰 Balance"},
                {"text": "🎁 Daily Bonus"},
            ],
            [
                {"text": "👥 Invite Friends"},
                {"text": "📋 Tasks"},
            ],
            [
                {"text": "👛 Wallet"},
                {"text": "💸 Withdraw"},
            ],
            [
                {"text": "❓ Help"},
                {"text": "🆘 Support"},
            ],
        ],
        "resize_keyboard": True,
    }


def admin_keyboard():
    return {
        "keyboard": [
            [
                {"text": "📊 Admin Stats"},
                {"text": "📥 Pending Withdrawals"},
            ],
            [
                {"text": "📝 Pending Tasks"},
                {"text": "🔙 User Menu"},
            ],
        ],
        "resize_keyboard": True,
    }


def withdrawal_keyboard(withdrawal_id: int):
    return {
        "inline_keyboard": [
            [
                {
                    "text": "✅ Approve",
                    "callback_data": f"wd:approve:{withdrawal_id}",
                },
                {
                    "text": "❌ Reject",
                    "callback_data": f"wd:reject:{withdrawal_id}",
                },
            ]
        ]
    }


def task_review_keyboard(submission_id: int):
    return {
        "inline_keyboard": [
            [
                {
                    "text": "✅ Approve",
                    "callback_data": f"task:approve:{submission_id}",
                },
                {
                    "text": "❌ Reject",
                    "callback_data": f"task:reject:{submission_id}",
                },
            ]
        ]
    }


# ============================================================
# MESSAGES
# ============================================================

def welcome_text():
    return (
        "🦅 <b>WELCOME TO FALCON WORLD</b>\n\n"
        "💰 Earn & Complete Tasks\n"
        "🎁 Daily Rewards\n"
        "👥 Referral Rewards\n"
        "🚀 New Opportunities\n\n"
        "💱 <b>USDT Exchange:</b> Buy & Sell\n"
        f"📢 <b>Ads & Promotions:</b> {html.escape(SUPPORT_USERNAME)}\n\n"
        "🚀 Open Falcon World from the menu below."
    )


def help_text():
    return (
        "❓ <b>Falcon World Help</b>\n\n"
        "💰 <b>Balance</b> — Check your current ETB balance.\n"
        "🎁 <b>Daily Bonus</b> — Claim 0.50 ETB once every 24 hours.\n"
        "👥 <b>Invite Friends</b> — Invite friends and earn referral rewards "
        "after they complete verification.\n"
        "📋 <b>Tasks</b> — Complete available tasks and submit proof.\n"
        "👛 <b>Wallet</b> — Save your CBE or Telebirr wallet.\n"
        "💸 <b>Withdraw</b> — Request withdrawal when you reach the minimum.\n\n"
        f"🆘 Support: {html.escape(SUPPORT_USERNAME)}"
    )


def balance_text(user_id: int):
    user = get_user(user_id)
    if not user:
        return "User not found."

    count = get_referral_count(user_id)

    return (
        f"💰 <b>Your Balance</b>\n\n"
        f"💵 Balance: <b>{float(user['balance']):.2f} ETB</b>\n"
        f"👥 Paid Referrals: <b>{count}</b>\n"
    )


def referral_text(user_id: int):
    count = get_referral_count(user_id)
    link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"
    reward = get_setting("referral_reward", DEFAULT_REFERRAL_REWARD)

    return (
        "👥 <b>Invite Friends</b>\n\n"
        f"🎁 Reward: <b>{reward:.2f} ETB</b> per verified referral\n"
        f"👤 Paid referrals: <b>{count}</b>\n\n"
        "🔗 <b>Your referral link:</b>\n"
        f"<code>{html.escape(link)}</code>\n\n"
        "Share the link with your friends."
    )


def wallet_text(user_id: int):
    user = get_user(user_id)
    if not user:
        return "User not found."

    wallet_type = user["wallet_type"] or "Not set"
    wallet_number = user["wallet_number"] or "Not set"

    return (
        "👛 <b>Wallet Settings</b>\n\n"
        f"Type: <b>{html.escape(wallet_type)}</b>\n"
        f"Number: <code>{html.escape(wallet_number)}</code>\n\n"
        "Supported:\n"
        "• CBE — 13 digits, starts with 1000\n"
        "• Telebirr — 10 digits, starts with 09 or 07"
    )


# ============================================================
# COMMAND HELPERS
# ============================================================

async def process_start(chat_id: int, user_data: dict, args: str):
    user_id = int(user_data["id"])
    username = user_data.get("username", "")
    first_name = user_data.get("first_name", "")

    upsert_user(user_id, username, first_name)

    if is_banned(user_id):
        await send_message(
            chat_id,
            "🚫 <b>Your account is restricted.</b>\n\n"
            f"Contact {html.escape(SUPPORT_USERNAME)} for support.",
        )
        return

    args = (args or "").strip()

    if args.startswith("ref_"):
        ref_part = args[4:].strip()
        if ref_part.isdigit():
            save_referral(user_id, int(ref_part))

    await send_message(
        chat_id,
        welcome_text(),
        {
            "inline_keyboard": [
                [
                    {
                        "text": "🚀 Open Falcon World",
                        "web_app": {"url": MINI_APP_URL},
                    }
                ]
            ]
        },
    )


async def process_text_message(chat_id: int, user_id: int, text: str):
    if is_banned(user_id):
        await send_message(
            chat_id,
            "🚫 Your account is restricted.",
        )
        return

    if text == "💰 Balance":
        await send_message(chat_id, balance_text(user_id))
        return

    if text == "🎁 Daily Bonus":
        success, result = claim_daily_bonus(user_id)
        if success:
            await send_message(
                chat_id,
                f"🎁 <b>Daily Bonus Claimed!</b>\n\n"
                f"💰 +{float(result):.2f} ETB\n"
                f"💵 {balance_text(user_id)}",
                main_keyboard(),
            )
        else:
            await send_message(
                chat_id,
                f"🎁 <b>Daily Bonus</b>\n\n{html.escape(str(result))}",
                main_keyboard(),
            )
        return

    if text == "👥 Invite Friends":
        await send_message(chat_id, referral_text(user_id))
        return

    if text == "📋 Tasks":
        tasks = get_active_tasks(user_id)

        if not tasks:
            await send_message(
                chat_id,
                "📋 <b>Tasks</b>\n\nNo active tasks right now.",
            )
            return

        lines = ["📋 <b>Available Tasks</b>\n"]

        for task in tasks:
            status = task["submission_status"]
            if status == "pending":
                status_text = "⏳ Pending"
            elif status == "approved":
                status_text = "✅ Approved"
            elif status == "rejected":
                status_text = "❌ Rejected — you can resubmit"
            else:
                status_text = "🆕 Available"

            lines.append(
                f"<b>#{task['id']} — {html.escape(task['title'])}</b>\n"
                f"💰 Reward: {float(task['reward']):.2f} ETB\n"
                f"📌 Status: {status_text}\n"
                f"🔗 {html.escape(task['link'] or 'No link')}\n"
            )

        await send_message(
            chat_id,
            "\n".join(lines)
            + "\n\nTo submit proof, send:\n"
            "<code>/submit TASK_ID your proof</code>",
        )
        return

    if text == "👛 Wallet":
        await send_message(
            chat_id,
            wallet_text(user_id)
            + "\n\n"
            "To save/update wallet:\n"
            "<code>/wallet cbe 1000XXXXXXXXX</code>\n"
            "or\n"
            "<code>/wallet telebirr 09XXXXXXXX</code>",
        )
        return

    if text == "💸 Withdraw":
        minimum = get_setting(
            "min_withdraw",
            DEFAULT_MIN_WITHDRAW,
        )
        await send_message(
            chat_id,
            f"💸 <b>Withdraw</b>\n\n"
            f"Minimum: <b>{minimum:.2f} ETB</b>\n\n"
            "Set your wallet first, then send:\n"
            "<code>/withdraw AMOUNT</code>\n\n"
            "Example:\n"
            "<code>/withdraw 100</code>",
        )
        return

    if text == "❓ Help":
        await send_message(chat_id, help_text())
        return

    if text == "🆘 Support":
        await send_message(
            chat_id,
            f"🆘 <b>Support</b>\n\n"
            f"Contact: {html.escape(SUPPORT_USERNAME)}",
        )
        return

    await send_message(
        chat_id,
        "Please use the buttons below.",
        main_keyboard(),
    )


# ============================================================
# ADMIN COMMANDS
# ============================================================

async def handle_admin_command(chat_id: int, user_id: int, text: str):
    if not is_admin(user_id):
        return False

    parts = text.split(maxsplit=1)
    command = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if command == "/admin":
        stats = get_admin_stats()

        await send_message(
            chat_id,
            "🛠 <b>Falcon World Admin</b>\n\n"
            f"👤 Users: <b>{stats['users']}</b>\n"
            f"✅ Verified: <b>{stats['verified']}</b>\n"
            f"🚫 Banned: <b>{stats['banned']}</b>\n"
            f"💰 Total balance: <b>{stats['balance']:.2f} ETB</b>\n"
            f"💸 Pending withdrawals: <b>{stats['pending_withdrawals']}</b>\n"
            f"📋 Pending tasks: <b>{stats['pending_tasks']}</b>\n\n"
            "Commands:\n"
            "/checkuser ID\n"
            "/addbalance ID AMOUNT\n"
            "/ban ID\n"
            "/unban ID\n"
            "/addtask Title | Link | Reward\n"
            "/setref AMOUNT\n"
            "/setdaily AMOUNT\n"
            "/setminwithdraw AMOUNT\n"
            "/broadcast MESSAGE",
            admin_keyboard(),
        )
        return True

    if command == "/checkuser":
        if not arg.isdigit():
            await send_message(chat_id, "Usage: /checkuser USER_ID")
            return True

        target_id = int(arg)
        user = get_user(target_id)

        if not user:
            await send_message(chat_id, "User not found.")
            return True

        await send_message(
            chat_id,
            f"👤 <b>User</b>\n\n"
            f"ID: <code>{user['id']}</code>\n"
            f"Name: {html.escape(user['first_name'] or '-')}\n"
            f"Username: @{html.escape(user['username'] or '-')}\n"
            f"Balance: <b>{float(user['balance']):.2f} ETB</b>\n"
            f"Verified: {bool(user['verified'])}\n"
            f"Banned: {bool(user['banned'])}\n"
            f"Wallet: {html.escape(user['wallet_type'] or '-')}"
            f" / <code>{html.escape(user['wallet_number'] or '-')}</code>\n"
            f"Suspicious wallet: {bool(user['wallet_suspicious'])}",
        )
        return True

    if command == "/addbalance":
        bits = arg.split()
        if len(bits) != 2 or not bits[0].isdigit():
            await send_message(chat_id, "Usage: /addbalance USER_ID AMOUNT")
            return True

        try:
            target_id = int(bits[0])
            amount = float(bits[1])
        except ValueError:
            await send_message(chat_id, "Invalid amount.")
            return True

        if not add_balance(target_id, amount):
            await send_message(chat_id, "User not found.")
            return True

        await send_message(
            chat_id,
            f"✅ Added <b>{amount:.2f} ETB</b> to <code>{target_id}</code>.",
        )
        await send_message(
            target_id,
            f"💰 Your balance was updated by admin.\n"
            f"Amount: <b>{amount:.2f} ETB</b>",
        )
        return True

    if command in {"/ban", "/unban"}:
        if not arg.isdigit():
            await send_message(chat_id, f"Usage: {command} USER_ID")
            return True

        target_id = int(arg)
        set_ban(target_id, command == "/ban")

        await send_message(
            chat_id,
            "✅ Done.",
        )

        if command == "/ban":
            await send_message(
                target_id,
                "🚫 Your Falcon World account has been restricted.",
            )
        else:
            await send_message(
                target_id,
                "✅ Your Falcon World account has been restored.",
            )
        return True

    if command == "/addtask":
        fields = [x.strip() for x in arg.split("|")]

        if len(fields) != 3:
            await send_message(
                chat_id,
                "Usage:\n"
                "/addtask Title | Link | Reward\n\n"
                "Example:\n"
                "/addtask Join Channel | https://t.me/example | 5",
            )
            return True

        title, link, reward_text = fields

        try:
            reward = float(reward_text)
        except ValueError:
            await send_message(chat_id, "Invalid reward.")
            return True

        if reward <= 0:
            await send_message(chat_id, "Reward must be greater than 0.")
            return True

        task_id = create_task(
            title=title,
            description="",
            link=link,
            reward=reward,
        )

        await send_message(
            chat_id,
            f"✅ Task created successfully.\nTask ID: <b>#{task_id}</b>",
        )
        return True

    if command == "/setref":
        try:
            value = float(arg)
            if value < 0:
                raise ValueError
        except ValueError:
            await send_message(chat_id, "Usage: /setref AMOUNT")
            return True

        set_setting("referral_reward", value)
        await send_message(
            chat_id,
            f"✅ Referral reward set to <b>{value:.2f} ETB</b>.",
        )
        return True

    if command == "/setdaily":
        try:
            value = float(arg)
            if value < 0:
                raise ValueError
        except ValueError:
            await send_message(chat_id, "Usage: /setdaily AMOUNT")
            return True

        set_setting("daily_bonus", value)
        await send_message(
            chat_id,
            f"✅ Daily bonus set to <b>{value:.2f} ETB</b>.",
        )
        return True

    if command == "/setminwithdraw":
        try:
            value = float(arg)
            if value <= 0:
                raise ValueError
        except ValueError:
            await send_message(chat_id, "Usage: /setminwithdraw AMOUNT")
            return True

        set_setting("min_withdraw", value)
        await send_message(
            chat_id,
            f"✅ Minimum withdrawal set to <b>{value:.2f} ETB</b>.",
        )
        return True

    if command == "/broadcast":
        if not arg:
            await send_message(chat_id, "Usage: /broadcast MESSAGE")
            return True

        conn = get_db()
        try:
            users = conn.execute(
                "SELECT id FROM users WHERE banned = 0"
            ).fetchall()
        finally:
            conn.close()

        sent = 0
        failed = 0

        for row in users:
            result = await send_message(
                int(row["id"]),
                f"📢 <b>Falcon World Announcement</b>\n\n{html.escape(arg)}",
            )
            if result.get("ok"):
                sent += 1
            else:
                failed += 1

        await send_message(
            chat_id,
            f"📢 Broadcast finished.\n\n"
            f"✅ Sent: {sent}\n"
            f"❌ Failed: {failed}",
        )
        return True

    return False


# ============================================================
# CALLBACKS
# ============================================================

async def handle_callback(update: dict):
    callback = update.get("callback_query") or {}
    callback_id = callback.get("id")
    data = callback.get("data", "")
    user = callback.get("from") or {}
    user_id = int(user.get("id", 0))

    if not callback_id:
        return

    if not is_admin(user_id):
        await answer_callback(
            callback_id,
            "Not authorized.",
            True,
        )
        return

    parts = data.split(":")
    if len(parts) != 3:
        await answer_callback(callback_id, "Invalid action.", True)
        return

    action_type, action, item_id_text = parts

    try:
        item_id = int(item_id_text)
    except ValueError:
        await answer_callback(callback_id, "Invalid ID.", True)
        return

    message = callback.get("message") or {}
    chat_id = message.get("chat", {}).get("id")
    message_id = message.get("message_id")

    if action_type == "wd":
        approve = action == "approve"
        success, result = review_withdrawal(
            item_id,
            approve,
            user_id,
        )

        if not success:
            await answer_callback(
                callback_id,
                str(result),
                True,
            )
            return

        target_user = int(result["user_id"])
        amount = float(result["amount"])

        if approve:
            await send_message(
                target_user,
                f"✅ <b>Withdrawal Approved</b>\n\n"
                f"Amount: <b>{amount:.2f} ETB</b>",
            )
            text = (
                f"✅ <b>Withdrawal #{item_id} approved</b>\n\n"
                f"Amount: {amount:.2f} ETB"
            )
        else:
            await send_message(
                target_user,
                f"❌ <b>Withdrawal Rejected</b>\n\n"
                f"Amount: <b>{amount:.2f} ETB</b>\n"
                "The amount has been returned to your balance.",
            )
            text = (
                f"❌ <b>Withdrawal #{item_id} rejected</b>\n\n"
                f"Refunded: {amount:.2f} ETB"
            )

        await answer_callback(callback_id, "Done.")

        if chat_id and message_id:
            await edit_message(chat_id, message_id, text)

        return

    if action_type == "task":
        approve = action == "approve"
        success, result = review_task_submission(
            item_id,
            approve,
            user_id,
        )

        if not success:
            await answer_callback(
                callback_id,
                str(result),
                True,
            )
            return

        target_user = int(result["user_id"])
        reward = float(result["reward"])

        if approve:
            await send_message(
                target_user,
                f"✅ <b>Task Approved</b>\n\n"
                f"Task: {html.escape(result['title'])}\n"
                f"Reward: <b>+{reward:.2f} ETB</b>",
            )
            text = (
                f"✅ <b>Task #{item_id} approved</b>\n"
                f"Reward: {reward:.2f} ETB"
            )
        else:
            await send_message(
                target_user,
                f"❌ <b>Task Rejected</b>\n\n"
                f"Task: {html.escape(result['title'])}\n"
                "You may submit new proof.",
            )
            text = f"❌ <b>Task #{item_id} rejected</b>"

        await answer_callback(callback_id, "Done.")

        if chat_id and message_id:
            await edit_message(chat_id, message_id, text)

        return

    await answer_callback(callback_id, "Unknown action.", True)


# ============================================================
# ADMIN LISTS
# ============================================================

async def send_pending_withdrawals(chat_id: int):
    conn = get_db()
    try:
        rows = conn.execute(
            """
            SELECT w.*, u.username, u.first_name
            FROM withdrawals w
            JOIN users u ON u.id = w.user_id
            WHERE w.status = 'pending'
            ORDER BY w.id DESC
            LIMIT 30
            """
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        await send_message(chat_id, "📥 No pending withdrawals.")
        return

    for row in rows:
        name = row["first_name"] or row["username"] or str(row["user_id"])

        text = (
            f"💸 <b>Withdrawal #{row['id']}</b>\n\n"
            f"👤 {html.escape(name)}\n"
            f"🆔 <code>{row['user_id']}</code>\n"
            f"💰 Amount: <b>{float(row['amount']):.2f} ETB</b>\n"
            f"👛 {html.escape(row['wallet_type'])}: "
            f"<code>{html.escape(row['wallet_number'])}</code>"
        )

        await send_message(
            chat_id,
            text,
            withdrawal_keyboard(int(row["id"])),
        )


async def send_pending_tasks(chat_id: int):
    rows = get_pending_submissions()

    if not rows:
        await send_message(chat_id, "📝 No pending task submissions.")
        return

    for row in rows[:30]:
        name = row["first_name"] or row["username"] or str(row["user_id"])

        text = (
            f"📝 <b>Task Submission #{row['id']}</b>\n\n"
            f"👤 {html.escape(name)}\n"
            f"🆔 <code>{row['user_id']}</code>\n"
            f"Task: <b>{html.escape(row['title'])}</b>\n"
            f"Reward: <b>{float(row['reward']):.2f} ETB</b>\n\n"
            f"<b>Proof:</b>\n{html.escape(row['proof'])}"
        )

        await send_message(
            chat_id,
            text,
            task_review_keyboard(int(row["id"])),
        )


# ============================================================
# UPDATE HANDLER
# ============================================================

async def handle_update(update: dict):
    """
    Main webhook update handler.
    server.py should call this function after receiving Telegram's update.
    """
    try:
        if update.get("callback_query"):
            await handle_callback(update)
            return

        message = update.get("message")
        if not message:
            return

        chat = message.get("chat") or {}
        chat_id = chat.get("id")

        if not chat_id:
            return

        user = message.get("from") or {}
        user_id = int(user.get("id", 0))

        if not user_id:
            return

        username = user.get("username", "")
        first_name = user.get("first_name", "")

        upsert_user(user_id, username, first_name)

        text = message.get("text", "") or ""

        # Admin commands/buttons
        if is_admin(user_id):
            if text == "📊 Admin Stats":
                await handle_admin_command(chat_id, user_id, "/admin")
                return

            if text == "📥 Pending Withdrawals":
                await send_pending_withdrawals(chat_id)
                return

            if text == "📝 Pending Tasks":
                await send_pending_tasks(chat_id)
                return

            if text == "🔙 User Menu":
                await send_message(
                    chat_id,
                    "👤 User menu restored.",
                    main_keyboard(),
                )
                return

            if text.startswith("/"):
                handled = await handle_admin_command(
                    chat_id,
                    user_id,
                    text,
                )
                if handled:
                    return

        # Standard commands
        if text.startswith("/start"):
            args = text.split(maxsplit=1)
            start_arg = args[1] if len(args) > 1 else ""
            await process_start(
                chat_id,
                user,
                start_arg,
            )

            if is_admin(user_id):
                await send_message(
                    chat_id,
                    "🛠 Admin menu available.",
                    admin_keyboard(),
                )
            else:
                await send_message(
                    chat_id,
                    "Choose an option:",
                    main_keyboard(),
                )
            return

        if text == "/help":
            await send_message(chat_id, help_text())
            return

        if text.startswith("/submit"):
            parts = text.split(maxsplit=2)

            if len(parts) < 3 or not parts[1].isdigit():
                await send_message(
                    chat_id,
                    "Usage:\n<code>/submit TASK_ID your proof</code>",
                )
                return

            task_id = int(parts[1])
            proof = parts[2]

            success, result = submit_task(
                user_id,
                task_id,
                proof,
            )

            await send_message(
                chat_id,
                ("✅ " if success else "❌ ") + html.escape(str(result)),
            )

            if success:
                rows = get_pending_submissions()
                for row in rows:
                    if (
                        int(row["task_id"]) == task_id
                        and int(row["user_id"]) == user_id
                        and row["status"] == "pending"
                    ):
                        await send_admin_message(
                            f"📝 <b>New Task Proof</b>\n\n"
                            f"User: {html.escape(row['first_name'] or row['username'] or str(user_id))}\n"
                            f"User ID: <code>{user_id}</code>\n"
                            f"Task: <b>{html.escape(row['title'])}</b>\n"
                            f"Reward: <b>{float(row['reward']):.2f} ETB</b>\n\n"
                            f"Proof:\n{html.escape(row['proof'])}",
                            task_review_keyboard(int(row["id"])),
                        )
                        break
            return

        if text.startswith("/wallet"):
            parts = text.split(maxsplit=2)

            if len(parts) != 3:
                await send_message(
                    chat_id,
                    "Usage:\n"
                    "<code>/wallet cbe 1000XXXXXXXXX</code>\n"
                    "or\n"
                    "<code>/wallet telebirr 09XXXXXXXX</code>",
                )
                return

            wallet_type = parts[1]
            wallet_number = parts[2]

            success, result, suspicious = save_wallet(
                user_id,
                wallet_type,
                wallet_number,
            )

            if success:
                await send_message(
                    chat_id,
                    f"✅ {html.escape(result)}"
                    + (
                        "\n⚠️ This wallet is already linked to another account. "
                        "It has been flagged for review."
                        if suspicious else ""
                    ),
                )

                if suspicious:
                    await send_admin_message(
                        "⚠️ <b>Duplicate Wallet Alert</b>\n\n"
                        f"User ID: <code>{user_id}</code>\n"
                        f"Wallet: {html.escape(wallet_type)} "
                        f"<code>{html.escape(re.sub(r'\\s+', '', wallet_number))}</code>"
                    )
            else:
                await send_message(
                    chat_id,
                    f"❌ {html.escape(result)}",
                )
            return

        if text.startswith("/withdraw"):
            parts = text.split(maxsplit=1)

            if len(parts) != 2:
                await send_message(
                    chat_id,
                    "Usage: <code>/withdraw AMOUNT</code>",
                )
                return

            success, result = create_withdrawal(
                user_id,
                float(parts[1]) if re.fullmatch(r"\d+(\.\d+)?", parts[1]) else -1,
            )

            if not success:
                await send_message(
                    chat_id,
                    f"❌ {html.escape(str(result))}",
                )
                return

            withdrawal_id = int(result["withdrawal_id"])
            amount = float(result["amount"])

            await send_message(
                chat_id,
                f"✅ <b>Withdrawal Submitted</b>\n\n"
                f"ID: <code>#{withdrawal_id}</code>\n"
                f"Amount: <b>{amount:.2f} ETB</b>\n"
                f"Wallet: {html.escape(result['wallet_type'])}\n"
                f"Status: ⏳ Pending",
            )

            await send_admin_message(
                f"💸 <b>New Withdrawal Request</b>\n\n"
                f"ID: <code>#{withdrawal_id}</code>\n"
                f"User ID: <code>{user_id}</code>\n"
                f"Amount: <b>{amount:.2f} ETB</b>\n"
                f"Wallet: {html.escape(result['wallet_type'])}\n"
                f"Number: <code>{html.escape(result['wallet_number'])}</code>"
                + (
                    "\n⚠️ <b>Wallet flagged as duplicate.</b>"
                    if result["suspicious"] else ""
                ),
                withdrawal_keyboard(withdrawal_id),
            )
            return

        await process_text_message(
            chat_id,
            user_id,
            text,
        )

    except Exception as exc:
        print("handle_update error:", repr(exc))


# ============================================================
# STARTUP HELPERS
# ============================================================

async def configure_bot():
    init_db()

    await telegram_request(
        "setMyCommands",
        {
            "commands": [
                {
                    "command": "start",
                    "description": "Start Falcon World",
                },
                {
                    "command": "help",
                    "description": "Help and support",
                },
            ]
        },
    )

    await telegram_request(
        "setChatMenuButton",
        {
            "menu_button": {
                "type": "web_app",
                "text": "🚀 Open Falcon",
                "web_app": {
                    "url": MINI_APP_URL,
                },
            }
        },
    )


if __name__ == "__main__":
    init_db()
    print("Falcon World bot backend initialized.")
    print("Run the FastAPI server with:")
    print("uvicorn server:app --host 0.0.0.0 --port $PORT")
