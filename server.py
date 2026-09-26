import os, re, json, base64, hmac, hashlib, time, asyncio, html, sqlite3, secrets, random
from datetime import datetime, timedelta
from urllib.parse import parse_qsl
from typing import Optional

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", os.getenv("ADMIN_ID", "")).strip()
ADMIN_IDS = {int(x.strip()) for x in ADMIN_IDS_RAW.split(",") if x.strip().isdigit()}
BOT_USERNAME = os.getenv("BOT_USERNAME", "FalconWorld_Bot").strip().lstrip("@")
MINI_APP_URL = os.getenv("MINI_APP_URL", "https://falcon-world.onrender.com/app").strip()
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://falcon-world.onrender.com/webhook").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
DB_PATH = os.getenv("DB_PATH", "falcon_world.db").strip() or "falcon_world.db"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FALCON_BG_PATH = os.path.join(BASE_DIR, "falcon-bg.webp")

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
CAPTCHA_SESSIONS = {}


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
            user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
            balance REAL NOT NULL DEFAULT 0, referral_earnings REAL NOT NULL DEFAULT 0,
            daily_bonus_earnings REAL NOT NULL DEFAULT 0, task_earnings REAL NOT NULL DEFAULT 0,
            verified INTEGER NOT NULL DEFAULT 0, banned INTEGER NOT NULL DEFAULT 0,
            referred_by INTEGER, referral_reward_paid INTEGER NOT NULL DEFAULT 0,
            daily_last_claim INTEGER NOT NULL DEFAULT 0, wallet_type TEXT, wallet_number TEXT,
            wallet_suspicious INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, amount REAL NOT NULL,
            wallet_type TEXT NOT NULL, wallet_number TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
            suspicious INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL, processed_at INTEGER,
            processed_by INTEGER, FOREIGN KEY(user_id) REFERENCES users(user_id)
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
            reward REAL NOT NULL DEFAULT 0, url TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS task_submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
            proof TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', created_at INTEGER NOT NULL,
            reviewed_at INTEGER, reviewed_by INTEGER, FOREIGN KEY(task_id) REFERENCES tasks(id), FOREIGN KEY(user_id) REFERENCES users(user_id)
        );
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS required_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
            url TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, created_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_withdrawals_status ON withdrawals(status);
        CREATE INDEX IF NOT EXISTS idx_submissions_task_user ON task_submissions(task_id,user_id);
        CREATE TABLE IF NOT EXISTS fraud_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, event_type TEXT NOT NULL,
            risk_score INTEGER NOT NULL DEFAULT 0, details TEXT NOT NULL DEFAULT '', ip_address TEXT,
            device_hash TEXT, created_at INTEGER NOT NULL, reviewed INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(user_id) REFERENCES users(user_id)
        );
        CREATE TABLE IF NOT EXISTS access_fingerprints (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, ip_address TEXT,
            device_hash TEXT, first_seen INTEGER NOT NULL, last_seen INTEGER NOT NULL,
            UNIQUE(user_id, ip_address, device_hash), FOREIGN KEY(user_id) REFERENCES users(user_id)
        );
        """)
        existing = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
        for col, definition in {
            "referral_earnings": "REAL NOT NULL DEFAULT 0",
            "daily_bonus_earnings": "REAL NOT NULL DEFAULT 0",
            "task_earnings": "REAL NOT NULL DEFAULT 0",
            "risk_score": "INTEGER NOT NULL DEFAULT 0",
            "risk_flags": "TEXT NOT NULL DEFAULT ''",
            "last_ip": "TEXT",
            "last_device_hash": "TEXT",
        }.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE users ADD COLUMN {col} {definition}")
        if conn.execute("SELECT COUNT(*) c FROM required_channels").fetchone()["c"] == 0:
            now = int(time.time())
            conn.executemany(
                "INSERT OR IGNORE INTO required_channels(username,name,url,active,created_at) VALUES(?,?,?,?,?)",
                [(c["username"], c["name"], c["url"], 1, now) for c in REQUIRED_CHANNELS],
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


def get_setting(key, default=None):
    conn = db()
    try:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        if not row: return default
        if isinstance(default, int): return int(float(row["value"]))
        if isinstance(default, float): return float(row["value"])
        return row["value"]
    finally: conn.close()


def set_setting(key, value):
    conn = db()
    try:
        conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
        conn.commit()
    finally: conn.close()


def configure_bot():
    global BOT_TOKEN, TELEGRAM_API
    BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
    TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else ""


async def telegram_request(method: str, data: Optional[dict] = None):
    if not BOT_TOKEN: return {"ok": False, "description": "BOT_TOKEN is missing"}
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            r = await client.post(f"{TELEGRAM_API}/{method}", json=data or {})
            try: return r.json()
            except Exception: return {"ok": False, "description": f"HTTP {r.status_code}"}
    except Exception as e: return {"ok": False, "description": str(e)}


async def send_message(chat_id: int, text: str, reply_markup=None):
    data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
    if reply_markup: data["reply_markup"] = reply_markup
    return await telegram_request("sendMessage", data)


async def send_admin_message(text, keyboard=None):
    return [await send_message(a, text, keyboard) for a in ADMIN_IDS]


def is_admin(uid): return int(uid) in ADMIN_IDS


def ensure_user(user_id, username="", first_name="", referred_by=None):
    now = int(time.time()); conn = db()
    try:
        row = conn.execute("SELECT user_id,referred_by FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            conn.execute("""INSERT INTO users(user_id,username,first_name,balance,verified,banned,referred_by,referral_reward_paid,daily_last_claim,wallet_suspicious,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (user_id, username or "", first_name or "", 0, 0, 0, referred_by if referred_by != user_id else None, 0, 0, 0, now, now))
        else:
            conn.execute("UPDATE users SET username=?,first_name=?,updated_at=? WHERE user_id=?", (username or "", first_name or "", now, user_id))
            if referred_by and not row["referred_by"] and referred_by != user_id:
                conn.execute("UPDATE users SET referred_by=? WHERE user_id=?", (referred_by, user_id))
        conn.commit()
    finally: conn.close()


def get_user(uid):
    conn = db()
    try: return conn.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone()
    finally: conn.close()


def is_banned(uid):
    r = get_user(uid); return bool(r and r["banned"])


def add_balance(uid, amount):
    conn = db()
    try:
        conn.execute("UPDATE users SET balance=ROUND(balance+?,8),updated_at=? WHERE user_id=?", (float(amount), int(time.time()), uid)); conn.commit()
    finally: conn.close()


def get_referral_count(uid):
    conn = db()
    try: return int(conn.execute("SELECT COUNT(*) c FROM users WHERE referred_by=? AND referral_reward_paid=1", (uid,)).fetchone()["c"])
    finally: conn.close()


def local_date(ts=None):
    try:
        from zoneinfo import ZoneInfo
        return datetime.fromtimestamp(ts or time.time(), ZoneInfo("Africa/Addis_Ababa")).date()
    except Exception: return datetime.utcfromtimestamp(ts or time.time()).date()


def claim_daily_bonus(uid):
    now=int(time.time()); today=local_date(now); reward=float(get_setting("daily_bonus",DEFAULT_DAILY_BONUS)); conn=db()
    try:
        conn.execute("BEGIN IMMEDIATE"); row=conn.execute("SELECT banned,verified,daily_last_claim,balance FROM users WHERE user_id=?",(uid,)).fetchone()
        if not row: conn.rollback(); return False,{"error":"user_not_found"}
        if row["banned"]: conn.rollback(); return False,{"error":"banned"}
        if not row["verified"]: conn.rollback(); return False,{"error":"not_verified"}
        last=int(row["daily_last_claim"] or 0)
        if last and local_date(last)==today: conn.rollback(); return False,{"error":"already_claimed","date":str(today)}
        conn.execute("UPDATE users SET balance=ROUND(balance+?,8),daily_bonus_earnings=ROUND(daily_bonus_earnings+?,8),daily_last_claim=?,updated_at=? WHERE user_id=?",(reward,reward,now,now,uid)); conn.commit()
        return True,{"reward":reward,"balance":float(row["balance"])+reward,"date":str(today),"next_date":str(today+timedelta(days=1))}
    except Exception: conn.rollback(); raise
    finally: conn.close()


def reward_referrer_after_verification(uid):
    conn=db()
    try:
        conn.execute("BEGIN IMMEDIATE"); child=conn.execute("SELECT referred_by,verified,referral_reward_paid FROM users WHERE user_id=?",(uid,)).fetchone()
        if not child or not child["verified"] or child["referral_reward_paid"]: conn.rollback(); return None
        rid=child["referred_by"]
        if not rid or rid==uid:
            conn.execute("UPDATE users SET referral_reward_paid=1,updated_at=? WHERE user_id=?",(int(time.time()),uid)); conn.commit(); return None
        ref=conn.execute("SELECT banned FROM users WHERE user_id=?",(rid,)).fetchone(); now=int(time.time())
        if not ref or ref["banned"]:
            conn.execute("UPDATE users SET referral_reward_paid=1,updated_at=? WHERE user_id=?",(now,uid)); conn.commit(); return None
        reward=float(get_setting("referral_reward",DEFAULT_REFERRAL_REWARD))
        conn.execute("UPDATE users SET balance=ROUND(balance+?,8),referral_earnings=ROUND(referral_earnings+?,8),updated_at=? WHERE user_id=?",(reward,reward,now,rid))
        conn.execute("UPDATE users SET referral_reward_paid=1,updated_at=? WHERE user_id=?",(now,uid)); conn.commit(); return reward
    except Exception: conn.rollback(); raise
    finally: conn.close()


def client_ip(request):
    forwarded=request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:120]
    return (request.client.host if request.client else "")[:120]


