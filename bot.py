import os
import re
import html
import sqlite3
import random
import logging
from datetime import datetime, timedelta

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    BotCommand,
)

from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)


# ============================================================
# 🦅 FALCON WORLD
# Advanced Telegram Earning Bot
# ============================================================


# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

ADMIN_IDS = [
    int(x.strip())
    for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
]

BOT_NAME = os.getenv(
    "BOT_NAME",
    "Falcon World"
)

DB_NAME = os.getenv(
    "DB_NAME",
    "falcon_world.db"
)

SUPPORT_USERNAME = os.getenv(
    "SUPPORT_USERNAME",
    "AmanM_12"
).lstrip("@")

DAILY_BONUS = 0.50
REFERRAL_REWARD = 2.00
MIN_WITHDRAW = 30.00


# ============================================================
# REQUIRED CHANNELS
# ============================================================

MANDATORY_CHANNELS = [
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
# CONVERSATION STATES
# ============================================================

(
    CAPTCHA,
    WALLET_TYPE,
    WALLET_INPUT,
    TASK_PROOF,
) = range(4)


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger("FalconWorld")


# ============================================================
# DATABASE
# ============================================================

def db():
    conn = sqlite3.connect(
        DB_NAME,
        timeout=30,
    )

    conn.row_factory = sqlite3.Row

    conn.execute(
        "PRAGMA foreign_keys = ON"
    )

    return conn


def init_db():

    conn = db()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT DEFAULT '',
            full_name TEXT DEFAULT '',
            balance REAL DEFAULT 0,
            referred_by INTEGER,
            cbe_account TEXT DEFAULT '',
            telebirr_account TEXT DEFAULT '',
            last_daily_bonus TEXT DEFAULT '',
            is_banned INTEGER DEFAULT 0,
            suspicious INTEGER DEFAULT 0,
            referral_rewarded INTEGER DEFAULT 0,
            verified INTEGER DEFAULT 0,
            joined_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER NOT NULL,
            referred_id INTEGER UNIQUE NOT NULL,
            reward_amount REAL NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            method TEXT NOT NULL,
            account_number TEXT NOT NULL,
            status TEXT DEFAULT 'PENDING',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            link TEXT DEFAULT '',
            reward REAL DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS task_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            proof_text TEXT DEFAULT '',
            proof_file_id TEXT DEFAULT '',
            proof_type TEXT DEFAULT 'text',
            status TEXT DEFAULT 'PENDING',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    # --------------------------------------------------------
    # MIGRATION
    # --------------------------------------------------------

    user_columns = {
        row["name"]
        for row in cursor.execute(
            "PRAGMA table_info(users)"
        ).fetchall()
    }

    user_migrations = {
        "referral_rewarded": "INTEGER DEFAULT 0",
        "verified": "INTEGER DEFAULT 0",
    }

    for column, definition in user_migrations.items():

        if column not in user_columns:

            cursor.execute(
                f"""
                ALTER TABLE users
                ADD COLUMN {column} {definition}
                """
            )

    submission_columns = {
        row["name"]
        for row in cursor.execute(
            "PRAGMA table_info(task_submissions)"
        ).fetchall()
    }

    if "proof_file_id" not in submission_columns:

        cursor.execute("""
            ALTER TABLE task_submissions
            ADD COLUMN proof_file_id TEXT DEFAULT ''
        """)

    if "proof_type" not in submission_columns:

        cursor.execute("""
            ALTER TABLE task_submissions
            ADD COLUMN proof_type TEXT DEFAULT 'text'
        """)

    # --------------------------------------------------------
    # SETTINGS
    # --------------------------------------------------------

    defaults = {
        "daily_bonus": str(DAILY_BONUS),
        "referral_reward": str(REFERRAL_REWARD),
        "min_withdraw": str(MIN_WITHDRAW),
    }

    for key, value in defaults.items():

        cursor.execute(
            """
            INSERT OR IGNORE INTO settings
            (key, value)
            VALUES (?, ?)
            """,
            (key, value),
        )

    # --------------------------------------------------------
    # INDEXES
    # --------------------------------------------------------

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_withdrawals_user
        ON withdrawals(user_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_withdrawals_status
        ON withdrawals(status)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_tasks_active
        ON tasks(is_active)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS
        idx_task_submissions_user
        ON task_submissions(user_id)
    """)

    conn.commit()
    conn.close()


init_db()


# ============================================================
# SETTINGS FUNCTIONS
# ============================================================

def get_setting(key, default=None):

    conn = db()

    row = conn.execute(
        """
        SELECT value
        FROM settings
        WHERE key = ?
        """,
        (key,),
    ).fetchone()

    conn.close()

    if not row:
        return default

    try:
        return float(row["value"])
    except Exception:
        return row["value"]


def set_setting(key, value):

    conn = db()

    conn.execute(
        """
        INSERT OR REPLACE INTO settings
        (key, value)
        VALUES (?, ?)
        """,
        (key, str(value)),
    )

    conn.commit()
    conn.close()


# ============================================================
# USER FUNCTIONS
# ============================================================

def get_user(user_id):

    conn = db()

    user = conn.execute(
        """
        SELECT *
        FROM users
        WHERE user_id = ?
        """,
        (user_id,),
    ).fetchone()

    conn.close()

    return user


def create_or_update_user(
    user_id,
    username="",
    full_name="",
    referred_by=None,
):

    conn = db()

    existing = conn.execute(
        """
        SELECT *
        FROM users
        WHERE user_id = ?
        """,
        (user_id,),
    ).fetchone()

    if existing:

        conn.execute(
            """
            UPDATE users
            SET username = ?,
                full_name = ?
            WHERE user_id = ?
            """,
            (
                username or "",
                full_name or "",
                user_id,
            ),
        )

        # Only set referral if user does not already have one
        if (
            existing["referred_by"] is None
            and referred_by
            and referred_by != user_id
            and existing["verified"] == 0
        ):

            referrer = conn.execute(
                """
                SELECT user_id
                FROM users
                WHERE user_id = ?
                AND is_banned = 0
                """,
                (referred_by,),
            ).fetchone()

            if referrer:

                conn.execute(
                    """
                    UPDATE users
                    SET referred_by = ?
                    WHERE user_id = ?
                    """,
                    (
                        referred_by,
                        user_id,
                    ),
                )

        conn.commit()
        conn.close()

        return False

    # Prevent self referral
    if referred_by == user_id:
        referred_by = None

    # Referrer must exist
    if referred_by:

        referrer = conn.execute(
            """
            SELECT user_id
            FROM users
            WHERE user_id = ?
            AND is_banned = 0
            """,
            (referred_by,),
        ).fetchone()

        if not referrer:
            referred_by = None

    conn.execute(
        """
        INSERT INTO users (
            user_id,
            username,
            full_name,
            referred_by
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            user_id,
            username or "",
            full_name or "",
            referred_by,
        ),
    )

    conn.commit()
    conn.close()

    return True


def is_banned(user_id):

    user = get_user(user_id)

    return bool(
        user and user["is_banned"] == 1
    )


def is_verified(user_id):

    user = get_user(user_id)

    return bool(
        user and user["verified"] == 1
    )


# ============================================================
# HTML HELPERS
# ============================================================

def safe(value):

    return html.escape(
        str(value or "")
    )


# ============================================================
# CHANNEL MEMBERSHIP
# ============================================================

async def check_channel_membership(
    user_id,
    context,
):

    missing = []

    for channel in MANDATORY_CHANNELS:

        try:

            member = await context.bot.get_chat_member(
                chat_id=channel["username"],
                user_id=user_id,
            )

            if member.status == "kicked":

                missing.append(channel)

            elif member.status == "left":

                missing.append(channel)

            elif (
                member.status == "restricted"
                and not getattr(
                    member,
                    "is_member",
                    False,
                )
            ):

                missing.append(channel)

        except Exception as e:

            logger.warning(
                "Membership check failed: %s | %s",
                channel["username"],
                e,
            )

            missing.append(channel)

    return missing


# ============================================================
# MAIN KEYBOARD
# ============================================================

def main_keyboard():

    keyboard = [
        ["💰 Balance", "🎁 Daily Bonus"],
        ["👥 Invite Friends", "📋 Tasks"],
        ["💳 Wallet Settings", "🔻 Withdraw"],
        ["❓ Help", "📞 Support"],
    ]

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
    )


# ============================================================
# CHANNEL KEYBOARD
# ============================================================

def channel_keyboard(
    missing_channels,
):

    buttons = []

    for channel in missing_channels:

        buttons.append(
            [
                InlineKeyboardButton(
                    f"📢 Join {channel['name']}",
                    url=channel["url"],
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                "✅ Verify Joining",
                callback_data="verify_membership",
            )
        ]
    )

    return InlineKeyboardMarkup(
        buttons
    )


# ============================================================
# WELCOME
# ============================================================

def welcome_text(first_name):

    name = safe(
        first_name or "Friend"
    )

    return (
        "🦅 <b>WELCOME TO FALCON WORLD</b>\n\n"
        f"👋 Hello {name}!\n\n"
        "💰 Earn & Complete Tasks\n"
        "🎁 Daily Rewards\n"
        "👥 Referral Rewards\n"
        "🚀 New Opportunities\n\n"
        "📢 <b>Ads & Promotions:</b> Contact Admin\n"
        "💱 <b>USDT Exchange:</b> Buy & Sell\n\n"
        "🚀 Open Falcon World from the Menu below."
    )


# ============================================================
# SHOW CHANNEL VERIFICATION
# ============================================================

