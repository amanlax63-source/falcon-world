import os
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel


# ============================================================
# FALCON WORLD - SERVER
# ============================================================

app = FastAPI(title="Falcon World API", version="1.0.0")


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BOT_USERNAME = os.getenv("BOT_USERNAME", "FalconWorld_Bot")

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "Aman_M12")

DAILY_BONUS = 0.50
REFERRAL_REWARD = 2.00
MIN_WITHDRAW = 30.00

DB_FILE = "falcon_world.db"


# Required Telegram channels
REQUIRED_CHANNELS = [
    {
        "username": "@ethiocashflow",
        "name": "Ethio Cash Flow",
        "url": "https://t.me/ethiocashflow",
    },
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


# ============================================================
# DATABASE
# ============================================================

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id TEXT UNIQUE NOT NULL,
            username TEXT DEFAULT '',
            first_name TEXT DEFAULT '',
            balance REAL DEFAULT 0,
            referral_count INTEGER DEFAULT 0,
            referred_by TEXT DEFAULT '',
            daily_claim TEXT DEFAULT '',
            cbe TEXT DEFAULT '',
            telebirr TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id TEXT NOT NULL,
            amount REAL NOT NULL,
            method TEXT NOT NULL,
            account TEXT NOT NULL,
            status TEXT DEFAULT 'Pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            reward REAL DEFAULT 0,
            url TEXT DEFAULT '',
            active INTEGER DEFAULT 1
        )
        """
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS completed_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id TEXT NOT NULL,
            task_id INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(telegram_id, task_id)
        )
        """
    )

    # Add default task if empty
    task_count = conn.execute(
        "SELECT COUNT(*) AS c FROM tasks"
    ).fetchone()["c"]

    if task_count == 0:
        conn.execute(
            """
            INSERT INTO tasks (title, reward, url, active)
            VALUES (?, ?, ?, ?)
            """,
            (
                "Coming Soon",
                0,
                "",
                0,
            ),
        )

    conn.commit()
    conn.close()


init_db()


# ============================================================
# MODELS
# ============================================================

class RegisterRequest(BaseModel):
    telegram_id: str
    username: Optional[str] = ""
    first_name: Optional[str] = ""
    referral: Optional[str] = ""


class WalletRequest(BaseModel):
    telegram_id: str
    cbe: Optional[str] = ""
    telebirr: Optional[str] = ""


class WithdrawRequest(BaseModel):
    telegram_id: str
    amount: float
    method: str
    account: str


class DailyBonusRequest(BaseModel):
    telegram_id: str


class ReferralRequest(BaseModel):
    telegram_id: str


class TaskRequest(BaseModel):
    telegram_id: str
    task_id: int


# ============================================================
# HELPERS
# ============================================================

def get_user(telegram_id: str):
    conn = get_db()

    user = conn.execute(
        "SELECT * FROM users WHERE telegram_id = ?",
        (str(telegram_id),),
    ).fetchone()

    conn.close()
    return user


def user_dict(user):
    if not user:
        return None

    return {
        "telegram_id": user["telegram_id"],
        "username": user["username"],
        "first_name": user["first_name"],
        "balance": round(float(user["balance"]), 2),
        "referral_count": int(user["referral_count"]),
        "cbe": user["cbe"],
        "telebirr": user["telebirr"],
        "created_at": user["created_at"],
    }


def valid_cbe(value: str) -> bool:
    value = value.strip()

    return (
        len(value) == 13
        and value.isdigit()
        and value.startswith("1000")
    )


def valid_telebirr(value: str) -> bool:
    value = value.strip()

    return (
        len(value) == 10
        and value.isdigit()
        and (
            value.startswith("09")
            or value.startswith("07")
        )
    )


# ============================================================
# TELEGRAM API
# ============================================================

async def telegram_request(method: str, data: dict):
    if not BOT_TOKEN:
        return {
            "ok": False,
            "description": "BOT_TOKEN is not configured"
        }

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(url, data=data)

            return response.json()

    except Exception as e:
        return {
            "ok": False,
            "description": str(e)
        }