def record_fingerprint(uid, ip_address, device_hash):
    if not ip_address and not device_hash:
        return 0, []
    conn=db(); now=int(time.time()); flags=[]; score=0
    try:
        # Same wallet is handled separately; this checks network/device reuse across accounts.
        if ip_address:
            rows=conn.execute("SELECT DISTINCT user_id FROM access_fingerprints WHERE ip_address=? AND user_id!=? LIMIT 20",(ip_address,uid)).fetchall()
            if rows:
                flags.append(f"shared_ip:{len(rows)}"); score += min(35, 10*len(rows))
        if device_hash:
            rows=conn.execute("SELECT DISTINCT user_id FROM access_fingerprints WHERE device_hash=? AND user_id!=? LIMIT 20",(device_hash,uid)).fetchall()
            if rows:
                flags.append(f"shared_device:{len(rows)}"); score += min(50, 20*len(rows))
        conn.execute("INSERT INTO access_fingerprints(user_id,ip_address,device_hash,first_seen,last_seen) VALUES(?,?,?,?,?) ON CONFLICT(user_id,ip_address,device_hash) DO UPDATE SET last_seen=excluded.last_seen",(uid,ip_address,device_hash,now,now))
        conn.execute("UPDATE users SET last_ip=?,last_device_hash=?,risk_score=MAX(risk_score,?),risk_flags=?,updated_at=? WHERE user_id=?",(ip_address,device_hash,score,",".join(flags),now,uid))
        if score:
            details=f"IP={ip_address or '-'}; device={device_hash or '-'}; flags={','.join(flags)}"
            conn.execute("INSERT INTO fraud_events(user_id,event_type,risk_score,details,ip_address,device_hash,created_at) VALUES(?,?,?,?,?,?,?)",(uid,"multi_account_signal",score,details,ip_address,device_hash,now))
        conn.commit()
        return score,flags
    finally: conn.close()


async def fraud_alert(uid, score, flags, context=""):
    if not score and not flags:return
    user=get_user(uid)
    if not user:return
    await send_admin_message(
        "ðŸš¨ <b>Multi-Account Risk Alert</b>\n\n"
        f"ðŸ‘¤ {format_user(user)}\n"
        f"âš ï¸ Risk score: <b>{score}</b>\n"
        f"ðŸ”Ž Signals: <b>{html.escape(', '.join(flags) or 'unknown')}</b>\n"
        f"ðŸ“Œ Context: {html.escape(context or 'access check')}\n\n"
        "â„¹ï¸ IP/device signals are risk indicators, not proof by themselves."
    )


def save_wallet(uid,wallet_type,wallet_number):
    wt=wallet_type.strip().lower(); wn=wallet_number.strip()
    if wt=="cbe": valid=bool(re.fullmatch(r"1000\d{9}",wn)); normalized="CBE"
    elif wt=="telebirr": valid=bool(re.fullmatch(r"(09|07)\d{8}",wn)); normalized="Telebirr"
    else: return False,"Invalid wallet type",False
    if not valid: return False,("CBE must be 13 digits and start with 1000." if normalized=="CBE" else "Telebirr must be 10 digits and start with 09 or 07."),False
    conn=db()
    try:
        duplicate=conn.execute("SELECT user_id FROM users WHERE wallet_type=? AND wallet_number=? AND user_id!=?",(normalized,wn,uid)).fetchone(); suspicious=bool(duplicate)
        conn.execute("UPDATE users SET wallet_type=?,wallet_number=?,wallet_suspicious=?,updated_at=? WHERE user_id=?",(normalized,wn,int(suspicious),int(time.time()),uid)); conn.commit()
        return True,"Wallet saved successfully.",suspicious
    finally: conn.close()


def create_withdrawal(uid, requested_amount=None):
    conn=db()
    try:
        conn.execute("BEGIN IMMEDIATE"); u=conn.execute("SELECT balance,banned,wallet_type,wallet_number,wallet_suspicious FROM users WHERE user_id=?",(uid,)).fetchone()
        if not u: conn.rollback(); return False,"User not found."
        if u["banned"]: conn.rollback(); return False,"Your account is banned."
        if not u["wallet_type"] or not u["wallet_number"]: conn.rollback(); return False,"Please save your wallet first."
        minimum=float(get_setting("min_withdraw",DEFAULT_MIN_WITHDRAW)); available=float(u["balance"])
        try: amount=available if requested_amount in (None,"",0) else float(requested_amount)
        except: conn.rollback(); return False,"Invalid withdrawal amount."
        if amount<minimum: conn.rollback(); return False,f"Minimum withdrawal is {minimum:.2f} ETB."
        if amount>available: conn.rollback(); return False,"Insufficient balance."
        if conn.execute("SELECT id FROM withdrawals WHERE user_id=? AND status='pending' LIMIT 1",(uid,)).fetchone(): conn.rollback(); return False,"You already have a pending withdrawal."
        now=int(time.time()); cur=conn.execute("INSERT INTO withdrawals(user_id,amount,wallet_type,wallet_number,status,suspicious,created_at) VALUES(?,?,?,?,?,?,?)",(uid,amount,u["wallet_type"],u["wallet_number"],"pending",int(bool(u["wallet_suspicious"])),now))
        wid=cur.lastrowid; conn.execute("UPDATE users SET balance=ROUND(balance-?,8),updated_at=? WHERE user_id=?",(amount,now,uid)); conn.commit()
        return True,{"withdrawal_id":wid,"amount":amount,"wallet_type":u["wallet_type"],"wallet_number":u["wallet_number"],"suspicious":bool(u["wallet_suspicious"])}
    except Exception: conn.rollback(); raise
    finally: conn.close()


def get_active_tasks(uid):
    conn=db()
    try: return conn.execute("""SELECT t.*,(SELECT status FROM task_submissions s WHERE s.task_id=t.id AND s.user_id=? ORDER BY s.id DESC LIMIT 1) submission_status FROM tasks t WHERE t.active=1 ORDER BY t.id DESC""",(uid,)).fetchall()
    finally: conn.close()


def submit_task(uid,task_id,proof):
    proof=(proof or "").strip()
    if not proof: return False,"Proof is required."
    if len(proof)>4000: return False,"Proof is too long."
    conn=db()
    try:
        task=conn.execute("SELECT * FROM tasks WHERE id=? AND active=1",(task_id,)).fetchone()
        if not task: return False,"Task not found or inactive."
        latest=conn.execute("SELECT id,status FROM task_submissions WHERE task_id=? AND user_id=? ORDER BY id DESC LIMIT 1",(task_id,uid)).fetchone()
        if latest and latest["status"]=="pending": return False,"Your previous submission is still pending."
        if latest and latest["status"]=="approved": return False,"This task is already approved."
        now=int(time.time()); cur=conn.execute("INSERT INTO task_submissions(task_id,user_id,proof,status,created_at) VALUES(?,?,?,?,?)",(task_id,uid,proof,"pending",now)); conn.commit()
        return True,{"submission_id":cur.lastrowid,"task_id":task_id,"user_id":uid,"reward":float(task["reward"]),"title":task["title"],"proof":proof}
    finally: conn.close()


def get_required_channels():
    conn=db()
    try: return [dict(r) for r in conn.execute("SELECT id,username,name,url,active FROM required_channels WHERE active=1 ORDER BY id ASC").fetchall()]
    finally: conn.close()


def withdrawal_keyboard(wid):
    return {"inline_keyboard":[[{"text":"âœ… Approve","callback_data":f"wd_approve:{wid}"},{"text":"âŒ Reject","callback_data":f"wd_reject:{wid}"}],[{"text":"ðŸš« Ban User","callback_data":f"wd_ban:{wid}"},{"text":"ðŸ‘¥ Referral List","callback_data":f"wd_refs:{wid}"}]]}


def task_keyboard(sid): return {"inline_keyboard":[[{"text":"âœ… Approve","callback_data":f"task_approve:{sid}"},{"text":"âŒ Reject","callback_data":f"task_reject:{sid}"}]]}



def format_user(r):
    name=html.escape(r["first_name"] or r["username"] or str(r["user_id"])); un=f"@{html.escape(r['username'])}" if r["username"] else "No username"
    return f"{name} ({un}) â€” <code>{r['user_id']}</code>"


async def notify_withdrawal(wid):
    conn=db()
    try: row=conn.execute("SELECT w.*,u.username,u.first_name FROM withdrawals w JOIN users u ON u.user_id=w.user_id WHERE w.id=?",(wid,)).fetchone()
    finally: conn.close()
    if not row:return
    text=(f"ðŸ’¸ <b>New Withdrawal #{row['id']}</b>\n\nðŸ‘¤ {format_user(row)}\nðŸ’° Amount: <b>{row['amount']:.2f} ETB</b>\nðŸ¦ Wallet: <b>{html.escape(row['wallet_type'])}</b>\nðŸ“± Number: <code>{html.escape(row['wallet_number'])}</code>\nâš ï¸ Suspicious: {'YES' if row['suspicious'] else 'No'}")
    await send_admin_message(text,withdrawal_keyboard(wid))


async def notify_task_submission(sid):
    conn=db()
    try: row=conn.execute("SELECT s.*,t.title,t.reward,u.username,u.first_name FROM task_submissions s JOIN tasks t ON t.id=s.task_id JOIN users u ON u.user_id=s.user_id WHERE s.id=?",(sid,)).fetchone()
    finally: conn.close()
    if not row:return
    text=(f"ðŸ“‹ <b>New Task Submission #{sid}</b>\n\nðŸŽ¯ Task: <b>{html.escape(row['title'])}</b>\nðŸ’° Reward: <b>{row['reward']:.2f} ETB</b>\nðŸ‘¤ {format_user(row)}\n\nðŸ§¾ <b>FULL PROOF:</b>\n<pre>{html.escape(row['proof'])}</pre>")
    await send_admin_message(text,task_keyboard(sid))