async def show_channel_verification(
    update,
    context,
):

    user_id = update.effective_user.id

    missing = await check_channel_membership(
        user_id,
        context,
    )

    if missing:

        text = (
            "🦅 <b>FALCON WORLD</b>\n\n"
            "🔐 <b>One more step!</b>\n\n"
            "Join all required channels below "
            "and then press <b>Verify Joining</b>.\n\n"
            "📢 Channels remaining:\n"
        )

        for channel in missing:
            text += (
                f"• {safe(channel['name'])}\n"
            )

        markup = channel_keyboard(
            missing
        )

        if update.callback_query:

            await update.callback_query.edit_message_text(
                text,
                reply_markup=markup,
                parse_mode="HTML",
            )

        elif update.message:

            await update.message.reply_text(
                text,
                reply_markup=markup,
                parse_mode="HTML",
            )

        return False

    await complete_verification(
        user_id,
        context,
    )

    return True


# ============================================================
# START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user = update.effective_user

    if not user or not update.message:
        return ConversationHandler.END

    if is_banned(user.id):

        await update.message.reply_text(
            "⛔ <b>Your Falcon World account "
            "has been suspended.</b>",
            parse_mode="HTML",
        )

        return ConversationHandler.END

    referred_by = None

    if context.args:

        code = context.args[0].strip()

        if code.startswith("ref_"):
            code = code[4:]

        if code.isdigit():

            candidate = int(code)

            if candidate != user.id:
                referred_by = candidate

    create_or_update_user(
        user.id,
        user.username,
        user.full_name,
        referred_by,
    )

    # Already verified users can go directly to menu
    if is_verified(user.id):

        missing = await check_channel_membership(
            user.id,
            context,
        )

        if not missing:

            await update.message.reply_text(
                welcome_text(
                    user.first_name
                ),
                reply_markup=main_keyboard(),
                parse_mode="HTML",
            )

            return ConversationHandler.END

        # Membership removed
        conn = db()

        conn.execute(
            """
            UPDATE users
            SET verified = 0
            WHERE user_id = ?
            """,
            (user.id,),
        )

        conn.commit()
        conn.close()

    # --------------------------------------------------------
    # CAPTCHA
    # --------------------------------------------------------

    num1 = random.randint(1, 9)
    num2 = random.randint(1, 9)

    context.user_data[
        "captcha_answer"
    ] = num1 + num2

    await update.message.reply_text(
        "🤖 <b>FALCON WORLD VERIFICATION</b>\n\n"
        "Before you continue, solve this simple verification.\n\n"
        f"🔢 <b>{num1} + {num2} = ?</b>\n\n"
        "Send only the answer.",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="HTML",
    )

    return CAPTCHA


# ============================================================
# CAPTCHA ANSWER
# ============================================================