async def check_channel_membership(
    telegram_id: str,
    channel_username: str
):
    result = await telegram_request(
        "getChatMember",
        {
            "chat_id": channel_username,
            "user_id": telegram_id,
        },
    )

    if not result.get("ok"):
        return False

    member = result.get("result", {})
    status = member.get("status", "")

    return status in {
        "creator",
        "administrator",
        "member",
    }


async def check_all_channels(telegram_id: str):
    results = []

    for channel in REQUIRED_CHANNELS:
        joined = await check_channel_membership(
            telegram_id,
            channel["username"],
        )

        results.append(
            {
                "username": channel["username"],
                "name": channel["name"],
                "url": channel["url"],
                "joined": joined,
            }
        )

    return results


# ============================================================
# HOME
# ============================================================

@app.get("/")
async def home():
    if os.path.exists("index.html"):
        return FileResponse("index.html")

    return JSONResponse(
        {
            "name": "Falcon World",
            "status": "online",
            "version": "1.0.0",
        }
    )


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "Falcon World",
        "bot": BOT_USERNAME,
    }


# ============================================================
# CHANNELS
# ============================================================

@app.get("/api/channels")
async def channels():
    return {
        "channels": REQUIRED_CHANNELS
    }


@app.get("/api/check-membership/{telegram_id}")
async def membership(telegram_id: str):

    results = await check_all_channels(telegram_id)

    all_joined = all(
        channel["joined"]
        for channel in results
    )

    return {
        "telegram_id": telegram_id,
        "all_joined": all_joined,
        "channels": results,
    }


# ============================================================
# REGISTER
# ============================================================