async def notify_task_photo_submission(sid, photo_bytes, filename, caption):
    conn=db()
    try:
        row=conn.execute("SELECT s.*,t.title,t.reward,u.username,u.first_name FROM task_submissions s JOIN tasks t ON t.id=s.task_id JOIN users u ON u.user_id=s.user_id WHERE s.id=?",(sid,)).fetchone()
    finally: conn.close()
    if not row:return
    cap=(f"ðŸ“‹ <b>New Task Photo Proof #{sid}</b>\n\nðŸŽ¯ Task: <b>{html.escape(row['title'])}</b>\nðŸ’° Reward: <b>{row['reward']:.2f} ETB</b>\nðŸ‘¤ {format_user(row)}\nðŸ§¾ Proof note: {html.escape(caption or 'Photo proof')}" )
    keyboard=task_keyboard(sid)
    for admin_id in ADMIN_IDS:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                await client.post(f"{TELEGRAM_API}/sendPhoto",data={"chat_id":str(admin_id),"caption":cap,"parse_mode":"HTML","reply_markup":json.dumps(keyboard)},files={"photo":(filename or "proof.jpg",photo_bytes,"image/jpeg")})
        except Exception as ex:
            print("Photo proof notify error:",repr(ex))


async def answer_callback(cid,text="",alert=False): return await telegram_request("answerCallbackQuery",{"callback_query_id":cid,"text":text,"show_alert":alert})


async def edit_callback(query,text,keyboard=None):
    data={"chat_id":query["message"]["chat"]["id"],"message_id":query["message"]["message_id"],"text":text,"parse_mode":"HTML"}
    if keyboard is not None:data["reply_markup"]=keyboard
    return await telegram_request("editMessageText",data)


async def admin_stats(chat_id):
    conn=db()
    try:
        vals={
            "users":conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"],
            "verified":conn.execute("SELECT COUNT(*) c FROM users WHERE verified=1").fetchone()["c"],
            "banned":conn.execute("SELECT COUNT(*) c FROM users WHERE banned=1").fetchone()["c"],
            "flagged":conn.execute("SELECT COUNT(*) c FROM users WHERE risk_score>0 OR wallet_suspicious=1").fetchone()["c"],
            "wd":conn.execute("SELECT COUNT(*) c FROM withdrawals WHERE status='pending'").fetchone()["c"],
            "wd_amount":conn.execute("SELECT COALESCE(SUM(amount),0) s FROM withdrawals WHERE status='pending'").fetchone()["s"],
            "subs":conn.execute("SELECT COUNT(*) c FROM task_submissions WHERE status='pending'").fetchone()["c"],
            "bal":conn.execute("SELECT COALESCE(SUM(balance),0) s FROM users").fetchone()["s"],
            "paid":conn.execute("SELECT COALESCE(SUM(amount),0) s FROM withdrawals WHERE status='approved'").fetchone()["s"],
            "tasks":conn.execute("SELECT COUNT(*) c FROM tasks WHERE active=1").fetchone()["c"],
            "channels":conn.execute("SELECT COUNT(*) c FROM required_channels WHERE active=1").fetchone()["c"],
        }
    finally:conn.close()
    await send_message(chat_id,f"ðŸ›  <b>Falcon World Admin Control Center</b>\n\nðŸ‘¥ Total users: <b>{vals['users']}</b>\nâœ… Verified: <b>{vals['verified']}</b>\nðŸš« Banned: <b>{vals['banned']}</b>\nðŸš¨ Flagged/Risk: <b>{vals['flagged']}</b>\n\nðŸ’° Total system balance: <b>{vals['bal']:.2f} ETB</b>\nðŸ’¸ Pending withdrawals: <b>{vals['wd']}</b> â€” <b>{vals['wd_amount']:.2f} ETB</b>\nðŸ’µ Approved withdrawals: <b>{vals['paid']:.2f} ETB</b>\nðŸ“‹ Pending task proofs: <b>{vals['subs']}</b>\nðŸ“ Active tasks: <b>{vals['tasks']}</b>\nðŸ“£ Active required channels: <b>{vals['channels']}</b>",admin_keyboard())


async def admin_withdrawals(chat_id):
    conn=db()
    try: rows=conn.execute("SELECT w.*,u.username,u.first_name FROM withdrawals w JOIN users u ON u.user_id=w.user_id WHERE w.status='pending' ORDER BY w.id ASC LIMIT 20").fetchall()
    finally:conn.close()
    if not rows:return await send_message(chat_id,"ðŸ’¸ No pending withdrawals.",admin_keyboard())
    for r in rows:
        await send_message(chat_id,f"ðŸ’¸ <b>Withdrawal #{r['id']}</b>\n\nðŸ‘¤ {format_user(r)}\nðŸ’° <b>{r['amount']:.2f} ETB</b>\nðŸ¦ {r['wallet_type']}\nðŸ“± <code>{r['wallet_number']}</code>\nâš ï¸ Suspicious: {'YES' if r['suspicious'] else 'No'}",withdrawal_keyboard(r['id']))


async def admin_submissions(chat_id):
    conn=db()
    try: rows=conn.execute("SELECT s.*,t.title,t.reward,u.username,u.first_name FROM task_submissions s JOIN tasks t ON t.id=s.task_id JOIN users u ON u.user_id=s.user_id WHERE s.status='pending' ORDER BY s.id ASC LIMIT 20").fetchall()
    finally:conn.close()
    if not rows:return await send_message(chat_id,"ðŸ“‹ No pending task submissions.",admin_keyboard())
    for r in rows:
        await send_message(chat_id,f"ðŸ“‹ <b>Submission #{r['id']}</b>\n\nðŸŽ¯ <b>{html.escape(r['title'])}</b>\nðŸ’° {r['reward']:.2f} ETB\nðŸ‘¤ {format_user(r)}\n\nðŸ§¾ <b>FULL PROOF:</b>\n<pre>{html.escape(r['proof'])}</pre>",task_keyboard(r['id']))


async def admin_tasks(chat_id):
    conn=db()
    try: rows=conn.execute("SELECT * FROM tasks ORDER BY id DESC LIMIT 30").fetchall()
    finally:conn.close()
    if not rows:return await send_message(chat_id,"ðŸ“‹ No tasks yet.\n\nUse /addtask TITLE|DESCRIPTION|REWARD|URL",admin_keyboard())
    for r in rows:
        kb={"inline_keyboard":[[{"text":"ðŸ—‘ Disable Task","callback_data":f"task_delete:{r['id']}"}]]}
        await send_message(chat_id,f"ðŸ“‹ <b>Task #{r['id']}</b>\n\n<b>{html.escape(r['title'])}</b>\nðŸ’° {r['reward']:.2f} ETB\nðŸ“Œ Status: {'ACTIVE' if r['active'] else 'OFF'}\nðŸ”— {html.escape(r['url'])}",kb)
    await send_message(chat_id,"âž• Add another task with /addtask TITLE|DESCRIPTION|REWARD|URL",admin_keyboard())


async def admin_channels(chat_id):
    rows=get_required_channels()
    if not rows:return await send_message(chat_id,"ðŸ“£ No required channels configured.",admin_keyboard())
    for r in rows:
        kb={"inline_keyboard":[[{"text":"ðŸ—‘ Remove","callback_data":f"ch_remove:{r['id']}"},{"text":"ðŸ”„ Enable/Disable","callback_data":f"ch_toggle:{r['id']}"}]]}
        await send_message(chat_id,f"ðŸ“£ <b>{html.escape(r['name'])}</b>\n{html.escape(r['username'])}\n{html.escape(r['url'])}\nStatus: {'ACTIVE' if r['active'] else 'OFF'}",kb)
    await send_message(chat_id,"âž• Add: /addchannel @username | Name | https://t.me/username\nâœï¸ Edit: /editchannel @old | @new | Name | https://t.me/new",admin_keyboard())


async def admin_settings(chat_id):
    await send_message(chat_id,f"âš™ï¸ <b>Settings</b>\n\nðŸŽ Daily bonus: <b>{get_setting('daily_bonus',DEFAULT_DAILY_BONUS):.2f} ETB</b>\nðŸ‘¥ Referral: <b>{get_setting('referral_reward',DEFAULT_REFERRAL_REWARD):.2f} ETB</b>\nðŸ’¸ Minimum withdrawal: <b>{get_setting('min_withdraw',DEFAULT_MIN_WITHDRAW):.2f} ETB</b>\n\n/setdaily AMOUNT\n/setref AMOUNT\n/setminwithdraw AMOUNT",admin_keyboard())


async def admin_users(chat_id):
    conn=db()
    try: rows=conn.execute("SELECT * FROM users ORDER BY user_id DESC LIMIT 20").fetchall()
    finally:conn.close()
    if not rows:return await send_message(chat_id,"ðŸ‘¥ No users yet.",admin_keyboard())
    lines=["ðŸ‘¥ <b>Recent Users</b>\n"]
    for r in rows: lines.append(f"{format_user(r)}\nðŸ’° {r['balance']:.2f} ETB â€¢ {'Verified' if r['verified'] else 'Unverified'} â€¢ {'BANNED' if r['banned'] else 'Active'}")
    lines.append("\n/checkuser USER_ID\n/addbalance USER_ID AMOUNT\n/ban USER_ID\n/unban USER_ID")
    await send_message(chat_id,"\n\n".join(lines),admin_keyboard())