async def verify_captcha(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.message:
        return ConversationHandler.END

    answer = update.message.text.strip()

    correct = str(
        context.user_data.get(
            "captcha_answer",
            "",
        )
    )

    if answer != correct:

        await update.message.reply_text(
            "❌ <b>Incorrect answer.</b>\n\n"
            "Use /start to try again.",
            parse_mode="HTML",
        )

        return ConversationHandler.END

    context.user_data.pop(
        "captcha_answer",
        None,
    )

    await show_channel_verification(
        update,
        context,
    )

    return ConversationHandler.END


# ============================================================
# COMPLETE VERIFICATION
# ============================================================

async def complete_verification(
    user_id,
    context,
):

    conn = db()

    user = conn.execute(
        """
        SELECT referred_by,
               referral_rewarded
        FROM users
        WHERE user_id = ?
        """,
        (user_id,),
    ).fetchone()

    if not user:

        conn.close()
        return

    conn.execute(
        """
        UPDATE users
        SET verified = 1
        WHERE user_id = ?
        """,
        (user_id,),
    )

    conn.commit()

    referred_by = user["referred_by"]
    already_rewarded = user["referral_rewarded"]

    # --------------------------------------------------------
    # REFERRAL REWARD
    # --------------------------------------------------------

    if (
        referred_by
        and not already_rewarded
        and referred_by != user_id
    ):

        existing_referral = conn.execute(
            """
            SELECT id
            FROM referrals
            WHERE referred_id = ?
            """,
            (user_id,),
        ).fetchone()

        if not existing_referral:

            referrer = conn.execute(
                """
                SELECT user_id
                FROM users
                WHERE user_id = ?
                AND is_banned = 0
                """,
                (referred_by,),
            ).fetchone()

            if referrer:

                reward = get_setting(
                    "referral_reward",
                    REFERRAL_REWARD,
                )

                conn.execute(
                    """
                    UPDATE users
                    SET balance = balance + ?
                    WHERE user_id = ?
                    """,
                    (
                        reward,
                        referred_by,
                    ),
                )

                conn.execute(
                    """
                    INSERT INTO referrals (
                        referrer_id,
                        referred_id,
                        reward_amount
                    )
                    VALUES (?, ?, ?)
                    """,
                    (
                        referred_by,
                        user_id,
                        reward,
                    ),
                )

                conn.execute(
                    """
                    UPDATE users
                    SET referral_rewarded = 1
                    WHERE user_id = ?
                    """,
                    (user_id,),
                )

                conn.commit()

                try:

                    await context.bot.send_message(
                        chat_id=referred_by,
                        text=(
                            "🎉 <b>REFERRAL REWARD</b>\n\n"
                            "A new user joined through "
                            "your referral link and completed "
                            "verification.\n\n"
                            f"💰 Reward: "
                            f"<b>+{reward:.2f} ETB</b>"
                        ),
                        parse_mode="HTML",
                    )

                except Exception as e:

                    logger.warning(
                        "Referral notification failed: %s",
                        e,
                    )

    conn.close()


# ============================================================
# VERIFY MEMBERSHIP CALLBACK
# ============================================================

async def callback_verify_membership(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    user_id = query.from_user.id

    if is_banned(user_id):

        await query.answer(
            "⛔ Your account is suspended.",
            show_alert=True,
        )

        return

    missing = await check_channel_membership(
        user_id,
        context,
    )

    if missing:

        await query.answer(
            "❌ Some channels are still missing.",
            show_alert=True,
        )

        names = "\n".join(
            f"• {safe(x['name'])}"
            for x in missing
        )

        try:

            await query.edit_message_text(
                "⚠️ <b>Verification incomplete</b>\n\n"
                f"{names}\n\n"
                "Join all of them and verify again.",
                reply_markup=channel_keyboard(
                    missing
                ),
                parse_mode="HTML",
            )

        except Exception:
            pass

        return

    await query.answer(
        "✅ Verification successful!"
    )

    await complete_verification(
        user_id,
        context,
    )

    try:

        await query.edit_message_text(
            "✅ <b>Verification successful!</b>\n\n"
            "Welcome to Falcon World 🦅",
            parse_mode="HTML",
        )

    except Exception:
        pass

    await context.bot.send_message(
        chat_id=user_id,
        text=welcome_text(
            query.from_user.first_name
        ),
        reply_markup=main_keyboard(),
        parse_mode="HTML",
    )


# ============================================================
# REQUIRE VERIFIED
# ============================================================

async def require_verified(
    update,
):

    user_id = update.effective_user.id

    if is_banned(user_id):

        if update.message:

            await update.message.reply_text(
                "⛔ <b>Your account is suspended.</b>",
                parse_mode="HTML",
            )

        return False

    user = get_user(user_id)

    if not user or user["verified"] != 1:

        if update.message:

            await update.message.reply_text(
                "🔐 <b>Verification required.</b>\n\n"
                "Please use /start first.",
                parse_mode="HTML",
            )

        return False

    return True


# ============================================================
# BALANCE
# ============================================================

async def handle_balance(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await require_verified(update):
        return

    user = get_user(
        update.effective_user.id
    )

    if not user:
        return

    cbe = user["cbe_account"] or "Not Set"
    telebirr = user["telebirr_account"] or "Not Set"

    conn = db()

    referrals = conn.execute(
        """
        SELECT COUNT(*)
        FROM referrals
        WHERE referrer_id = ?
        """,
        (user["user_id"],),
    ).fetchone()[0]

    conn.close()

    text = (
        "💰 <b>MY BALANCE</b>\n\n"
        f"🆔 User ID: "
        f"<code>{user['user_id']}</code>\n"
        f"💵 Balance: "
        f"<b>{user['balance']:.2f} ETB</b>\n"
        f"👥 Referrals: <b>{referrals}</b>\n\n"
        "💳 <b>WALLETS</b>\n"
        f"🏦 CBE: <code>{safe(cbe)}</code>\n"
        f"📱 Telebirr: "
        f"<code>{safe(telebirr)}</code>"
    )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
    )


# ============================================================
# DAILY BONUS
# ============================================================

async def handle_daily_bonus(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await require_verified(update):
        return

    user_id = update.effective_user.id

    conn = db()

    user = conn.execute(
        """
        SELECT last_daily_bonus
        FROM users
        WHERE user_id = ?
        """,
        (user_id,),
    ).fetchone()

    if not user:

        conn.close()
        return

    now = datetime.utcnow()

    if user["last_daily_bonus"]:

        try:

            last = datetime.fromisoformat(
                user["last_daily_bonus"]
            )

            next_claim = (
                last +
                timedelta(hours=24)
            )

            if now < next_claim:

                remaining = (
                    next_claim - now
                )

                total_seconds = int(
                    remaining.total_seconds()
                )

                hours = (
                    total_seconds // 3600
                )

                minutes = (
                    total_seconds % 3600
                ) // 60

                conn.close()

                await update.message.reply_text(
                    "⏳ <b>DAILY BONUS ALREADY CLAIMED</b>\n\n"
                    f"Come back in "
                    f"<b>{hours}h {minutes}m</b>.",
                    parse_mode="HTML",
                )

                return

        except Exception:
            pass

    bonus = get_setting(
        "daily_bonus",
        DAILY_BONUS,
    )

    conn.execute(
        """
        UPDATE users
        SET balance = balance + ?,
            last_daily_bonus = ?
        WHERE user_id = ?
        """,
        (
            bonus,
            now.isoformat(),
            user_id,
        ),
    )

    new_balance = conn.execute(
        """
        SELECT balance
        FROM users
        WHERE user_id = ?
        """,
        (user_id,),
    ).fetchone()["balance"]

    conn.commit()
    conn.close()

    await update.message.reply_text(
        "🎁 <b>DAILY BONUS CLAIMED!</b>\n\n"
        f"💰 Reward: "
        f"<b>+{bonus:.2f} ETB</b>\n"
        f"💵 New Balance: "
        f"<b>{new_balance:.2f} ETB</b>",
        parse_mode="HTML",
    )


# ============================================================
# REFERRAL
# ============================================================

async def handle_invite(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await require_verified(update):
        return

    user_id = update.effective_user.id

    bot_info = await context.bot.get_me()

    conn = db()

    count = conn.execute(
        """
        SELECT COUNT(*)
        FROM referrals
        WHERE referrer_id = ?
        """,
        (user_id,),
    ).fetchone()[0]

    total = conn.execute(
        """
        SELECT COALESCE(
            SUM(reward_amount),
            0
        )
        FROM referrals
        WHERE referrer_id = ?
        """,
        (user_id,),
    ).fetchone()[0]

    conn.close()

    reward = get_setting(
        "referral_reward",
        REFERRAL_REWARD,
    )

    link = (
        f"https://t.me/"
        f"{bot_info.username}"
        f"?start=ref_{user_id}"
    )

    share_url = (
        "https://t.me/share/url"
        f"?url={link}"
    )

    text = (
        "👥 <b>INVITE FRIENDS</b>\n\n"
        f"💰 Earn <b>{reward:.2f} ETB</b> "
        "for every referred user who "
        "completes verification.\n\n"
        "🔗 <b>Your Referral Link</b>\n"
        f"<code>{safe(link)}</code>\n\n"
        f"👥 Invited: <b>{count}</b>\n"
        f"💵 Referral Earnings: "
        f"<b>{total:.2f} ETB</b>"
    )

    buttons = [
        [
            InlineKeyboardButton(
                "📤 Share Referral Link",
                url=share_url,
            )
        ]
    ]

    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            buttons
        ),
        parse_mode="HTML",
    )


# ============================================================
# WALLET SETTINGS
# ============================================================

async def start_wallet_setup(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await require_verified(update):
        return ConversationHandler.END

    buttons = [
        [
            InlineKeyboardButton(
                "🏦 CBE Account",
                callback_data="set_wallet_cbe",
            )
        ],
        [
            InlineKeyboardButton(
                "📱 Telebirr",
                callback_data="set_wallet_telebirr",
            )
        ],
    ]

    await update.message.reply_text(
        "💳 <b>WALLET SETTINGS</b>\n\n"
        "Select the wallet you want to save:",
        reply_markup=InlineKeyboardMarkup(
            buttons
        ),
        parse_mode="HTML",
    )

    return WALLET_TYPE


# ============================================================
# WALLET CHOICE
# ============================================================

async def handle_wallet_choice(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    await query.answer()

    if is_banned(query.from_user.id):

        await query.edit_message_text(
            "⛔ Account suspended."
        )

        return ConversationHandler.END

    context.user_data[
        "wallet_choice"
    ] = query.data

    if query.data == "set_wallet_cbe":

        text = (
            "🏦 <b>CBE ACCOUNT</b>\n\n"
            "Send your 13-digit CBE account number.\n\n"
            "Example:\n"
            "<code>1000XXXXXXXXX</code>"
        )

    else:

        text = (
            "📱 <b>TELEBIRR</b>\n\n"
            "Send your 10-digit Telebirr number.\n\n"
            "Example:\n"
            "<code>0912345678</code>"
        )

    await query.edit_message_text(
        text,
        parse_mode="HTML",
    )

    return WALLET_INPUT


# ============================================================
# SAVE WALLET
# ============================================================

async def save_wallet_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.message:
        return ConversationHandler.END

    user_id = update.effective_user.id

    value = update.message.text.strip()

    choice = context.user_data.get(
        "wallet_choice"
    )

    if choice not in (
        "set_wallet_cbe",
        "set_wallet_telebirr",
    ):

        await update.message.reply_text(
            "❌ Wallet session expired.\n"
            "Please try again.",
            reply_markup=main_keyboard(),
        )

        return ConversationHandler.END

    conn = db()

    # --------------------------------------------------------
    # CBE
    # --------------------------------------------------------

    if choice == "set_wallet_cbe":

        if not re.fullmatch(
            r"1000\d{9}",
            value,
        ):

            conn.close()

            await update.message.reply_text(
                "❌ <b>Invalid CBE account.</b>\n\n"
                "It must be exactly 13 digits "
                "and start with <b>1000</b>.",
                parse_mode="HTML",
            )

            return WALLET_INPUT

        duplicates = conn.execute(
            """
            SELECT user_id
            FROM users
            WHERE cbe_account = ?
            AND user_id != ?
            """,
            (
                value,
                user_id,
            ),
        ).fetchall()

        if duplicates:

            conn.execute(
                """
                UPDATE users
                SET suspicious = 1
                WHERE user_id = ?
                """,
                (user_id,),
            )

            for row in duplicates:

                conn.execute(
                    """
                    UPDATE users
                    SET suspicious = 1
                    WHERE user_id = ?
                    """,
                    (row["user_id"],),
                )

            conn.commit()

            await notify_admins(
                context,
                (
                    "🚨 <b>DUPLICATE CBE WALLET</b>\n\n"
                    f"User: <code>{user_id}</code>\n"
                    f"CBE: <code>{safe(value)}</code>\n"
                    f"Existing Users: "
                    f"<code>{safe([x['user_id'] for x in duplicates])}</code>"
                ),
            )

        conn.execute(
            """
            UPDATE users
            SET cbe_account = ?
            WHERE user_id = ?
            """,
            (
                value,
                user_id,
            ),
        )

        conn.commit()
        conn.close()

        context.user_data.pop(
            "wallet_choice",
            None,
        )

        await update.message.reply_text(
            "✅ <b>CBE account saved successfully.</b>",
            reply_markup=main_keyboard(),
            parse_mode="HTML",
        )

        return ConversationHandler.END

    # --------------------------------------------------------
    # TELEBIRR
    # --------------------------------------------------------

    if choice == "set_wallet_telebirr":

        if not re.fullmatch(
            r"(09|07)\d{8}",
            value,
        ):

            conn.close()

            await update.message.reply_text(
                "❌ <b>Invalid Telebirr number.</b>\n\n"
                "It must be exactly 10 digits "
                "and start with <b>09</b> or <b>07</b>.",
                parse_mode="HTML",
            )

            return WALLET_INPUT

        duplicates = conn.execute(
            """
            SELECT user_id
            FROM users
            WHERE telebirr_account = ?
            AND user_id != ?
            """,
            (
                value,
                user_id,
            ),
        ).fetchall()

        if duplicates:

            conn.execute(
                """
                UPDATE users
                SET suspicious = 1
                WHERE user_id = ?
                """,
                (user_id,),
            )

            for row in duplicates:

                conn.execute(
                    """
                    UPDATE users
                    SET suspicious = 1
                    WHERE user_id = ?
                    """,
                    (row["user_id"],),
                )

            conn.commit()

            await notify_admins(
                context,
                (
                    "🚨 <b>DUPLICATE TELEBIRR</b>\n\n"
                    f"User: <code>{user_id}</code>\n"
                    f"Telebirr: <code>{safe(value)}</code>\n"
                    f"Existing Users: "
                    f"<code>{safe([x['user_id'] for x in duplicates])}</code>"
                ),
            )

        conn.execute(
            """
            UPDATE users
            SET telebirr_account = ?
            WHERE user_id = ?
            """,
            (
                value,
                user_id,
            ),
        )

        conn.commit()
        conn.close()

        context.user_data.pop(
            "wallet_choice",
            None,
        )

        await update.message.reply_text(
            "✅ <b>Telebirr saved successfully.</b>",
            reply_markup=main_keyboard(),
            parse_mode="HTML",
        )

        return ConversationHandler.END

    conn.close()

    return ConversationHandler.END


# ============================================================
# WITHDRAW REQUEST
# ============================================================

async def handle_withdraw_request(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await require_verified(update):
        return

    user_id = update.effective_user.id

    user = get_user(user_id)

    if not user:
        return

    minimum = get_setting(
        "min_withdraw",
        MIN_WITHDRAW,
    )

    balance = float(
        user["balance"]
    )

    if balance < minimum:

        await update.message.reply_text(
            "🔻 <b>WITHDRAW</b>\n\n"
            f"Minimum withdrawal: "
            f"<b>{minimum:.2f} ETB</b>\n"
            f"Your balance: "
            f"<b>{balance:.2f} ETB</b>",
            parse_mode="HTML",
        )

        return

    # Existing pending withdrawal
    conn = db()

    pending = conn.execute(
        """
        SELECT id
        FROM withdrawals
        WHERE user_id = ?
        AND status = 'PENDING'
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()

    conn.close()

    if pending:

        await update.message.reply_text(
            "⏳ <b>You already have a pending withdrawal.</b>\n\n"
            "Please wait for Admin to review it.",
            parse_mode="HTML",
        )

        return

    buttons = []

    if user["cbe_account"]:

        buttons.append(
            [
                InlineKeyboardButton(
                    f"🏦 CBE • {user['cbe_account']}",
                    callback_data="withdraw_cbe",
                )
            ]
        )

    if user["telebirr_account"]:

        buttons.append(
            [
                InlineKeyboardButton(
                    f"📱 Telebirr • {user['telebirr_account']}",
                    callback_data="withdraw_telebirr",
                )
            ]
        )

    if not buttons:

        await update.message.reply_text(
            "⚠️ <b>No withdrawal wallet found.</b>\n\n"
            "Please open <b>💳 Wallet Settings</b> "
            "and add CBE or Telebirr first.",
            parse_mode="HTML",
        )

        return

    await update.message.reply_text(
        "🔻 <b>WITHDRAWAL</b>\n\n"
        f"Available balance: "
        f"<b>{balance:.2f} ETB</b>\n\n"
        "Select your withdrawal method:",
        reply_markup=InlineKeyboardMarkup(
            buttons
        ),
        parse_mode="HTML",
    )


# ============================================================
# WITHDRAW METHOD
# ============================================================

async def process_withdrawal_selection(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id

    if is_banned(user_id):
        return

    user = get_user(user_id)

    if not user:
        return

    method = (
        "CBE"
        if query.data == "withdraw_cbe"
        else "Telebirr"
    )

    account = (
        user["cbe_account"]
        if method == "CBE"
        else user["telebirr_account"]
    )

    if not account:

        await query.edit_message_text(
            "❌ Wallet not found."
        )

        return

    balance = float(
        user["balance"]
    )

    minimum = get_setting(
        "min_withdraw",
        MIN_WITHDRAW,
    )

    if balance < minimum:

        await query.edit_message_text(
            "❌ Insufficient balance."
        )

        return

    context.user_data[
        "withdraw_method"
    ] = method

    context.user_data[
        "withdraw_account"
    ] = account

    context.user_data[
        "withdraw_amount"
    ] = balance

    buttons = [
        [
            InlineKeyboardButton(
                "✅ Confirm Withdrawal",
                callback_data="confirm_withdraw",
            )
        ],
        [
            InlineKeyboardButton(
                "❌ Cancel",
                callback_data="cancel_withdraw",
            )
        ],
    ]

    await query.edit_message_text(
        "🔻 <b>CONFIRM WITHDRAWAL</b>\n\n"
        f"💰 Amount: <b>{balance:.2f} ETB</b>\n"
        f"💳 Method: <b>{method}</b>\n"
        f"🏦 Account: <code>{safe(account)}</code>\n\n"
        "⚠️ This request will use your full available balance.\n\n"
        "Confirm below:",
        reply_markup=InlineKeyboardMarkup(
            buttons
        ),
        parse_mode="HTML",
    )


# ============================================================
# CONFIRM WITHDRAW
# ============================================================

async def confirm_withdraw(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id

    method = context.user_data.get(
        "withdraw_method"
    )

    account = context.user_data.get(
        "withdraw_account"
    )

    amount = context.user_data.get(
        "withdraw_amount"
    )

    if not method or not account or not amount:

        await query.edit_message_text(
            "❌ Withdrawal session expired.\n"
            "Please try again."
        )

        return

    conn = db()

    # Transaction lock
    conn.execute(
        "BEGIN IMMEDIATE"
    )

    user = conn.execute(
        """
        SELECT *
        FROM users
        WHERE user_id = ?
        """,
        (user_id,),
    ).fetchone()

    if not user:

        conn.rollback()
        conn.close()

        await query.edit_message_text(
            "❌ User not found."
        )

        return

    # Check pending withdrawal
    pending = conn.execute(
        """
        SELECT id
        FROM withdrawals
        WHERE user_id = ?
        AND status = 'PENDING'
        LIMIT 1
        """,
        (user_id,),
    ).fetchone()

    if pending:

        conn.rollback()
        conn.close()

        await query.edit_message_text(
            "⏳ You already have a pending withdrawal."
        )

        return

    current_balance = float(
        user["balance"]
    )

    amount = float(amount)

    if current_balance < amount:

        conn.rollback()
        conn.close()

        await query.edit_message_text(
            "❌ Your balance has changed.\n"
            "Please try again."
        )

        return

    conn.execute(
        """
        UPDATE users
        SET balance = balance - ?
        WHERE user_id = ?
        """,
        (
            amount,
            user_id,
        ),
    )

    cursor = conn.execute(
        """
        INSERT INTO withdrawals (
            user_id,
            amount,
            method,
            account_number,
            status
        )
        VALUES (?, ?, ?, ?, 'PENDING')
        """,
        (
            user_id,
            amount,
            method,
            account,
        ),
    )

    withdrawal_id = cursor.lastrowid

    conn.commit()
    conn.close()

    username = (
        f"@{safe(user['username'])}"
        if user["username"]
        else "N/A"
    )

    warning = (
        "\n🚨 <b>MULTI-ACCOUNT FLAG</b>\n"
        if user["suspicious"]
        else ""
    )

    admin_text = (
        f"🚨 <b>NEW WITHDRAWAL #{withdrawal_id}</b>\n"
        f"{warning}\n"
        "👤 <b>User</b>\n"
        f"Name: {safe(user['full_name'])}\n"
        f"Username: {username}\n"
        f"ID: <code>{user_id}</code>\n\n"
        "💰 <b>Payout</b>\n"
        f"Amount: <b>{amount:.2f} ETB</b>\n"
        f"Method: <b>{method}</b>\n"
        f"Account: <code>{safe(account)}</code>"
    )

    buttons = [
        [
            InlineKeyboardButton(
                "✅ Approve",
                callback_data=(
                    f"adm_appr_{withdrawal_id}"
                ),
            ),
            InlineKeyboardButton(
                "❌ Reject & Refund",
                callback_data=(
                    f"adm_rej_{withdrawal_id}"
                ),
            ),
        ],
        [
            InlineKeyboardButton(
                "⛔ Ban User",
                callback_data=(
                    f"adm_ban_{user_id}"
                ),
            )
        ],
    ]

    for admin_id in ADMIN_IDS:

        try:

            await context.bot.send_message(
                chat_id=admin_id,
                text=admin_text,
                reply_markup=InlineKeyboardMarkup(
                    buttons
                ),
                parse_mode="HTML",
            )

        except Exception as e:

            logger.warning(
                "Withdrawal admin notification failed: %s",
                e,
            )

    context.user_data.clear()

    await query.edit_message_text(
        "✅ <b>WITHDRAWAL SUBMITTED</b>\n\n"
        f"💰 Amount: <b>{amount:.2f} ETB</b>\n"
        f"💳 Method: <b>{method}</b>\n\n"
        "⏳ Your request is waiting for "
        "Admin verification.",
        parse_mode="HTML",
    )


# ============================================================
# CANCEL WITHDRAW
# ============================================================

async def cancel_withdraw(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    await query.answer()

    context.user_data.pop(
        "withdraw_method",
        None,
    )

    context.user_data.pop(
        "withdraw_account",
        None,
    )

    context.user_data.pop(
        "withdraw_amount",
        None,
    )

    await query.edit_message_text(
        "❌ <b>Withdrawal cancelled.</b>",
        parse_mode="HTML",
    )


# ============================================================
# TASK LIST
# ============================================================

async def handle_tasks_list(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await require_verified(update):
        return

    user_id = update.effective_user.id

    conn = db()

    tasks = conn.execute(
        """
        SELECT
            t.id,
            t.title,
            t.link,
            t.reward
        FROM tasks t
        WHERE t.is_active = 1
        AND NOT EXISTS (
            SELECT 1
            FROM task_submissions ts
            WHERE ts.task_id = t.id
            AND ts.user_id = ?
            AND ts.status IN (
                'PENDING',
                'APPROVED'
            )
        )
        ORDER BY t.id DESC
        """,
        (user_id,),
    ).fetchall()

    conn.close()

    if not tasks:

        await update.message.reply_text(
            "📋 <b>NO TASKS AVAILABLE</b>\n\n"
            "Please check again later.",
            parse_mode="HTML",
        )

        return

    buttons = []

    for task in tasks:

        buttons.append(
            [
                InlineKeyboardButton(
                    f"👉 {task['title']} "
                    f"(+{task['reward']:.2f} ETB)",
                    callback_data=(
                        f"dotask_{task['id']}"
                    ),
                )
            ]
        )

    await update.message.reply_text(
        "📋 <b>AVAILABLE TASKS</b>\n\n"
        "Select a task below:",
        reply_markup=InlineKeyboardMarkup(
            buttons
        ),
        parse_mode="HTML",
    )


# ============================================================
# TASK CLICK
# ============================================================

async def process_task_click(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id

    if is_banned(user_id):

        await query.edit_message_text(
            "⛔ Account suspended."
        )

        return ConversationHandler.END

    try:

        task_id = int(
            query.data.split("_")[1]
        )

    except Exception:

        await query.edit_message_text(
            "❌ Invalid task."
        )

        return ConversationHandler.END

    conn = db()

    task = conn.execute(
        """
        SELECT *
        FROM tasks
        WHERE id = ?
        AND is_active = 1
        """,
        (task_id,),
    ).fetchone()

    existing = conn.execute(
        """
        SELECT id
        FROM task_submissions
        WHERE task_id = ?
        AND user_id = ?
        AND status IN (
            'PENDING',
            'APPROVED'
        )
        """,
        (
            task_id,
            user_id,
        ),
    ).fetchone()

    conn.close()

    if not task:

        await query.edit_message_text(
            "❌ Task no longer exists."
        )

        return ConversationHandler.END

    if existing:

        await query.edit_message_text(
            "⚠️ You already submitted this task."
        )

        return ConversationHandler.END

    context.user_data[
        "current_task_id"
    ] = task_id

    text = (
        "📋 <b>TASK DETAILS</b>\n\n"
        f"📌 Task: <b>{safe(task['title'])}</b>\n"
        f"💰 Reward: "
        f"<b>{task['reward']:.2f} ETB</b>\n\n"
        f"🔗 Link:\n"
        f"{safe(task['link'])}\n\n"
        "📝 Complete the task and send your proof.\n\n"
        "You can send:\n"
        "• Screenshot\n"
        "• Username\n"
        "• Text proof\n\n"
        "❌ Use /cancel to cancel."
    )

    await query.edit_message_text(
        text,
        parse_mode="HTML",
    )

    return TASK_PROOF


# ============================================================
# TASK PROOF
# ============================================================

async def handle_task_proof_submission(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.message:
        return ConversationHandler.END

    user_id = update.effective_user.id

    task_id = context.user_data.get(
        "current_task_id"
    )

    if not task_id:

        await update.message.reply_text(
            "❌ Task session expired.",
            reply_markup=main_keyboard(),
        )

        return ConversationHandler.END

    proof_text = ""
    proof_file_id = ""
    proof_type = "text"

    # --------------------------------------------------------
    # PHOTO
    # --------------------------------------------------------

    if update.message.photo:

        proof_file_id = (
            update.message.photo[-1].file_id
        )

        proof_text = (
            update.message.caption
            or "Screenshot proof"
        )

        proof_type = "photo"

    # --------------------------------------------------------
    # DOCUMENT
    # --------------------------------------------------------

    elif update.message.document:

        proof_file_id = (
            update.message.document.file_id
        )

        proof_text = (
            update.message.caption
            or "Document proof"
        )

        proof_type = "document"

    # --------------------------------------------------------
    # TEXT
    # --------------------------------------------------------

    elif update.message.text:

        proof_text = (
            update.message.text.strip()
        )

        proof_type = "text"

    else:

        await update.message.reply_text(
            "❌ Please send a screenshot, "
            "document, or text proof."
        )

        return TASK_PROOF

    conn = db()

    task = conn.execute(
        """
        SELECT title, reward
        FROM tasks
        WHERE id = ?
        AND is_active = 1
        """,
        (task_id,),
    ).fetchone()

    if not task:

        conn.close()

        await update.message.reply_text(
            "❌ Task not found.",
            reply_markup=main_keyboard(),
        )

        return ConversationHandler.END

    existing = conn.execute(
        """
        SELECT id
        FROM task_submissions
        WHERE task_id = ?
        AND user_id = ?
        AND status IN (
            'PENDING',
            'APPROVED'
        )
        """,
        (
            task_id,
            user_id,
        ),
    ).fetchone()

    if existing:

        conn.close()

        await update.message.reply_text(
            "⚠️ You already submitted this task.",
            reply_markup=main_keyboard(),
        )

        return ConversationHandler.END

    cursor = conn.execute(
        """
        INSERT INTO task_submissions (
            task_id,
            user_id,
            proof_text,
            proof_file_id,
            proof_type,
            status
        )
        VALUES (?, ?, ?, ?, ?, 'PENDING')
        """,
        (
            task_id,
            user_id,
            proof_text,
            proof_file_id,
            proof_type,
        ),
    )

    submission_id = cursor.lastrowid

    conn.commit()
    conn.close()

    user = get_user(user_id)

    username = (
        f"@{safe(user['username'])}"
        if user and user["username"]
        else "N/A"
    )

    admin_text = (
        f"📥 <b>NEW TASK PROOF #{submission_id}</b>\n\n"
        f"👤 User ID: <code>{user_id}</code>\n"
        f"Username: {username}\n"
        f"📌 Task: <b>{safe(task['title'])}</b>\n"
        f"💰 Reward: "
        f"<b>{task['reward']:.2f} ETB</b>\n\n"
        f"📝 Proof:\n{safe(proof_text)}"
    )

    buttons = [
        [
            InlineKeyboardButton(
                "✅ Approve",
                callback_data=(
                    f"tappr_{submission_id}"
                ),
            ),
            InlineKeyboardButton(
                "❌ Reject",
                callback_data=(
                    f"trej_{submission_id}"
                ),
            ),
        ]
    ]

    for admin_id in ADMIN_IDS:

        try:

            markup = InlineKeyboardMarkup(
                buttons
            )

            if proof_type == "photo":

                await context.bot.send_photo(
                    chat_id=admin_id,
                    photo=proof_file_id,
                    caption=admin_text,
                    reply_markup=markup,
                    parse_mode="HTML",
                )

            elif proof_type == "document":

                await context.bot.send_document(
                    chat_id=admin_id,
                    document=proof_file_id,
                    caption=admin_text,
                    reply_markup=markup,
                    parse_mode="HTML",
                )

            else:

                await context.bot.send_message(
                    chat_id=admin_id,
                    text=admin_text,
                    reply_markup=markup,
                    parse_mode="HTML",
                )

        except Exception as e:

            logger.warning(
                "Task proof admin notification failed: %s",
                e,
            )

    context.user_data.pop(
        "current_task_id",
        None,
    )

    await update.message.reply_text(
        "✅ <b>PROOF SUBMITTED!</b>\n\n"
        "Your submission has been sent to Admin "
        "for review.",
        reply_markup=main_keyboard(),
        parse_mode="HTML",
    )

    return ConversationHandler.END


# ============================================================
# CANCEL COMMAND
# ============================================================

async def cancel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    context.user_data.clear()

    await update.message.reply_text(
        "❌ <b>Cancelled.</b>",
        reply_markup=main_keyboard(),
        parse_mode="HTML",
    )

    return ConversationHandler.END


# ============================================================
# SUPPORT
# ============================================================

async def handle_support(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await require_verified(update):
        return

    username = SUPPORT_USERNAME

    buttons = [
        [
            InlineKeyboardButton(
                "📞 Contact Support",
                url=f"https://t.me/{username}",
            )
        ]
    ]

    await update.message.reply_text(
        "📞 <b>FALCON WORLD SUPPORT</b>\n\n"
        "For support, questions, advertising "
        "or promotions, contact Admin.\n\n"
        f"👤 Support: <b>@{safe(username)}</b>",
        reply_markup=InlineKeyboardMarkup(
            buttons
        ),
        parse_mode="HTML",
    )


# ============================================================
# HELP
# ============================================================

async def handle_help(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not await require_verified(update):
        return

    daily = get_setting(
        "daily_bonus",
        DAILY_BONUS,
    )

    referral = get_setting(
        "referral_reward",
        REFERRAL_REWARD,
    )

    minimum = get_setting(
        "min_withdraw",
        MIN_WITHDRAW,
    )

    await update.message.reply_text(
        "❓ <b>FALCON WORLD HELP</b>\n\n"
        "💰 <b>Balance</b>\n"
        "Check your current balance and wallets.\n\n"
        "🎁 <b>Daily Bonus</b>\n"
        f"Claim <b>{daily:.2f} ETB</b> every 24 hours.\n\n"
        "👥 <b>Invite Friends</b>\n"
        f"Earn <b>{referral:.2f} ETB</b> after "
        "your referred user completes verification.\n\n"
        "📋 <b>Tasks</b>\n"
        "Complete tasks and submit proof.\n\n"
        "💳 <b>Wallet Settings</b>\n"
        "Save CBE or Telebirr.\n\n"
        "🔻 <b>Withdraw</b>\n"
        f"Minimum: <b>{minimum:.2f} ETB</b>.\n\n"
        "📢 <b>Ads & Promotions</b>\n"
        "Contact Admin for advertising and promotions.",
        parse_mode="HTML",
    )


# ============================================================
# ADMIN NOTIFY
# ============================================================

async def notify_admins(
    context,
    text,
):

    for admin_id in ADMIN_IDS:

        try:

            await context.bot.send_message(
                chat_id=admin_id,
                text=text,
                parse_mode="HTML",
            )

        except Exception as e:

            logger.warning(
                "Admin notification error: %s",
                e,
            )


# ============================================================
# ADMIN CHECK
# ============================================================

def is_admin(user_id):

    return user_id in ADMIN_IDS


# ============================================================
# ADMIN DASHBOARD
# ============================================================

async def admin_dashboard(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not is_admin(
        update.effective_user.id
    ):
        return

    conn = db()

    total_users = conn.execute(
        "SELECT COUNT(*) FROM users"
    ).fetchone()[0]

    verified = conn.execute(
        """
        SELECT COUNT(*)
        FROM users
        WHERE verified = 1
        """
    ).fetchone()[0]

    total_balance = conn.execute(
        """
        SELECT COALESCE(
            SUM(balance),
            0
        )
        FROM users
        """
    ).fetchone()[0]

    pending_withdrawals = conn.execute(
        """
        SELECT COUNT(*)
        FROM withdrawals
        WHERE status = 'PENDING'
        """
    ).fetchone()[0]

    pending_tasks = conn.execute(
        """
        SELECT COUNT(*)
        FROM task_submissions
        WHERE status = 'PENDING'
        """
    ).fetchone()[0]

    suspicious = conn.execute(
        """
        SELECT COUNT(*)
        FROM users
        WHERE suspicious = 1
        """
    ).fetchone()[0]

    conn.close()

    text = (
        "⚙️ <b>FALCON WORLD ADMIN PANEL</b>\n\n"
        f"👥 Total Users: <b>{total_users}</b>\n"
        f"✅ Verified: <b>{verified}</b>\n"
        f"💰 User Balances: "
        f"<b>{total_balance:.2f} ETB</b>\n"
        f"🔻 Pending Withdrawals: "
        f"<b>{pending_withdrawals}</b>\n"
        f"📋 Pending Task Proofs: "
        f"<b>{pending_tasks}</b>\n"
        f"🚨 Suspicious Users: "
        f"<b>{suspicious}</b>\n\n"
        "<b>ADMIN COMMANDS</b>\n\n"
        "/users\n"
        "/checkuser USER_ID\n"
        "/ban USER_ID\n"
        "/unban USER_ID\n"
        "/addbalance USER_ID AMOUNT\n"
        "/addtask Title | Link | Reward\n"
        "/deltask TASK_ID\n"
        "/tasksadmin\n"
        "/pending\n"
        "/setref AMOUNT\n"
        "/setdaily AMOUNT\n"
        "/setminwithdraw AMOUNT\n"
        "/settings\n"
        "/broadcast MESSAGE"
    )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
    )


# ============================================================
# ADMIN USERS
# ============================================================

async def admin_users(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not is_admin(
        update.effective_user.id
    ):
        return

    conn = db()

    total = conn.execute(
        "SELECT COUNT(*) FROM users"
    ).fetchone()[0]

    verified = conn.execute(
        """
        SELECT COUNT(*)
        FROM users
        WHERE verified = 1
        """
    ).fetchone()[0]

    banned = conn.execute(
        """
        SELECT COUNT(*)
        FROM users
        WHERE is_banned = 1
        """
    ).fetchone()[0]

    conn.close()

    await update.message.reply_text(
        "👥 <b>USERS</b>\n\n"
        f"Total: <b>{total}</b>\n"
        f"Verified: <b>{verified}</b>\n"
        f"Banned: <b>{banned}</b>",
        parse_mode="HTML",
    )


# ============================================================
# ADMIN CHECK USER
# ============================================================

async def admin_check_user(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not is_admin(
        update.effective_user.id
    ):
        return

    if not context.args:

        await update.message.reply_text(
            "Usage:\n"
            "<code>/checkuser USER_ID</code>",
            parse_mode="HTML",
        )

        return

    try:

        target_id = int(
            context.args[0]
        )

    except Exception:

        await update.message.reply_text(
            "❌ Invalid User ID."
        )

        return

    user = get_user(target_id)

    if not user:

        await update.message.reply_text(
            "❌ User not found."
        )

        return

    conn = db()

    referrals = conn.execute(
        """
        SELECT COUNT(*)
        FROM referrals
        WHERE referrer_id = ?
        """,
        (target_id,),
    ).fetchone()[0]

    withdrawals = conn.execute(
        """
        SELECT COUNT(*)
        FROM withdrawals
        WHERE user_id = ?
        """,
        (target_id,),
    ).fetchone()[0]

    submissions = conn.execute(
        """
        SELECT COUNT(*)
        FROM task_submissions
        WHERE user_id = ?
        """,
        (target_id,),
    ).fetchone()[0]

    conn.close()

    username = (
        f"@{safe(user['username'])}"
        if user["username"]
        else "N/A"
    )

    text = (
        "👤 <b>USER AUDIT</b>\n\n"
        f"🆔 ID: <code>{user['user_id']}</code>\n"
        f"👤 Name: {safe(user['full_name'])}\n"
        f"Username: {username}\n"
        f"💰 Balance: "
        f"<b>{user['balance']:.2f} ETB</b>\n"
        f"👥 Referrals: <b>{referrals}</b>\n"
        f"📋 Submissions: <b>{submissions}</b>\n"
        f"🔻 Withdrawals: <b>{withdrawals}</b>\n\n"
        f"🏦 CBE: "
        f"<code>{safe(user['cbe_account'] or 'None')}</code>\n"
        f"📱 Telebirr: "
        f"<code>{safe(user['telebirr_account'] or 'None')}</code>\n\n"
        f"🚨 Suspicious: "
        f"<b>{user['suspicious']}</b>\n"
        f"⛔ Banned: "
        f"<b>{user['is_banned']}</b>\n"
        f"✅ Verified: "
        f"<b>{user['verified']}</b>"
    )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
    )


# ============================================================
# ADMIN BAN
# ============================================================

async def admin_ban(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not is_admin(
        update.effective_user.id
    ):
        return

    if not context.args:

        await update.message.reply_text(
            "Usage: /ban USER_ID"
        )

        return

    try:

        user_id = int(
            context.args[0]
        )

    except Exception:

        await update.message.reply_text(
            "❌ Invalid User ID."
        )

        return

    conn = db()

    result = conn.execute(
        """
        UPDATE users
        SET is_banned = 1
        WHERE user_id = ?
        """,
        (user_id,),
    )

    conn.commit()
    conn.close()

    if result.rowcount == 0:

        await update.message.reply_text(
            "❌ User not found."
        )

        return

    try:

        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "⛔ <b>Your Falcon World account "
                "has been suspended.</b>"
            ),
            parse_mode="HTML",
        )

    except Exception:
        pass

    await update.message.reply_text(
        f"⛔ User <code>{user_id}</code> banned.",
        parse_mode="HTML",
    )


# ============================================================
# ADMIN UNBAN
# ============================================================

async def admin_unban(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not is_admin(
        update.effective_user.id
    ):
        return

    if not context.args:

        await update.message.reply_text(
            "Usage: /unban USER_ID"
        )

        return

    try:

        user_id = int(
            context.args[0]
        )

    except Exception:

        await update.message.reply_text(
            "❌ Invalid User ID."
        )

        return

    conn = db()

    result = conn.execute(
        """
        UPDATE users
        SET is_banned = 0
        WHERE user_id = ?
        """,
        (user_id,),
    )

    conn.commit()
    conn.close()

    if result.rowcount == 0:

        await update.message.reply_text(
            "❌ User not found."
        )

        return

    await update.message.reply_text(
        f"✅ User <code>{user_id}</code> unbanned.",
        parse_mode="HTML",
    )


# ============================================================
# ADMIN ADD BALANCE
# ============================================================

async def admin_add_balance(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not is_admin(
        update.effective_user.id
    ):
        return

    if len(context.args) < 2:

        await update.message.reply_text(
            "Usage:\n"
            "/addbalance USER_ID AMOUNT"
        )

        return

    try:

        user_id = int(
            context.args[0]
        )

        amount = float(
            context.args[1]
        )

        if amount <= 0:
            raise ValueError

    except Exception:

        await update.message.reply_text(
            "❌ Invalid User ID or amount."
        )

        return

    conn = db()

    user = conn.execute(
        """
        SELECT user_id
        FROM users
        WHERE user_id = ?
        """,
        (user_id,),
    ).fetchone()

    if not user:

        conn.close()

        await update.message.reply_text(
            "❌ User not found."
        )

        return

    conn.execute(
        """
        UPDATE users
        SET balance = balance + ?
        WHERE user_id = ?
        """,
        (
            amount,
            user_id,
        ),
    )

    new_balance = conn.execute(
        """
        SELECT balance
        FROM users
        WHERE user_id = ?
        """,
        (user_id,),
    ).fetchone()["balance"]

    conn.commit()
    conn.close()

    try:

        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "💰 <b>BALANCE CREDITED</b>\n\n"
                f"Amount: <b>+{amount:.2f} ETB</b>\n"
                f"New Balance: "
                f"<b>{new_balance:.2f} ETB</b>"
            ),
            parse_mode="HTML",
        )

    except Exception:
        pass

    await update.message.reply_text(
        "✅ Balance updated.\n\n"
        f"User: <code>{user_id}</code>\n"
        f"Added: <b>{amount:.2f} ETB</b>\n"
        f"New Balance: "
        f"<b>{new_balance:.2f} ETB</b>",
        parse_mode="HTML",
    )


# ============================================================
# ADMIN ADD TASK
# ============================================================

async def admin_add_task(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not is_admin(
        update.effective_user.id
    ):
        return

    if not update.message.text:

        return

    try:

        raw = update.message.text.split(
            " ",
            1,
        )[1]

        parts = [
            x.strip()
            for x in raw.split("|")
        ]

        if len(parts) != 3:
            raise ValueError

        title, link, reward = parts

        reward = float(reward)

        if not title or reward <= 0:
            raise ValueError

    except Exception:

        await update.message.reply_text(
            "❌ <b>Wrong format</b>\n\n"
            "<code>/addtask Join Channel | "
            "https://t.me/example | 2</code>",
            parse_mode="HTML",
        )

        return

    conn = db()

    cursor = conn.execute(
        """
        INSERT INTO tasks (
            title,
            link,
            reward,
            is_active
        )
        VALUES (?, ?, ?, 1)
        """,
        (
            title,
            link,
            reward,
        ),
    )

    task_id = cursor.lastrowid

    conn.commit()
    conn.close()

    await update.message.reply_text(
        "✅ <b>TASK CREATED</b>\n\n"
        f"🆔 ID: <code>{task_id}</code>\n"
        f"📌 {safe(title)}\n"
        f"💰 {reward:.2f} ETB\n"
        f"🔗 {safe(link)}",
        parse_mode="HTML",
    )


# ============================================================
# ADMIN DELETE TASK
# ============================================================

async def admin_delete_task(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not is_admin(
        update.effective_user.id
    ):
        return

    if not context.args:

        await update.message.reply_text(
            "Usage: /deltask TASK_ID"
        )

        return

    try:

        task_id = int(
            context.args[0]
        )

    except Exception:

        await update.message.reply_text(
            "❌ Invalid task ID."
        )

        return

    conn = db()

    result = conn.execute(
        """
        UPDATE tasks
        SET is_active = 0
        WHERE id = ?
        """,
        (task_id,),
    )

    conn.commit()
    conn.close()

    if result.rowcount == 0:

        await update.message.reply_text(
            "❌ Task not found."
        )

        return

    await update.message.reply_text(
        f"✅ Task <code>{task_id}</code> deactivated.",
        parse_mode="HTML",
    )


# ============================================================
# ADMIN TASKS
# ============================================================

async def admin_tasks(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not is_admin(
        update.effective_user.id
    ):
        return

    conn = db()

    tasks = conn.execute(
        """
        SELECT id, title, reward, is_active
        FROM tasks
        ORDER BY id DESC
        LIMIT 30
        """
    ).fetchall()

    conn.close()

    if not tasks:

        await update.message.reply_text(
            "📋 No tasks found."
        )

        return

    text = "📋 <b>TASKS</b>\n\n"

    for task in tasks:

        status = (
            "🟢 ACTIVE"
            if task["is_active"]
            else "🔴 OFF"
        )

        text += (
            f"#{task['id']} — "
            f"{safe(task['title'])}\n"
            f"💰 {task['reward']:.2f} ETB • "
            f"{status}\n\n"
        )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
    )


# ============================================================
# ADMIN PENDING WITHDRAWALS
# ============================================================

async def admin_pending(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not is_admin(
        update.effective_user.id
    ):
        return

    conn = db()

    rows = conn.execute(
        """
        SELECT
            id,
            user_id,
            amount,
            method,
            account_number,
            created_at
        FROM withdrawals
        WHERE status = 'PENDING'
        ORDER BY id DESC
        LIMIT 30
        """
    ).fetchall()

    conn.close()

    if not rows:

        await update.message.reply_text(
            "✅ No pending withdrawals."
        )

        return

    text = "🔻 <b>PENDING WITHDRAWALS</b>\n\n"

    for row in rows:

        text += (
            f"#{row['id']} • "
            f"User <code>{row['user_id']}</code>\n"
            f"💰 {row['amount']:.2f} ETB\n"
            f"💳 {safe(row['method'])}\n"
            f"🏦 <code>{safe(row['account_number'])}</code>\n\n"
        )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
    )


# ============================================================
# ADMIN SET REFERRAL
# ============================================================

async def admin_set_ref(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not is_admin(
        update.effective_user.id
    ):
        return

    if not context.args:

        await update.message.reply_text(
            "Usage: /setref AMOUNT"
        )

        return

    try:

        amount = float(
            context.args[0]
        )

        if amount < 0:
            raise ValueError

    except Exception:

        await update.message.reply_text(
            "❌ Invalid amount."
        )

        return

    set_setting(
        "referral_reward",
        amount,
    )

    await update.message.reply_text(
        "✅ Referral reward updated to "
        f"<b>{amount:.2f} ETB</b>.",
        parse_mode="HTML",
    )


# ============================================================
# ADMIN SET DAILY
# ============================================================

async def admin_set_daily(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not is_admin(
        update.effective_user.id
    ):
        return

    if not context.args:

        await update.message.reply_text(
            "Usage: /setdaily AMOUNT"
        )

        return

    try:

        amount = float(
            context.args[0]
        )

        if amount < 0:
            raise ValueError

    except Exception:

        await update.message.reply_text(
            "❌ Invalid amount."
        )

        return

    set_setting(
        "daily_bonus",
        amount,
    )

    await update.message.reply_text(
        "✅ Daily bonus updated to "
        f"<b>{amount:.2f} ETB</b>.",
        parse_mode="HTML",
    )


# ============================================================
# ADMIN SET MIN WITHDRAW
# ============================================================

async def admin_set_min_withdraw(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not is_admin(
        update.effective_user.id
    ):
        return

    if not context.args:

        await update.message.reply_text(
            "Usage: /setminwithdraw AMOUNT"
        )

        return

    try:

        amount = float(
            context.args[0]
        )

        if amount <= 0:
            raise ValueError

    except Exception:

        await update.message.reply_text(
            "❌ Invalid amount."
        )

        return

    set_setting(
        "min_withdraw",
        amount,
    )

    await update.message.reply_text(
        "✅ Minimum withdrawal updated to "
        f"<b>{amount:.2f} ETB</b>.",
        parse_mode="HTML",
    )


# ============================================================
# ADMIN SETTINGS
# ============================================================

async def admin_settings(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not is_admin(
        update.effective_user.id
    ):
        return

    daily = get_setting(
        "daily_bonus",
        DAILY_BONUS,
    )

    referral = get_setting(
        "referral_reward",
        REFERRAL_REWARD,
    )

    minimum = get_setting(
        "min_withdraw",
        MIN_WITHDRAW,
    )

    await update.message.reply_text(
        "⚙️ <b>FALCON WORLD SETTINGS</b>\n\n"
        f"🎁 Daily Bonus: "
        f"<b>{daily:.2f} ETB</b>\n"
        f"👥 Referral Reward: "
        f"<b>{referral:.2f} ETB</b>\n"
        f"🔻 Minimum Withdrawal: "
        f"<b>{minimum:.2f} ETB</b>",
        parse_mode="HTML",
    )


# ============================================================
# ADMIN BROADCAST
# ============================================================

async def admin_broadcast(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not is_admin(
        update.effective_user.id
    ):
        return

    if not context.args:

        await update.message.reply_text(
            "Usage:\n"
            "/broadcast Your message"
        )

        return

    message = update.message.text.split(
        " ",
        1,
    )[1].strip()

    conn = db()

    users = conn.execute(
        """
        SELECT user_id
        FROM users
        WHERE is_banned = 0
        """
    ).fetchall()

    conn.close()

    sent = 0
    failed = 0

    for row in users:

        try:

            await context.bot.send_message(
                chat_id=row["user_id"],
                text=message,
            )

            sent += 1

        except Exception:

            failed += 1

    await update.message.reply_text(
        "📢 <b>BROADCAST FINISHED</b>\n\n"
        f"✅ Sent: <b>{sent}</b>\n"
        f"❌ Failed: <b>{failed}</b>",
        parse_mode="HTML",
    )


# ============================================================
# ADMIN CALLBACKS
# ============================================================

async def handle_admin_callbacks(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    # Security check BEFORE execution
    if query.from_user.id not in ADMIN_IDS:

        await query.answer(
            "⛔ Admin only.",
            show_alert=True,
        )

        return

    await query.answer()

    data = query.data

    conn = db()

    try:

        # ====================================================
        # WITHDRAW APPROVE
        # ====================================================

        if data.startswith("adm_appr_"):

            withdrawal_id = int(
                data.split("_")[2]
            )

            row = conn.execute(
                """
                SELECT
                    user_id,
                    amount,
                    status
                FROM withdrawals
                WHERE id = ?
                """,
                (withdrawal_id,),
            ).fetchone()

            if not row:

                await query.edit_message_text(
                    "❌ Withdrawal not found."
                )

                return

            if row["status"] != "PENDING":

                await query.answer(
                    "Already processed.",
                    show_alert=True,
                )

                return

            conn.execute(
                """
                UPDATE withdrawals
                SET status = 'APPROVED'
                WHERE id = ?
                """,
                (withdrawal_id,),
            )

            conn.commit()

            original = (
                query.message.text
                or ""
            )

            await query.edit_message_text(
                original +
                "\n\n"
                "✅ <b>APPROVED</b>",
                parse_mode="HTML",
            )

            try:

                await context.bot.send_message(
                    chat_id=row["user_id"],
                    text=(
                        "🎉 <b>WITHDRAWAL APPROVED</b>\n\n"
                        f"💰 Amount: "
                        f"<b>{row['amount']:.2f} ETB</b>\n\n"
                        "✅ Your withdrawal has been "
                        "approved by Admin."
                    ),
                    parse_mode="HTML",
                )

            except Exception:
                pass

        # ====================================================
        # WITHDRAW REJECT
        # ====================================================

        elif data.startswith("adm_rej_"):

            withdrawal_id = int(
                data.split("_")[2]
            )

            row = conn.execute(
                """
                SELECT
                    user_id,
                    amount,
                    status
                FROM withdrawals
                WHERE id = ?
                """,
                (withdrawal_id,),
            ).fetchone()

            if not row:

                await query.edit_message_text(
                    "❌ Withdrawal not found."
                )

                return

            if row["status"] != "PENDING":

                await query.answer(
                    "Already processed.",
                    show_alert=True,
                )

                return

            conn.execute(
                """
                UPDATE withdrawals
                SET status = 'REJECTED'
                WHERE id = ?
                """,
                (withdrawal_id,),
            )

            conn.execute(
                """
                UPDATE users
                SET balance = balance + ?
                WHERE user_id = ?
                """,
                (
                    row["amount"],
                    row["user_id"],
                ),
            )

            conn.commit()

            original = (
                query.message.text
                or ""
            )

            await query.edit_message_text(
                original +
                "\n\n"
                "❌ <b>REJECTED & REFUNDED</b>",
                parse_mode="HTML",
            )

            try:

                await context.bot.send_message(
                    chat_id=row["user_id"],
                    text=(
                        "❌ <b>WITHDRAWAL REJECTED</b>\n\n"
                        f"💰 <b>{row['amount']:.2f} ETB</b> "
                        "has been returned to your balance."
                    ),
                    parse_mode="HTML",
                )

            except Exception:
                pass

        # ====================================================
        # BAN
        # ====================================================

        elif data.startswith("adm_ban_"):

            user_id = int(
                data.split("_")[2]
            )

            conn.execute(
                """
                UPDATE users
                SET is_banned = 1
                WHERE user_id = ?
                """,
                (user_id,),
            )

            conn.commit()

            original = (
                query.message.text
                or ""
            )

            await query.edit_message_text(
                original +
                f"\n\n⛔ <b>USER {user_id} BANNED</b>",
                parse_mode="HTML",
            )

            try:

                await context.bot.send_message(
                    chat_id=user_id,
                    text=(
                        "⛔ <b>FALCON WORLD ACCOUNT SUSPENDED</b>\n\n"
                        "Your account has been suspended "
                        "by Admin."
                    ),
                    parse_mode="HTML",
                )

            except Exception:
                pass

        # ====================================================
        # TASK APPROVE
        # ====================================================

        elif data.startswith("tappr_"):

            submission_id = int(
                data.split("_")[1]
            )

            row = conn.execute(
                """
                SELECT
                    ts.user_id,
                    ts.status,
                    t.reward,
                    t.title
                FROM task_submissions ts
                JOIN tasks t
                    ON ts.task_id = t.id
                WHERE ts.id = ?
                """,
                (submission_id,),
            ).fetchone()

            if not row:

                await edit_admin_message(
                    query,
                    "❌ Submission not found.",
                )

                return

            if row["status"] != "PENDING":

                await query.answer(
                    "Already processed.",
                    show_alert=True,
                )

                return

            conn.execute(
                """
                UPDATE task_submissions
                SET status = 'APPROVED'
                WHERE id = ?
                """,
                (submission_id,),
            )

            conn.execute(
                """
                UPDATE users
                SET balance = balance + ?
                WHERE user_id = ?
                """,
                (
                    row["reward"],
                    row["user_id"],
                ),
            )

            conn.commit()

            await edit_admin_message(
                query,
                (
                    "✅ <b>APPROVED & REWARDED</b>\n\n"
                    f"Task: <b>{safe(row['title'])}</b>\n"
                    f"User: <code>{row['user_id']}</code>\n"
                    f"Reward: "
                    f"<b>+{row['reward']:.2f} ETB</b>"
                ),
            )

            try:

                await context.bot.send_message(
                    chat_id=row["user_id"],
                    text=(
                        "🎉 <b>TASK APPROVED!</b>\n\n"
                        f"📌 {safe(row['title'])}\n"
                        f"💰 <b>+{row['reward']:.2f} ETB</b>"
                    ),
                    parse_mode="HTML",
                )

            except Exception:
                pass

        # ====================================================
        # TASK REJECT
        # ====================================================

        elif data.startswith("trej_"):

            submission_id = int(
                data.split("_")[1]
            )

            row = conn.execute(
                """
                SELECT
                    user_id,
                    status
                FROM task_submissions
                WHERE id = ?
                """,
                (submission_id,),
            ).fetchone()

            if not row:

                await edit_admin_message(
                    query,
                    "❌ Submission not found.",
                )

                return

            if row["status"] != "PENDING":

                await query.answer(
                    "Already processed.",
                    show_alert=True,
                )

                return

            conn.execute(
                """
                UPDATE task_submissions
                SET status = 'REJECTED'
                WHERE id = ?
                """,
                (submission_id,),
            )

            conn.commit()

            await edit_admin_message(
                query,
                (
                    "❌ <b>PROOF REJECTED</b>\n\n"
                    f"User: <code>{row['user_id']}</code>"
                ),
            )

            try:

                await context.bot.send_message(
                    chat_id=row["user_id"],
                    text=(
                        "❌ <b>TASK REJECTED</b>\n\n"
                        "Your submitted proof was not approved.\n"
                        "You may submit the task again."
                    ),
                    parse_mode="HTML",
                )

            except Exception:
                pass

    except Exception as e:

        logger.exception(
            "Admin callback error"
        )

        try:

            await query.answer(
                "An error occurred.",
                show_alert=True,
            )

        except Exception:
            pass

    finally:

        conn.close()


# ============================================================
# ADMIN MESSAGE EDIT HELPER
# ============================================================

async def edit_admin_message(
    query,
    text,
):

    try:

        if query.message.photo:

            await query.edit_message_caption(
                caption=text,
                parse_mode="HTML",
            )

        elif query.message.document:

            await query.edit_message_caption(
                caption=text,
                parse_mode="HTML",
            )

        else:

            await query.edit_message_text(
                text=text,
                parse_mode="HTML",
            )

    except Exception as e:

        logger.warning(
            "Admin message edit failed: %s",
            e,
        )


# ============================================================
# UNKNOWN TEXT
# ============================================================

async def unknown_text(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    if not update.message:
        return

    if is_banned(
        update.effective_user.id
    ):
        return

    await update.message.reply_text(
        "🦅 <b>Falcon World</b>\n\n"
        "Please use the menu buttons below.",
        reply_markup=main_keyboard(),
        parse_mode="HTML",
    )


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):

    logger.error(
        "Unhandled exception: %s",
        context.error,
    )


# ============================================================
# BOT COMMANDS
# ============================================================

async def setup_commands(
    application: Application,
):

    commands = [
        BotCommand(
            "start",
            "Start Falcon World",
        ),
        BotCommand(
            "cancel",
            "Cancel current action",
        ),
    ]

    await application.bot.set_my_commands(
        commands
    )


# ============================================================
# MAIN
# ============================================================

def main():

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN environment variable is missing."
        )

    if not ADMIN_IDS:

        raise RuntimeError(
            "ADMIN_IDS environment variable is missing."
        )

    application = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .post_init(setup_commands)
        .build()
    )

    # ========================================================
    # CAPTCHA CONVERSATION
    # ========================================================

    captcha_conversation = ConversationHandler(

        entry_points=[
            CommandHandler(
                "start",
                start,
            )
        ],

        states={

            CAPTCHA: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    verify_captcha,
                )
            ],

        },

        fallbacks=[
            CommandHandler(
                "cancel",
                cancel,
            )
        ],

        allow_reentry=True,
    )

    # ========================================================
    # WALLET CONVERSATION
    # ========================================================

    wallet_conversation = ConversationHandler(

        entry_points=[
            MessageHandler(
                filters.Regex(
                    r"^💳 Wallet Settings$"
                ),
                start_wallet_setup,
            )
        ],

        states={

            WALLET_TYPE: [
                CallbackQueryHandler(
                    handle_wallet_choice,
                    pattern=r"^set_wallet_(cbe|telebirr)$",
                )
            ],

            WALLET_INPUT: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    save_wallet_input,
                )
            ],

        },

        fallbacks=[
            CommandHandler(
                "cancel",
                cancel,
            )
        ],

    )

    # ========================================================
    # TASK CONVERSATION
    # ========================================================

    task_conversation = ConversationHandler(

        entry_points=[
            CallbackQueryHandler(
                process_task_click,
                pattern=r"^dotask_\d+$",
            )
        ],

        states={

            TASK_PROOF: [
                MessageHandler(
                    (
                        filters.TEXT
                        | filters.PHOTO
                        | filters.Document.ALL
                    ),
                    handle_task_proof_submission,
                )
            ],

        },

        fallbacks=[
            CommandHandler(
                "cancel",
                cancel,
            )
        ],

    )

    # ========================================================
    # CONVERSATIONS FIRST
    # ========================================================

    application.add_handler(
        captcha_conversation
    )

    application.add_handler(
        wallet_conversation
    )

    application.add_handler(
        task_conversation
    )

    # ========================================================
    # MAIN MENU
    # ========================================================

    application.add_handler(
        MessageHandler(
            filters.Regex(
                r"^💰 Balance$"
            ),
            handle_balance,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.Regex(
                r"^🎁 Daily Bonus$"
            ),
            handle_daily_bonus,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.Regex(
                r"^👥 Invite Friends$"
            ),
            handle_invite,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.Regex(
                r"^📋 Tasks$"
            ),
            handle_tasks_list,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.Regex(
                r"^🔻 Withdraw$"
            ),
            handle_withdraw_request,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.Regex(
                r"^❓ Help$"
            ),
            handle_help,
        )
    )

    application.add_handler(
        MessageHandler(
            filters.Regex(
                r"^📞 Support$"
            ),
            handle_support,
        )

    )

    # ========================================================
    # MEMBERSHIP
    # ========================================================

    application.add_handler(
        CallbackQueryHandler(
            callback_verify_membership,
            pattern=r"^verify_membership$",
        )
    )

    # ========================================================
    # WITHDRAW CALLBACKS
    # ========================================================

    application.add_handler(
        CallbackQueryHandler(
            process_withdrawal_selection,
            pattern=r"^withdraw_(cbe|telebirr)$",
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            confirm_withdraw,
            pattern=r"^confirm_withdraw$",
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            cancel_withdraw,
            pattern=r"^cancel_withdraw$",
        )
    )

    # ========================================================
    # ADMIN CALLBACKS
    # ========================================================

    application.add_handler(
        CallbackQueryHandler(
            handle_admin_callbacks,
            pattern=r"^(adm_appr_|adm_rej_|adm_ban_|tappr_|trej_)",
        )
    )

    # ========================================================
    # ADMIN COMMANDS
    # ========================================================

    application.add_handler(
        CommandHandler(
            "admin",
            admin_dashboard,
        )
    )

    application.add_handler(
        CommandHandler(
            "users",
            admin_users,
        )
    )

    application.add_handler(
        CommandHandler(
            "checkuser",
            admin_check_user,
        )
    )

    application.add_handler(
        CommandHandler(
            "ban",
            admin_ban,
        )
    )

    application.add_handler(
        CommandHandler(
            "unban",
            admin_unban,
        )
    )

    application.add_handler(
        CommandHandler(
            "addbalance",
            admin_add_balance,
        )
    )

    application.add_handler(
        CommandHandler(
            "addtask",
            admin_add_task,
        )
    )

    application.add_handler(
        CommandHandler(
            "deltask",
            admin_delete_task,
        )
    )

    application.add_handler(
        CommandHandler(
            "tasksadmin",
            admin_tasks,
        )
    )

    application.add_handler(
        CommandHandler(
            "pending",
            admin_pending,
        )
    )

    application.add_handler(
        CommandHandler(
            "setref",
            admin_set_ref,
        )
    )

    application.add_handler(
        CommandHandler(
            "setdaily",
            admin_set_daily,
        )
    )

    application.add_handler(
        CommandHandler(
            "setminwithdraw",
            admin_set_min_withdraw,
        )
    )

    application.add_handler(
        CommandHandler(
            "settings",
            admin_settings,
        )
    )

    application.add_handler(
        CommandHandler(
            "broadcast",
            admin_broadcast,
        )
    )

    # ========================================================
    # UNKNOWN TEXT
    # ========================================================

    application.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            unknown_text,
        )
    )

    # ========================================================
    # ERROR HANDLER
    # ========================================================

    application.add_error_handler(
        error_handler
    )

    logger.info(
        "🦅 Falcon World is starting..."
    )

    application.run_polling(
        drop_pending_updates=True
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