@app.post("/api/register")
async def register(data: RegisterRequest):

    telegram_id = str(data.telegram_id)

    if not telegram_id:
        raise HTTPException(
            status_code=400,
            detail="Telegram ID is required",
        )

    conn = get_db()

    existing = conn.execute(
        "SELECT * FROM users WHERE telegram_id = ?",
        (telegram_id,),
    ).fetchone()

    if existing:
        conn.execute(
            """
            UPDATE users
            SET username = ?, first_name = ?
            WHERE telegram_id = ?
            """,
            (
                data.username or "",
                data.first_name or "",
                telegram_id,
            ),
        )

        conn.commit()

        user = conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?",
            (telegram_id,),
        ).fetchone()

        conn.close()

        return {
            "success": True,
            "new_user": False,
            "user": user_dict(user),
        }

    referred_by = str(data.referral or "").strip()

    # Prevent self-referral
    if referred_by == telegram_id:
        referred_by = ""

    conn.execute(
        """
        INSERT INTO users (
            telegram_id,
            username,
            first_name,
            referred_by
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            telegram_id,
            data.username or "",
            data.first_name or "",
            referred_by,
        ),
    )

    conn.commit()

    user = conn.execute(
        "SELECT * FROM users WHERE telegram_id = ?",
        (telegram_id,),
    ).fetchone()

    conn.close()

    return {
        "success": True,
        "new_user": True,
        "user": user_dict(user),
    }


# ============================================================
# USER
# ============================================================

@app.get("/api/me/{telegram_id}")
async def me(telegram_id: str):

    user = get_user(telegram_id)

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found",
        )

    return {
        "success": True,
        "user": user_dict(user),
    }


# ============================================================
# REFERRAL
# ============================================================

@app.get("/api/referral/{telegram_id}")
async def referral(telegram_id: str):

    user = get_user(telegram_id)

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found",
        )

    referral_link = (
        f"https://t.me/{BOT_USERNAME}"
        f"?start=ref_{telegram_id}"
    )

    return {
        "success": True,
        "count": user["referral_count"],
        "reward": REFERRAL_REWARD,
        "link": referral_link,
    }


@app.post("/api/referral")
async def referral_data(data: ReferralRequest):

    user = get_user(data.telegram_id)

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found",
        )

    return {
        "success": True,
        "count": user["referral_count"],
        "reward": REFERRAL_REWARD,
        "link": (
            f"https://t.me/{BOT_USERNAME}"
            f"?start=ref_{data.telegram_id}"
        ),
    }


# ============================================================
# DAILY BONUS
# ============================================================

@app.post("/api/daily-bonus")
async def daily_bonus(data: DailyBonusRequest):

    user = get_user(data.telegram_id)

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found",
        )

    today = datetime.utcnow().strftime("%Y-%m-%d")

    if user["daily_claim"] == today:
        return {
            "success": False,
            "claimed": True,
            "message": "Daily bonus already claimed today.",
            "balance": round(float(user["balance"]), 2),
        }

    conn = get_db()

    new_balance = float(user["balance"]) + DAILY_BONUS

    conn.execute(
        """
        UPDATE users
        SET balance = ?, daily_claim = ?
        WHERE telegram_id = ?
        """,
        (
            new_balance,
            today,
            data.telegram_id,
        ),
    )

    conn.commit()
    conn.close()

    return {
        "success": True,
        "claimed": True,
        "reward": DAILY_BONUS,
        "balance": round(new_balance, 2),
    }


# ============================================================
# WALLET
# ============================================================

@app.post("/api/wallet")
async def save_wallet(data: WalletRequest):

    cbe = data.cbe.strip()
    telebirr = data.telebirr.strip()

    if cbe and not valid_cbe(cbe):
        raise HTTPException(
            status_code=400,
            detail="Invalid CBE account. It must be 13 digits and start with 1000.",
        )

    if telebirr and not valid_telebirr(telebirr):
        raise HTTPException(
            status_code=400,
            detail="Invalid Telebirr number. It must be 10 digits and start with 09 or 07.",
        )

    user = get_user(data.telegram_id)

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found",
        )

    conn = get_db()

    conn.execute(
        """
        UPDATE users
        SET cbe = ?, telebirr = ?
        WHERE telegram_id = ?
        """,
        (
            cbe,
            telebirr,
            data.telegram_id,
        ),
    )

    conn.commit()

    user = conn.execute(
        "SELECT * FROM users WHERE telegram_id = ?",
        (data.telegram_id,),
    ).fetchone()

    conn.close()

    return {
        "success": True,
        "user": user_dict(user),
    }


@app.get("/api/wallet/{telegram_id}")
async def wallet(telegram_id: str):

    user = get_user(telegram_id)

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found",
        )

    return {
        "success": True,
        "cbe": user["cbe"],
        "telebirr": user["telebirr"],
    }


# ============================================================
# WITHDRAW
# ============================================================

@app.post("/api/withdraw")
async def withdraw(data: WithdrawRequest):

    user = get_user(data.telegram_id)

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found",
        )

    if data.amount < MIN_WITHDRAW:
        raise HTTPException(
            status_code=400,
            detail=f"Minimum withdrawal is {MIN_WITHDRAW} ETB.",
        )

    if data.amount > float(user["balance"]):
        raise HTTPException(
            status_code=400,
            detail="Insufficient balance.",
        )

    method = data.method.strip().lower()

    if method not in {"cbe", "telebirr"}:
        raise HTTPException(
            status_code=400,
            detail="Invalid withdrawal method.",
        )

    account = data.account.strip()

    if method == "cbe" and not valid_cbe(account):
        raise HTTPException(
            status_code=400,
            detail="Invalid CBE account.",
        )

    if method == "telebirr" and not valid_telebirr(account):
        raise HTTPException(
            status_code=400,
            detail="Invalid Telebirr number.",
        )

    conn = get_db()

    new_balance = float(user["balance"]) - data.amount

    conn.execute(
        """
        UPDATE users
        SET balance = ?
        WHERE telegram_id = ?
        """,
        (
            new_balance,
            data.telegram_id,
        ),
    )

    conn.execute(
        """
        INSERT INTO withdrawals (
            telegram_id,
            amount,
            method,
            account,
            status
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            data.telegram_id,
            data.amount,
            method,
            account,
            "Pending",
        ),
    )

    conn.commit()
    conn.close()

    return {
        "success": True,
        "message": "Withdrawal request submitted.",
        "amount": data.amount,
        "status": "Pending",
        "balance": round(new_balance, 2),
    }