async def admin_user_audit(chat_id, user_id):
    user=get_user(user_id)
    if not user:return await send_message(chat_id,"âŒ User not found.",admin_keyboard())
    conn=db()
    try:
        refs=conn.execute("SELECT user_id,username,first_name,verified,banned,referral_reward_paid,balance FROM users WHERE referred_by=? ORDER BY user_id ASC",(user_id,)).fetchall()
        wd=conn.execute("SELECT id,amount,status,wallet_type,wallet_number,created_at FROM withdrawals WHERE user_id=? ORDER BY id DESC LIMIT 20",(user_id,)).fetchall()
        subs=conn.execute("SELECT s.id,s.status,s.proof,s.created_at,t.title,t.reward FROM task_submissions s JOIN tasks t ON t.id=s.task_id WHERE s.user_id=? ORDER BY s.id DESC LIMIT 20",(user_id,)).fetchall()
        fraud=conn.execute("SELECT event_type,risk_score,details,created_at FROM fraud_events WHERE user_id=? ORDER BY id DESC LIMIT 20",(user_id,)).fetchall()
    finally:conn.close()
    text=(f"ðŸ‘¤ <b>FULL USER AUDIT</b>\n\n"
          f"Name: {html.escape(user['first_name'] or 'â€”')}\nUsername: @{html.escape(user['username'] or 'none')}\nTelegram ID: <code>{user['user_id']}</code>\n"
          f"Balance: <b>{user['balance']:.2f} ETB</b>\nVerified: {'YES' if user['verified'] else 'NO'}\nBanned: {'YES' if user['banned'] else 'NO'}\n"
          f"Wallet: <b>{html.escape(user['wallet_type'] or 'Not set')}</b> / <code>{html.escape(user['wallet_number'] or 'Not set')}</code>\n"
          f"Wallet suspicious: {'YES' if user['wallet_suspicious'] else 'No'}\nRisk score: <b>{user['risk_score']}</b>\nRisk flags: {html.escape(user['risk_flags'] or 'None')}\n"
          f"Referral count: <b>{len(refs)}</b>")
    await send_message(chat_id,text,admin_keyboard())
    if refs:
        for start in range(0,len(refs),30):
            chunk=refs[start:start+30]
            lines=[f"ðŸ‘¥ <b>Referral Breakdown {start+1}-{start+len(chunk)} / {len(refs)}</b>"]
            for r in chunk:
                lines.append(f"â€¢ {format_user(r)} â€” {'Verified' if r['verified'] else 'Unverified'} â€” balance {r['balance']:.2f} ETB")
            await send_message(chat_id,"\n".join(lines))
    if wd:
        lines=["ðŸ’¸ <b>User Withdrawals</b>"]
        for r in wd: lines.append(f"#{r['id']} â€¢ {r['amount']:.2f} ETB â€¢ {html.escape(r['status'])} â€¢ {html.escape(r['wallet_type'])} <code>{html.escape(r['wallet_number'])}</code>")
        await send_message(chat_id,"\n".join(lines))
    if subs:
        lines=["ðŸ“‹ <b>User Task History</b>"]
        for r in subs: lines.append(f"#{r['id']} â€¢ {html.escape(r['title'])} â€¢ {r['reward']:.2f} ETB â€¢ {html.escape(r['status'])}\nProof: {html.escape(r['proof'][:600])}")
        await send_message(chat_id,"\n\n".join(lines))
    if fraud:
        lines=["ðŸš¨ <b>Fraud Signals</b>"]
        for r in fraud: lines.append(f"â€¢ {html.escape(r['event_type'])} â€¢ score {r['risk_score']} â€¢ {html.escape(r['details'][:500])}")
        await send_message(chat_id,"\n".join(lines))


async def admin_fraud(chat_id):
    conn=db()
    try:
        rows=conn.execute("SELECT * FROM users WHERE risk_score>0 OR wallet_suspicious=1 ORDER BY risk_score DESC,updated_at DESC LIMIT 30").fetchall()
    finally:conn.close()
    if not rows:return await send_message(chat_id,"ðŸ›¡ <b>Anti-Fraud</b>\n\nNo flagged users.",admin_keyboard())
    lines=["ðŸš¨ <b>Flagged Accounts</b>"]
    for r in rows:
        lines.append(f"â€¢ {format_user(r)}\nRisk: <b>{r['risk_score']}</b> | Wallet duplicate: {'YES' if r['wallet_suspicious'] else 'No'}\nFlags: {html.escape(r['risk_flags'] or 'â€”')}\n/checkuser {r['user_id']}")
    await send_message(chat_id,"\n\n".join(lines),admin_keyboard())


def admin_keyboard():
    return {"inline_keyboard":[
        [{"text":"ðŸ“Š Stats","callback_data":"adm_stats"},{"text":"ðŸ‘¥ Users","callback_data":"adm_users"}],
        [{"text":"ðŸ’¸ Withdrawals","callback_data":"adm_wds"},{"text":"ðŸ“‹ Submissions","callback_data":"adm_subs"}],
        [{"text":"âž• Add Task","callback_data":"adm_addtask"},{"text":"ðŸ“ Manage Tasks","callback_data":"adm_tasks"}],
        [{"text":"ðŸ“£ Manage Channels","callback_data":"adm_channels"},{"text":"ðŸ›¡ Anti-Fraud","callback_data":"adm_fraud"}],
        [{"text":"âš™ï¸ Settings","callback_data":"adm_settings"}]
    ]}

async def handle_admin_callback(q,data):
    aid=int(q["from"]["id"])
    if not is_admin(aid): return await answer_callback(q["id"],"Not authorized.",True)
    if data=="adm_stats": await answer_callback(q["id"]); await admin_stats(aid); return
    if data=="adm_users": await answer_callback(q["id"]); await admin_users(aid); return
    if data=="adm_wds": await answer_callback(q["id"]); await admin_withdrawals(aid); return
    if data=="adm_subs": await answer_callback(q["id"]); await admin_submissions(aid); return
    if data=="adm_tasks": await answer_callback(q["id"]); await admin_tasks(aid); return
    if data=="adm_channels": await answer_callback(q["id"]); await admin_channels(aid); return
    if data=="adm_settings": await answer_callback(q["id"]); await admin_settings(aid); return
    if data=="adm_fraud": await answer_callback(q["id"]); await admin_fraud(aid); return
    if data=="adm_addtask": return await answer_callback(q["id"],"Use /addtask TITLE|DESCRIPTION|REWARD|URL",True)
    if data.startswith("task_delete:"):
        tid=int(data.split(":",1)[1]); conn=db()
        try:
            cur=conn.execute("UPDATE tasks SET active=0 WHERE id=?",(tid,)); conn.commit()
        finally: conn.close()
        await answer_callback(q["id"],"Task disabled." if cur.rowcount else "Task not found."); await admin_tasks(aid); return
    if data.startswith("ch_remove:"):
        cid=int(data.split(":",1)[1]); conn=db()
        try:cur=conn.execute("DELETE FROM required_channels WHERE id=?",(cid,));conn.commit()
        finally:conn.close()
        await answer_callback(q["id"],"Channel removed." if cur.rowcount else "Channel not found."); await admin_channels(aid); return
    if data.startswith("ch_toggle:"):
        cid=int(data.split(":",1)[1]); conn=db()
        try:conn.execute("UPDATE required_channels SET active=CASE active WHEN 1 THEN 0 ELSE 1 END WHERE id=?",(cid,));conn.commit()
        finally:conn.close()
        await answer_callback(q["id"],"Channel status changed."); await admin_channels(aid); return
    if data.startswith("wd_refs:"):
        wid=int(data.split(":",1)[1]); conn=db()
        try:
            w=conn.execute("SELECT user_id FROM withdrawals WHERE id=?",(wid,)).fetchone(); refs=conn.execute("SELECT user_id,username,first_name,verified,banned,referral_reward_paid,balance FROM users WHERE referred_by=? ORDER BY user_id ASC",(w["user_id"],)).fetchall() if w else []
        finally:conn.close()
        if not refs:return await answer_callback(q["id"],"No referrals found.",True)
        for start in range(0,len(refs),30):
            chunk=refs[start:start+30]; lines=[f"ðŸ‘¥ <b>Referral List {start+1}-{start+len(chunk)} / {len(refs)}</b>"]
            for r in chunk:lines.append(f"â€¢ {format_user(r)} â€” {'Verified' if r['verified'] else 'Unverified'} â€” {'BANNED' if r['banned'] else 'Active'}")
            await send_message(aid,"\n".join(lines))
        return await answer_callback(q["id"],"Referral list sent.")
    if data.startswith("wd_"):
        action,raw=data.split(":",1); wid=int(raw); conn=db()
        try:
            row=conn.execute("SELECT * FROM withdrawals WHERE id=?",(wid,)).fetchone()
            if not row:return await answer_callback(q["id"],"Withdrawal not found.",True)
            if row["status"]!="pending":return await answer_callback(q["id"],f"Already {row['status']}.",True)
            now=int(time.time())
            if action=="wd_approve": status="approved";conn.execute("UPDATE withdrawals SET status='approved',processed_at=?,processed_by=? WHERE id=? AND status='pending'",(now,aid,wid))
            elif action=="wd_reject": status="rejected and refunded";conn.execute("UPDATE withdrawals SET status='rejected',processed_at=?,processed_by=? WHERE id=? AND status='pending'",(now,aid,wid));conn.execute("UPDATE users SET balance=ROUND(balance+?,8),updated_at=? WHERE user_id=?",(row["amount"],now,row["user_id"]))
            elif action=="wd_ban": status="user banned";conn.execute("UPDATE users SET banned=1,updated_at=? WHERE user_id=?",(now,row["user_id"]))
            else:return await answer_callback(q["id"],"Unknown action.",True)
            conn.commit()
        finally:conn.close()
        await answer_callback(q["id"],f"Withdrawal {status}."); await edit_callback(q,f"ðŸ’¸ <b>Withdrawal #{wid}</b>\n\nStatus: <b>{status}</b>")
        if action in {"wd_approve","wd_reject"}:
            msg=(f"ðŸ’¸ <b>Withdrawal Update</b>\n\nAmount: <b>{row['amount']:.2f} ETB</b>\nStatus: <b>{status}</b>\n"
                 + ("âœ… Your payout has been approved. Please allow normal processing time for the transfer." if action=="wd_approve" else "â†©ï¸ Your balance has been refunded because the withdrawal was rejected."))
            await send_message(row["user_id"],msg)
        elif action=="wd_ban": await send_message(row["user_id"],"ðŸš« Your Falcon World account has been banned by an administrator.")
        return
    if data.startswith("task_"):
        action,raw=data.split(":",1); sid=int(raw); conn=db()
        try:row=conn.execute("SELECT s.*,t.title,t.reward FROM task_submissions s JOIN tasks t ON t.id=s.task_id WHERE s.id=?",(sid,)).fetchone()
        finally:conn.close()
        if not row:return await answer_callback(q["id"],"Submission not found.",True)
        if row["status"]!="pending":return await answer_callback(q["id"],f"Already {row['status']}.",True)
        conn=db();now=int(time.time())
        try:
            if action=="task_approve":conn.execute("UPDATE task_submissions SET status='approved',reviewed_at=?,reviewed_by=? WHERE id=? AND status='pending'",(now,aid,sid));conn.execute("UPDATE users SET balance=ROUND(balance+?,8),task_earnings=ROUND(task_earnings+?,8),updated_at=? WHERE user_id=?",(row["reward"],row["reward"],now,row["user_id"]));status="approved"
            elif action=="task_reject":conn.execute("UPDATE task_submissions SET status='rejected',reviewed_at=?,reviewed_by=? WHERE id=? AND status='pending'",(now,aid,sid));status="rejected"
            else:return await answer_callback(q["id"],"Unknown action.",True)
            conn.commit()
        finally:conn.close()
        await answer_callback(q["id"],f"Task {status}.");await edit_callback(q,f"ðŸ“‹ <b>Task Submission #{sid}</b>\n\nStatus: <b>{status}</b>")
        await send_message(row["user_id"],f"ðŸ“‹ <b>Task Update</b>\n\nTask: <b>{html.escape(row['title'])}</b>\nStatus: <b>{status}</b>"+(f"\nðŸ’° Reward: <b>+{row['reward']:.2f} ETB</b>" if status=="approved" else ""))


def parse_start_ref(text):
    parts=text.split(maxsplit=1)
    if len(parts)!=2:return None
    p=parts[1].strip(); return int(p[4:]) if p.startswith("ref_") and p[4:].isdigit() else None


def main_keyboard(): return {"inline_keyboard":[[{"text":"ðŸš€ Open Falcon World","web_app":{"url":MINI_APP_URL}}]]}


async def handle_message(message):
    chat=message.get("chat",{}); user=message.get("from",{}); chat_id=chat.get("id"); uid=user.get("id")
    if not chat_id or not uid:return
    username=user.get("username",""); first_name=user.get("first_name",""); text=(message.get("text") or "").strip()
    ref=parse_start_ref(text) if text.startswith("/start") else None; ensure_user(uid,username,first_name,ref)
    if is_banned(uid) and not is_admin(uid): return await send_message(chat_id,"ðŸš« Your account is currently banned.")
    if text.startswith("/start"):
        return await send_message(chat_id,"ðŸ¦… <b>WELCOME TO FALCON WORLD</b>\n\nðŸ’° Earn & Complete Tasks\nðŸŽ Daily Rewards\nðŸ‘¥ Referral Rewards\nðŸš€ New Opportunities\n\nðŸ’± USDT Exchange: Buy & Sell\nðŸ“¢ Ads & Promotions: DM @AmanM_12\n\nðŸ¦… <b>Tap the Falcon World button below to get started.</b>",main_keyboard())
    if text=="/admin" and is_admin(uid): return await admin_stats(chat_id)
    if text=="/adminpanel" and is_admin(uid): return await send_message(chat_id,"ðŸ›  <b>Falcon World Admin Panel</b>",admin_keyboard())
    if text.startswith("/checkuser ") and is_admin(uid):
        raw=text.split(maxsplit=1)[1].strip()
        if not raw.isdigit(): return await send_message(chat_id,"Usage: /checkuser USER_ID")
        return await admin_user_audit(chat_id,int(raw))
    if text.startswith("/addbalance ") and is_admin(uid):
        p=text.split();
        if len(p)!=3 or not p[1].isdigit():return await send_message(chat_id,"Usage: /addbalance USER_ID AMOUNT")
        try: amount=float(p[2])
        except:return await send_message(chat_id,"Amount must be a number.")
        if not get_user(int(p[1])):return await send_message(chat_id,"User not found.")
        add_balance(int(p[1]),amount); await send_message(int(p[1]),f"ðŸ’° Admin balance adjustment: <b>{amount:+.2f} ETB</b>"); return await send_message(chat_id,"âœ… Balance updated.")
    if text.startswith("/ban ") and is_admin(uid):
        raw=text.split(maxsplit=1)[1].strip(); conn=db()
        try:conn.execute("UPDATE users SET banned=1,updated_at=? WHERE user_id=?",(int(time.time()),int(raw)));conn.commit()
        finally:conn.close()
        return await send_message(chat_id,"ðŸš« User banned.")
    if text.startswith("/unban ") and is_admin(uid):
        raw=text.split(maxsplit=1)[1].strip(); conn=db()
        try:conn.execute("UPDATE users SET banned=0,updated_at=? WHERE user_id=?",(int(time.time()),int(raw)));conn.commit()
        finally:conn.close()
        return await send_message(chat_id,"âœ… User unbanned.")
    if text.startswith("/deltask ") and is_admin(uid):
        raw=text.split(maxsplit=1)[1].strip()
        if not raw.isdigit(): return await send_message(chat_id,"Usage: /deltask TASK_ID")
        conn=db()
        try:cur=conn.execute("UPDATE tasks SET active=0 WHERE id=?",(int(raw),));conn.commit()
        finally:conn.close()
        return await send_message(chat_id,"âœ… Task disabled." if cur.rowcount else "âŒ Task not found.")
    if text=="/fraud" and is_admin(uid):
        return await admin_fraud(chat_id)
    if text.startswith("/setminwithdraw ") and is_admin(uid):
        set_setting("min_withdraw",float(text.split(maxsplit=1)[1])); return await send_message(chat_id,"âœ… Minimum withdrawal updated.")
    if text.startswith("/setdaily ") and is_admin(uid):
        set_setting("daily_bonus",float(text.split(maxsplit=1)[1])); return await send_message(chat_id,"âœ… Daily bonus updated.")
    if text.startswith("/setref ") and is_admin(uid):
        set_setting("referral_reward",float(text.split(maxsplit=1)[1])); return await send_message(chat_id,"âœ… Referral reward updated.")
    if text=="/channels" and is_admin(uid):return await admin_channels(chat_id)
    if text.startswith("/addchannel ") and is_admin(uid):
        p=[x.strip() for x in text.split("|",2)]
        if len(p)!=3:return await send_message(chat_id,"Usage: /addchannel @username | Name | https://t.me/username")
        u,n,url=p;u=u if u.startswith("@") else "@"+u;conn=db()
        try:conn.execute("INSERT INTO required_channels(username,name,url,active,created_at) VALUES(?,?,?,?,?)",(u,n,url,1,int(time.time())));conn.commit()
        except sqlite3.IntegrityError:return await send_message(chat_id,"âŒ Channel already exists.")
        finally:conn.close()
        return await send_message(chat_id,"âœ… Channel added.")
    if text.startswith("/removechannel ") and is_admin(uid):
        u=text.split(maxsplit=1)[1].strip();u=u if u.startswith("@") else "@"+u;conn=db()
        try:cur=conn.execute("DELETE FROM required_channels WHERE username=?",(u,));conn.commit()
        finally:conn.close()
        return await send_message(chat_id,"âœ… Channel removed." if cur.rowcount else "âŒ Channel not found.")
    if text.startswith("/editchannel ") and is_admin(uid):
        p=[x.strip() for x in text.split("|",3)]
        if len(p)!=4:return await send_message(chat_id,"Usage: /editchannel @old | @new | Name | https://t.me/new")
        old,new,name,url=p;old=old if old.startswith("@") else "@"+old;new=new if new.startswith("@") else "@"+new;conn=db()
        try:cur=conn.execute("UPDATE required_channels SET username=?,name=?,url=? WHERE username=?",(new,name,url,old));conn.commit()
        finally:conn.close()
        return await send_message(chat_id,"âœ… Channel updated." if cur.rowcount else "âŒ Channel not found.")
    if text.startswith("/addtask ") and is_admin(uid):
        p=text.split("|",3)
        if len(p)!=4:return await send_message(chat_id,"Usage: /addtask TITLE|DESCRIPTION|REWARD|URL")
        title,desc,rew,url=[x.strip() for x in p]
        try:reward=float(rew)
        except:return await send_message(chat_id,"Reward must be a number.")
        conn=db()
        try:cur=conn.execute("INSERT INTO tasks(title,description,reward,url,active,created_at) VALUES(?,?,?,?,1,?)",(title,desc,reward,url,int(time.time())));conn.commit();tid=cur.lastrowid
        finally:conn.close()
        return await send_message(chat_id,f"âœ… Task #{tid} created.")
    return await send_message(chat_id,"Use /start to open Falcon World.",main_keyboard())