# ============================================================
# WITHDRAWAL HISTORY
# ============================================================

@app.get("/api/withdrawals/{telegram_id}")
async def withdrawals(telegram_id: str):

    user = get_user(telegram_id)

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found",
        )

    conn = get_db()

    rows = conn.execute(
        """
        SELECT
            id,
            amount,
            method,
            account,
            status,
            created_at
        FROM withdrawals
        WHERE telegram_id = ?
        ORDER BY id DESC
        """,
        (telegram_id,),
    ).fetchall()

    conn.close()

    return {
        "success": True,
        "withdrawals": [
            {
                "id": row["id"],
                "amount": row["amount"],
                "method": row["method"],
                "account": row["account"],
                "status": row["status"],
                "created_at": row["created_at"],
            }
            for row in rows
        ],
    }


# ============================================================
# TASKS
# ============================================================

@app.get("/api/tasks/{telegram_id}")
async def tasks(telegram_id: str):

    user = get_user(telegram_id)

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found",
        )

    conn = get_db()

    rows = conn.execute(
        """
        SELECT id, title, reward, url
        FROM tasks
        WHERE active = 1
        ORDER BY id ASC
        """
    ).fetchall()

    completed = conn.execute(
        """
        SELECT task_id
        FROM completed_tasks
        WHERE telegram_id = ?
        """,
        (telegram_id,),
    ).fetchall()

    completed_ids = {
        row["task_id"]
        for row in completed
    }

    conn.close()

    return {
        "success": True,
        "tasks": [
            {
                "id": row["id"],
                "title": row["title"],
                "reward": row["reward"],
                "url": row["url"],
                "completed": row["id"] in completed_ids,
            }
            for row in rows
        ],
    }


@app.post("/api/tasks/complete")
async def complete_task(data: TaskRequest):

    user = get_user(data.telegram_id)

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found",
        )

    conn = get_db()

    task = conn.execute(
        """
        SELECT *
        FROM tasks
        WHERE id = ? AND active = 1
        """,
        (data.task_id,),
    ).fetchone()

    if not task:
        conn.close()

        raise HTTPException(
            status_code=404,
            detail="Task not found",
        )

    already = conn.execute(
        """
        SELECT id
        FROM completed_tasks
        WHERE telegram_id = ? AND task_id = ?
        """,
        (
            data.telegram_id,
            data.task_id,
        ),
    ).fetchone()

    if already:
        conn.close()

        return {
            "success": False,
            "message": "Task already completed.",
        }

    reward = float(task["reward"])
    new_balance = float(user["balance"]) + reward

    conn.execute(
        """
        INSERT INTO completed_tasks (
            telegram_id,
            task_id
        )
        VALUES (?, ?)
        """,
        (
            data.telegram_id,
            data.task_id,
        ),
    )

    conn.execute(
        """
        UPDATE users
        SET balance = ?
        WHERE telegram_id = ?
        """,
        (
            new_balance,
            data.telegram_id,
        ),
    )

    conn.commit()
    conn.close()

    return {
        "success": True,
        "reward": reward,
        "balance": round(new_balance, 2),
    }


# ============================================================
# ADMIN / INFO
# ============================================================

@app.get("/api/config")
async def config():

    return {
        "bot_username": BOT_USERNAME,
        "admin": ADMIN_USERNAME,
        "daily_bonus": DAILY_BONUS,
        "referral_reward": REFERRAL_REWARD,
        "minimum_withdraw": MIN_WITHDRAW,
        "channels": REQUIRED_CHANNELS,
    }


# ============================================================
# ERROR HANDLER
# ============================================================

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):

    print("SERVER ERROR:", repr(exc))

    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": "Internal server error",
        },
    )