async def handle_callback(q):
    data=q.get("data","")
    if data.startswith(("wd_","task_","adm_")): return await handle_admin_callback(q,data)
    await answer_callback(q["id"])


async def handle_update(update):
    if "callback_query" in update:return await handle_callback(update["callback_query"])
    if update.get("message"):await handle_message(update["message"])


def validate_init_data(init_data):
    if not init_data or not BOT_TOKEN:return None
    try:
        parsed=dict(parse_qsl(init_data,keep_blank_values=True)); received=parsed.pop("hash",None)
        if not received:return None
        check="\n".join(f"{k}={parsed[k]}" for k in sorted(parsed))
        secret=hmac.new(b"WebAppData",BOT_TOKEN.encode(),hashlib.sha256).digest(); calculated=hmac.new(secret,check.encode(),hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calculated,received):return None
        auth=int(parsed.get("auth_date","0"));
        if auth<=0 or time.time()-auth>86400:return None
        u=json.loads(parsed.get("user","{}"));return u if u.get("id") else None
    except Exception:return None


async def check_channel_membership(uid,username):
    r=await telegram_request("getChatMember",{"chat_id":username,"user_id":uid})
    if not r.get("ok"):return False
    m=r.get("result",{});s=m.get("status")
    return s in {"member","administrator","creator"} or (s=="restricted" and m.get("is_member") is True)


async def check_all_channels(uid):
    channels=get_required_channels()
    async def one(c):return {**c,"joined":await check_channel_membership(uid,c["username"])}
    results=await asyncio.gather(*(one(c) for c in channels))
    count=sum(x["joined"] for x in results);return {"verified":count==len(results),"verified_count":count,"total":len(results),"channels":results}


async def require_user(request):
    user=validate_init_data(request.headers.get("X-Telegram-Init-Data",""))
    if not user:return None,JSONResponse({"error":"telegram_required"},status_code=401)
    uid=int(user["id"])
    if is_banned(uid):return None,JSONResponse({"error":"banned"},status_code=403)
    # Browser-generated device ID is only a risk signal; it is not a secure identity proof.
    device_hash=request.headers.get("X-Falcon-Device","").strip()[:128]
    score,flags=record_fingerprint(uid,client_ip(request),device_hash)
    if score>=20:
        # Fire-and-forget is avoided here; the request remains deterministic.
        await fraud_alert(uid,score,flags,"Mini App access")
    return user,None


APP_HTML=r'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no"><title>Falcon World</title><script src="https://telegram.org/js/telegram-web-app.js"></script><style>
*{box-sizing:border-box}body{margin:0;font-family:Arial,sans-serif;background:#07111f;color:#fff;min-height:100vh}button,input,textarea{font:inherit}.app{max-width:560px;margin:auto;min-height:100vh;background:linear-gradient(180deg,#0b1b30,#07111f);padding-bottom:82px}.top{padding:22px 18px 10px;text-align:center}.logo{font-size:42px}.title{font-size:25px;font-weight:800}.sub{color:#9fb1c7;font-size:13px}.card{margin:12px 14px;padding:17px;border:1px solid #1e3650;border-radius:18px;background:rgba(15,32,53,.88);box-shadow:0 8px 28px #0003}.balance{font-size:34px;font-weight:800;margin:8px 0}.muted{color:#91a4ba}.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.action{border:1px solid #294563;background:#10243a;color:#fff;border-radius:15px;padding:15px;text-align:left;min-height:88px}.action b{display:block;margin-top:7px}.btn{border:0;border-radius:13px;padding:13px 16px;background:#1687ff;color:white;font-weight:700;width:100%;margin-top:9px}.btn.secondary{background:#1a3048}.btn.danger{background:#b83232}.input{width:100%;padding:13px;border-radius:12px;border:1px solid #31506d;background:#081625;color:#fff;margin-top:8px}.nav{position:fixed;bottom:0;left:50%;transform:translateX(-50%);width:min(560px,100%);display:grid;grid-template-columns:repeat(4,1fr);background:#0b1a2c;border-top:1px solid #25415c;padding:8px 5px;z-index:10}.nav button{background:none;border:0;color:#8da3ba;padding:7px 2px;font-size:11px}.nav button.active{color:#fff}.page{display:none}.page.active{display:block}.badge{display:inline-block;padding:5px 9px;border-radius:20px;background:#173a59;color:#9fd1ff;font-size:11px}.row{display:flex;justify-content:space-between;gap:12px;align-items:center}.service{padding:12px 0;border-bottom:1px solid rgba(255,255,255,.08)}.service:last-child{border-bottom:0}.task{border:1px solid #294563;border-radius:14px;padding:13px;margin:10px 0}.ok{color:#55df91}.err{color:#ff7b7b}.center{text-align:center}.small{font-size:12px}.channel{display:flex;justify-content:space-between;gap:10px;align-items:center;padding:12px 0;border-bottom:1px solid #20384e}.channel a{color:#62b4ff;text-decoration:none}.loader{padding:30px;text-align:center;color:#9fb1c7}
</style></head><body><div class="app"><div class="top"><div class="logo">ðŸ¦…</div><div class="title">Falcon World</div><div class="sub">Earn â€¢ Grow â€¢ Withdraw</div></div>
<div id="home" class="page active"><div class="card"><span class="badge">ðŸ›¡ Verified Member</span><div class="muted">Your Balance</div><div id="balance" class="balance">0.00 ETB</div><div class="muted">â‰ˆ 0.00 USDT</div></div><div class="card"><div class="row"><b>Quick Actions</b><span class="badge">7 features</span></div><div class="grid" style="margin-top:10px"><button class="action" onclick="show('tasks')">ðŸ“‹<b>Tasks</b><span class="muted small">Complete & Earn</span></button><button class="action" onclick="show('daily')">ðŸŽ<b>Daily Bonus</b><span class="muted small">Claim Reward</span></button><button class="action" onclick="show('referral')">ðŸ‘¥<b>Referral</b><span class="muted small">Invite & Earn</span></button><button class="action" onclick="show('wallet')">ðŸ’³<b>Wallet</b><span class="muted small">Manage Funds</span></button><button class="action" onclick="show('withdraw')">ðŸ’¸<b>Withdraw</b><span class="muted small">Get Earnings</span></button><button class="action" onclick="show('support')">ðŸ†˜<b>Support</b><span class="muted small">We're Here</span></button></div></div></div>
<div id="tasks" class="page"><div class="card"><h2>ðŸ“‹ Tasks</h2><div id="tasksList" class="loader">Loadingâ€¦</div></div></div>
<div id="channels" class="page"><div class="card"><h2>ðŸ“£ Required Channels</h2><div id="channelsList" class="loader">Loadingâ€¦</div><button class="btn" onclick="verify()">âœ“ Verify Membership</button></div></div>
<div id="daily" class="page"><div class="card"><h2>ðŸŽ Daily Reward</h2><div class="balance">+<span id="dailyReward">0.50</span> ETB</div><div id="dailyStatus" class="muted">Loadingâ€¦</div><button id="dailyBtn" class="btn" onclick="claimDaily()">ðŸŽ Claim Daily Bonus</button></div></div>
<div id="referral" class="page"><div class="card"><h2>ðŸ‘¥ Invite Friends</h2><div class="muted">Invite friends and earn after they complete verification.</div><p>Invited Users: <b id="refCount">0</b></p><p>Reward / Referral: <b id="refReward">2.00 ETB</b></p><p>Referral Earnings: <b id="refEarn">0.00 ETB</b></p><input id="refLink" class="input" readonly><button class="btn" onclick="shareRef()">â†— Share Referral Link</button></div></div>
<div id="wallet" class="page"><div class="card"><h2>ðŸ’³ Wallet</h2><div class="muted">CBE: 13 digits starting 1000<br>Telebirr: 10 digits starting 09 / 07</div><select id="walletType" class="input"><option value="cbe">CBE</option><option value="telebirr">Telebirr</option></select><input id="walletNumber" class="input" placeholder="Wallet number"><button class="btn" onclick="saveWallet()">Save Wallet</button><div id="walletMsg"></div></div></div>
<div id="withdraw" class="page"><div class="card"><h2>ðŸ’¸ Withdraw</h2><p>Available: <b id="wdBalance">0.00 ETB</b></p><p>Minimum: <b id="minWd">30.00 ETB</b></p><div class="muted">Leave amount empty to withdraw your full available balance.</div><input id="wdAmount" class="input" type="number" min="0" step="0.01" placeholder="Withdrawal amount"><button class="btn" onclick="withdraw()">ðŸ’¸ Request Withdrawal</button><div id="wdMsg"></div></div></div>
<div id="history" class="page"><div class="card"><h2>â—· History</h2><div id="historyList" class="loader">Loadingâ€¦</div></div></div>
<div id="profile" class="page"><div class="card"><h2>ðŸ¦… Falcon World Member</h2><p>Telegram ID: <b id="profileId">â€”</b></p><p>Status: <b class="ok">Verified</b></p><p>Wallet: <b id="profileWallet">Not set</b></p><p>Balance: <b id="profileBalance">0.00 ETB</b></p></div></div>
<div id="support" class="page"><div class="card"><h2>ðŸ†˜ Support & Services</h2><p class="muted">Need a service or want to work with us? Contact <b>@AmanM_12</b>.</p><div class="service"><b>ðŸ“£ Channel Growth</b><br><span class="muted">Grow your Telegram channel and reach more people.</span></div><div class="service"><b>ðŸ‘¥ Group Growth</b><br><span class="muted">Promotion and growth for Telegram groups.</span></div><div class="service"><b>ðŸ“¢ Advertising & Promotion</b><br><span class="muted">Advertise your project, bot, channel, group or service.</span></div><div class="service"><b>ðŸ’± USDT Buy / Sell</b><br><span class="muted">Ask about available USDT buying or selling service.</span></div><div class="service"><b>ðŸ“º Channel Buy / Sell</b><br><span class="muted">Looking to buy or sell a Telegram channel? Contact us.</span></div><div class="service"><b>ðŸ“± Social Media Promotion</b><br><span class="muted">Promotion and digital marketing services.</span></div><button class="btn" onclick="openTG('https://t.me/AmanM_12')">ðŸ†˜ Contact @AmanM_12</button></div></div>
<div class="nav"><button id="navHome" class="active" onclick="show('home')">ðŸ¦…<br>Home</button><button id="navTasks" onclick="show('tasks')">ðŸ“‹<br>Tasks</button><button id="navHistory" onclick="show('history')">â—·<br>History</button><button id="navProfile" onclick="show('profile')">â—<br>Profile</button></div></div>
<script>
const tg=window.Telegram?.WebApp; if(tg){tg.ready();tg.expand()} let deviceId=localStorage.getItem('falcon_device_id'); if(!deviceId){deviceId=crypto.randomUUID?crypto.randomUUID():(Date.now()+'-'+Math.random());localStorage.setItem('falcon_device_id',deviceId)} const headers={'X-Telegram-Init-Data':tg?.initData||'','X-Falcon-Device':deviceId};
async function api(url,opt={}){opt.headers={...(opt.headers||{}),...headers,'Content-Type':'application/json'};const r=await fetch(url,opt);let d={};try{d=await r.json()}catch{} if(!r.ok)throw new Error(d.error||'Request failed');return d}
function show(id){document.querySelectorAll('.page').forEach(x=>x.classList.remove('active'));document.getElementById(id).classList.add('active');document.querySelectorAll('.nav button').forEach(x=>x.classList.remove('active'));({home:'navHome',tasks:'navTasks',history:'navHistory',profile:'navProfile'})[id]&&document.getElementById(({home:'navHome',tasks:'navTasks',history:'navHistory',profile:'navProfile'})[id]).classList.add('active');if(id==='tasks')loadTasks();if(id==='channels')loadChannels();if(id==='history')loadHistory();if(id==='daily')loadDaily();if(id==='referral')loadReferral()}
function money(x){return Number(x||0).toFixed(2)}
async function loadMe(){try{const d=await api('/api/me');document.getElementById('balance').textContent=money(d.balance)+' ETB';document.getElementById('wdBalance').textContent=money(d.balance)+' ETB';document.getElementById('minWd').textContent=money(d.min_withdraw)+' ETB';document.getElementById('profileId').textContent=d.user_id;document.getElementById('profileBalance').textContent=money(d.balance)+' ETB';document.getElementById('profileWallet').textContent=d.wallet_type&&d.wallet_number?d.wallet_type+': '+d.wallet_number:'Not set'}catch(e){document.getElementById('balance').textContent='Telegram only'}}
async function loadTasks(){const box=document.getElementById('tasksList');try{const d=await api('/api/tasks');if(!d.tasks.length){box.innerHTML='<div class="muted">No active tasks right now.</div>';return}box.innerHTML=d.tasks.map(t=>`<div class="task"><b>#${t.id} ${esc(t.title)}</b><p class="muted">${esc(t.description||'')}</p><b>ðŸ’° ${money(t.reward)} ETB</b><p class="small">Status: ${esc(t.submission_status||'not submitted')}</p>${t.url?`<button class="btn secondary" onclick="openTG('${esc(t.url)}')">Open Task</button>`:''}${t.submission_status!=='approved'?`<textarea id="proof${t.id}" class="input" placeholder="Write your proof details"></textarea><input id="photo${t.id}" class="input" type="file" accept="image/*"><button class="btn" onclick="submitTask(${t.id})">Submit Proof</button>`:''}</div>`).join('')}catch(e){box.innerHTML='<div class="err">'+esc(e.message)+'</div>'}}
async function submitTask(id){const proof=document.getElementById('proof'+id).value;const photo=document.getElementById('photo'+id)?.files?.[0];try{if(photo){if(photo.size>5*1024*1024)throw new Error('Image must be 5 MB or smaller.');const reader=new FileReader();const data=await new Promise((resolve,reject)=>{reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsDataURL(photo)});await api('/api/tasks/'+id+'/submit-photo',{method:'POST',body:JSON.stringify({photo_data:data,note:proof,filename:photo.name})})}else{await api('/api/tasks/'+id+'/submit',{method:'POST',body:JSON.stringify({proof})})}alert('Proof submitted. Admin will review it.');loadTasks()}catch(e){alert(e.message)}}
async function loadChannels(){const b=document.getElementById('channelsList');try{const d=await api('/api/verify');b.innerHTML=d.channels.map(c=>`<div class="channel"><div>${c.joined?'âœ…':'âŒ'} <b>${esc(c.name)}</b><br><span class="small muted">${esc(c.username)}</span></div><a href="${esc(c.url)}">Join</a></div>`).join('')}catch(e){b.innerHTML='<div class="err">'+esc(e.message)+'</div>'}}
async function verify(){try{const c=await api('/api/captcha');const ans=prompt(c.question);if(ans===null)return;await api('/api/captcha/verify',{method:'POST',body:JSON.stringify({token:c.token,answer:ans})});const d=await api('/api/verify',{method:'POST'});if(d.verified){alert('âœ… Verification successful!');loadMe();show('home')}else{alert(`Joined ${d.verified_count}/${d.total}. Join all channels first.`);loadChannels()}}catch(e){alert(e.message)}}
async function loadDaily(){try{const d=await api('/api/daily-status');document.getElementById('dailyReward').textContent=money(d.reward);document.getElementById('dailyStatus').textContent=d.can_claim?'Available today':'Already claimed today';document.getElementById('dailyBtn').disabled=!d.can_claim}catch(e){document.getElementById('dailyStatus').textContent=e.message}}
async function claimDaily(){try{const d=await api('/api/daily-bonus',{method:'POST'});alert('ðŸŽ +'+money(d.reward)+' ETB');loadMe();loadDaily()}catch(e){alert(e.message)}}
async function loadReferral(){try{const d=await api('/api/referral');document.getElementById('refLink').value=d.link;document.getElementById('refCount').textContent=d.count;document.getElementById('refReward').textContent=money(d.reward)+' ETB';document.getElementById('refEarn').textContent=money(d.earnings)+' ETB'}catch(e){}}
async function shareRef(){const l=document.getElementById('refLink').value;if(tg?.openTelegramLink)tg.openTelegramLink('https://t.me/share/url?url='+encodeURIComponent(l)+'&text='+encodeURIComponent('Join Falcon World ðŸ¦…'));else navigator.clipboard?.writeText(l)}
async function saveWallet(){try{const d=await api('/api/wallet',{method:'POST',body:JSON.stringify({wallet_type:document.getElementById('walletType').value,wallet_number:document.getElementById('walletNumber').value})});document.getElementById('walletMsg').innerHTML='<p class="ok">'+esc(d.message)+'</p>';loadMe()}catch(e){document.getElementById('walletMsg').innerHTML='<p class="err">'+esc(e.message)+'</p>'}}
async function withdraw(){try{const v=document.getElementById('wdAmount').value;const d=await api('/api/withdraw',{method:'POST',body:JSON.stringify({amount:v||null})});document.getElementById('wdMsg').innerHTML='<p class="ok">Withdrawal #'+d.withdrawal_id+' submitted.</p>';loadMe()}catch(e){document.getElementById('wdMsg').innerHTML='<p class="err">'+esc(e.message)+'</p>'}}
async function loadHistory(){const b=document.getElementById('historyList');try{const d=await api('/api/history');b.innerHTML=d.items.length?d.items.map(x=>`<div class="task"><div class="row"><b>${money(x.amount)} ETB</b><span>${esc(x.status)}</span></div><div class="muted small">${esc(x.wallet_type)} â€¢ ${esc(x.wallet_mask)}<br>${esc(x.created)}</div></div>`).join(''):'<div class="muted">No withdrawal history.</div>'}catch(e){b.innerHTML='<div class="err">'+esc(e.message)+'</div>'}}
function openTG(u){if(tg?.openTelegramLink&&u.includes('t.me'))tg.openTelegramLink(u);else window.open(u,'_blank')}
function esc(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}
async function gate(){try{const d=await api('/api/verify');if(!d.verified){show('channels');loadChannels()}}catch(e){}}
loadMe();gate();
</script></body></html>'''

app=FastAPI(title="Falcon World")

@app.get("/")
async def home(): return {"status":"online","app":"Falcon World"}

@app.get("/health")
async def health(): return {"status":"ok","app":"falcon-world"}

@app.get("/falcon-bg.webp")
async def background():
    if os.path.exists(FALCON_BG_PATH): return FileResponse(FALCON_BG_PATH,media_type="image/webp",headers={"Cache-Control":"public,max-age=86400"})
    return JSONResponse({"error":"background_not_found"},status_code=404)

@app.get("/app",response_class=HTMLResponse)
async def mini_app(): return HTMLResponse(APP_HTML)


def new_captcha(uid):
    a,b=random.randint(11,39),random.randint(3,18);token=secrets.token_urlsafe(18);CAPTCHA_SESSIONS[uid]={"token":token,"answer":a+b,"expires":time.time()+300};return {"token":token,"question":f"What is {a} + {b}?"}

@app.get("/api/captcha")
async def captcha(request:Request):
    u,e=await require_user(request)
    if e:return e
    return new_captcha(int(u["id"]))

@app.post("/api/captcha/verify")
async def captcha_verify(request:Request):
    u,e=await require_user(request)
    if e:return e
    uid=int(u["id"]);s=CAPTCHA_SESSIONS.get(uid)
    if not s or s["expires"]<time.time():return JSONResponse({"error":"CAPTCHA expired. Please request a new one."},status_code=400)
    try:b=await request.json();
    except Exception:b={}
    if str(b.get("token",""))!=s["token"]:return JSONResponse({"error":"Invalid verification session."},status_code=400)
    try:ans=int(str(b.get("answer","")).strip())
    except:return JSONResponse({"error":"Please enter a valid number."},status_code=400)
    if ans!=s["answer"]:CAPTCHA_SESSIONS.pop(uid,None);return JSONResponse({"error":"Incorrect answer. Please try again."},status_code=400)
    s["human"]=True;s["expires"]=time.time()+600;return {"ok":True}

@app.api_route("/api/verify",methods=["GET","POST"])
async def verify_user(request:Request):
    u,e=await require_user(request)
    if e:return e
    uid=int(u["id"])
    if request.method=="POST":
        s=CAPTCHA_SESSIONS.get(uid)
        if not s or not s.get("human") or s.get("expires",0)<time.time():return JSONResponse({"error":"Complete human verification first."},status_code=403)
    v=await check_all_channels(uid)
    if v["verified"]:
        ensure_user(uid,u.get("username",""),u.get("first_name",""));conn=db()
        try:conn.execute("UPDATE users SET verified=1,updated_at=? WHERE user_id=?",(int(time.time()),uid));conn.commit()
        finally:conn.close()
        reward_referrer_after_verification(uid)
    return v

@app.get("/api/me")
async def api_me(request:Request):
    u,e=await require_user(request)
    if e:return e
    uid=int(u["id"]);ensure_user(uid,u.get("username",""),u.get("first_name",""));row=get_user(uid);conn=db()
    try:
        tw=conn.execute("SELECT COALESCE(SUM(amount),0) s FROM withdrawals WHERE user_id=? AND status='approved'",(uid,)).fetchone()["s"];pw=conn.execute("SELECT COALESCE(SUM(amount),0) s FROM withdrawals WHERE user_id=? AND status='pending'",(uid,)).fetchone()["s"]
    finally:conn.close()
    re_=float(row["referral_earnings"] or 0);de=float(row["daily_bonus_earnings"] or 0);te=float(row["task_earnings"] or 0)
    return {"user_id":row["user_id"],"username":row["username"],"first_name":row["first_name"],"balance":float(row["balance"]),"verified":bool(row["verified"]),"wallet_type":row["wallet_type"],"wallet_number":row["wallet_number"],"wallet_suspicious":bool(row["wallet_suspicious"]),"referral_earnings":re_,"daily_bonus_earnings":de,"task_earnings":te,"total_earned":re_+de+te,"total_withdrawn":float(tw or 0),"pending_withdrawal":float(pw or 0),"min_withdraw":float(get_setting("min_withdraw",DEFAULT_MIN_WITHDRAW))}

@app.get("/api/history")
async def history(request:Request):
    u,e=await require_user(request)
    if e:return e
    conn=db()
    try:rows=conn.execute("SELECT amount,wallet_type,wallet_number,status,created_at FROM withdrawals WHERE user_id=? ORDER BY id DESC LIMIT 30",(int(u["id"]),)).fetchall()
    finally:conn.close()
    items=[]
    for r in rows:
        n=r["wallet_number"] or "";masked=n[:4]+"*"*max(0,len(n)-6)+n[-2:] if len(n)>6 else n
        items.append({"amount":float(r["amount"]),"wallet_type":r["wallet_type"],"wallet_mask":masked,"status":r["status"].title(),"created":time.strftime("%Y-%m-%d %H:%M",time.localtime(r["created_at"]))})
    return {"items":items}

@app.get("/api/daily-status")
async def daily_status(request:Request):
    u,e=await require_user(request)
    if e:return e
    row=get_user(int(u["id"]));today=local_date();last=int(row["daily_last_claim"] or 0);can=not last or local_date(last)!=today
    return {"today":str(today),"can_claim":can,"reward":float(get_setting("daily_bonus",DEFAULT_DAILY_BONUS)),"next_date":str(today+timedelta(days=1)) if not can else str(today)}

@app.post("/api/daily-bonus")
async def daily_bonus(request:Request):
    u,e=await require_user(request)
    if e:return e
    ok,r=claim_daily_bonus(int(u["id"]))
    if not ok:return JSONResponse({"error":"Daily bonus already claimed for today." if r.get("error")=="already_claimed" else ("Please verify all required channels first." if r.get("error")=="not_verified" else r.get("error","Could not claim bonus."))},status_code=429 if r.get("error")=="already_claimed" else 400)
    return {"reward":r["reward"],"balance":r["balance"]}

@app.get("/api/referral")
async def referral(request:Request):
    u,e=await require_user(request)
    if e:return e
    uid=int(u["id"]);row=get_user(uid);return {"link":f"https://t.me/{BOT_USERNAME}?start=ref_{uid}","count":get_referral_count(uid),"reward":get_setting("referral_reward",DEFAULT_REFERRAL_REWARD),"earnings":float(row["referral_earnings"] or 0)}

@app.post("/api/wallet")
async def wallet(request:Request):
    u,e=await require_user(request)
    if e:return e
    try:b=await request.json()
    except:b={}
    ok,msg,susp=save_wallet(int(u["id"]),str(b.get("wallet_type","")),str(b.get("wallet_number","")))
    if not ok:return JSONResponse({"error":msg},status_code=400)
    if susp:await send_admin_message(f"âš ï¸ <b>Duplicate Wallet Alert</b>\n\nUser ID: <code>{u['id']}</code>\nWallet: <b>{html.escape(str(b.get('wallet_type')))}</b>\nNumber: <code>{html.escape(str(b.get('wallet_number')))}</code>")
    return {"ok":True,"message":msg,"suspicious":susp}

@app.get("/api/tasks")
async def tasks(request:Request):
    u,e=await require_user(request)
    if e:return e
    return {"tasks":[{"id":r["id"],"title":r["title"],"description":r["description"],"reward":float(r["reward"]),"url":r["url"],"submission_status":r["submission_status"]} for r in get_active_tasks(int(u["id"]))]}

@app.post("/api/tasks/{task_id}/submit")
async def task_submit(task_id:int,request:Request):
    u,e=await require_user(request)
    if e:return e
    try:b=await request.json()
    except:b={}
    ok,r=submit_task(int(u["id"]),task_id,str(b.get("proof","")))
    if not ok:return JSONResponse({"error":r},status_code=400)
    await notify_task_submission(r["submission_id"]);return {"ok":True,"submission_id":r["submission_id"]}

@app.post("/api/tasks/{task_id}/submit-photo")
async def task_submit_photo(task_id:int, request:Request):
    u,e=await require_user(request)
    if e:return e
    try: b=await request.json()
    except Exception: b={}
    raw=str(b.get("photo_data", ""))
    if not raw.startswith("data:image/") or "," not in raw:
        return JSONResponse({"error":"Please upload an image proof."},status_code=400)
    header,encoded=raw.split(",",1)
    if len(encoded)>7*1024*1024:
        return JSONResponse({"error":"Image must be 5 MB or smaller."},status_code=400)
    try: data=base64.b64decode(encoded,validate=True)
    except Exception:return JSONResponse({"error":"Invalid image data."},status_code=400)
    if len(data)>5*1024*1024:return JSONResponse({"error":"Image must be 5 MB or smaller."},status_code=400)
    note=str(b.get("note", "")).strip()[:500]
    filename=str(b.get("filename", "proof.jpg"))[:120]
    proof=f"[PHOTO PROOF] {filename}\n{note}"
    ok,r=submit_task(int(u["id"]),task_id,proof)
    if not ok:return JSONResponse({"error":r},status_code=400)
    await notify_task_photo_submission(r["submission_id"],data,filename,note)
    return {"ok":True,"submission_id":r["submission_id"]}

@app.post("/api/withdraw")
async def withdraw(request:Request):
    u,e=await require_user(request)
    if e:return e
    try:b=await request.json()
    except:b={}
    ok,r=create_withdrawal(int(u["id"]),b.get("amount"))
    if not ok:return JSONResponse({"error":r},status_code=400)
    await notify_withdrawal(r["withdrawal_id"]);return {"ok":True,**r}

@app.post("/webhook")
async def webhook(request:Request):
    if WEBHOOK_SECRET and not hmac.compare_digest(request.headers.get("X-Telegram-Bot-Api-Secret-Token",""),WEBHOOK_SECRET):return JSONResponse({"ok":False},status_code=403)
    try:update=await request.json()
    except:return {"ok":True}
    try:await handle_update(update)
    except Exception as ex:print("Webhook error:",repr(ex))
    return {"ok":True}

@app.on_event("startup")
async def startup():
    configure_bot();init_db()
    if not BOT_TOKEN: print("ERROR: BOT_TOKEN is missing.");return
    await telegram_request("setMyCommands",{"commands":[{"command":"start","description":"Open Falcon World"},{"command":"admin","description":"Admin dashboard"},{"command":"adminpanel","description":"Open admin panel"}]})
    await telegram_request("setChatMenuButton",{"menu_button":{"type":"web_app","text":"ðŸ¦… Open Falcon World","web_app":{"url":MINI_APP_URL}}})
    webhook_data={"url":WEBHOOK_URL,"allowed_updates":["message","callback_query"]}
    if WEBHOOK_SECRET:webhook_data["secret_token"]=WEBHOOK_SECRET
    print("Webhook setup:",await telegram_request("setWebhook",webhook_data))
