import os
import json
import hmac
import hashlib
import time
import asyncio
from urllib.parse import parse_qsl

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse


# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = os.getenv("ADMIN_ID", "").strip()

BOT_USERNAME = "FalconWorld_Bot"

WEBHOOK_URL = "https://falcon-world.onrender.com/webhook"
MINI_APP_URL = "https://falcon-world.onrender.com/app"

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"


# =========================================================
# REQUIRED CHANNELS
# =========================================================

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


# =========================================================
# FASTAPI APP
# =========================================================

app = FastAPI()


# =========================================================
# TELEGRAM API HELPER
# =========================================================

async def telegram_request(method: str, data: dict | None = None):
    if not BOT_TOKEN:
        return {"ok": False, "description": "BOT_TOKEN is missing"}

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(f"{TELEGRAM_API}/{method}", json=data or {})
            return response.json()
    except Exception as e:
        return {"ok": False, "description": str(e)}


async def set_menu_button():
    return await telegram_request(
        "setChatMenuButton",
        {
            "menu_button": {
                "type": "web_app",
                "text": "🚀 Open Falcon",
                "web_app": {"url": MINI_APP_URL}
            }
        }
    )


async def send_message(chat_id: int, text: str):
    return await telegram_request(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
    )


# =========================================================
# INIT DATA VALIDATION
# =========================================================

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
            b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256
        ).digest()

        calculated_hash = hmac.new(
            secret_key, data_check_string.encode(), hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(calculated_hash, received_hash):
            return None

        auth_date = int(parsed.get("auth_date", "0"))
        if auth_date <= 0 or (time.time() - auth_date > 86400):
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


# =========================================================
# CHANNEL CHECKING LOGIC
# =========================================================

async def check_channel_membership(user_id: int, channel_username: str):
    result = await telegram_request(
        "getChatMember",
        {"chat_id": channel_username, "user_id": user_id}
    )

    if not result.get("ok"):
        return False

    member = result.get("result", {})
    status = member.get("status")
    return status in {"member", "administrator", "creator"}


async def check_all_channels(user_id: int):
    async def check(channel):
        joined = await check_channel_membership(user_id, channel["username"])
        return {**channel, "joined": joined}

    results = await asyncio.gather(*(check(ch) for ch in REQUIRED_CHANNELS))
    verified_count = sum(1 for ch in results if ch["joined"])
    verified = (verified_count == len(REQUIRED_CHANNELS))

    return {
        "verified": verified,
        "verified_count": verified_count,
        "total": len(REQUIRED_CHANNELS),
        "channels": results,
    }


# =========================================================
# ENDPOINTS
# =========================================================

@app.get("/")
async def home():
    return {"status": "online", "app": "Falcon World"}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/app", response_class=HTMLResponse)
async def mini_app():
    html = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Falcon World</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>

<style>
* {
    box-sizing: border-box;
    -webkit-tap-highlight-color: transparent;
}

html, body {
    margin: 0;
    padding: 0;
    width: 100%;
    min-height: 100%;
    background: #030712;
    color: #ffffff;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    overflow-x: hidden;
}

/* Background Effects */
.app-bg {
    position: fixed;
    inset: 0;
    z-index: -2;
    background: 
        radial-gradient(circle at 50% 0%, rgba(37, 99, 235, 0.35), transparent 50%),
        radial-gradient(circle at 100% 100%, rgba(14, 165, 233, 0.15), transparent 45%),
        #030712;
}

.glow {
    position: fixed;
    width: 300px;
    height: 300px;
    border-radius: 50%;
    background: rgba(59, 130, 246, 0.15);
    filter: blur(80px);
    top: -100px;
    left: 50%;
    transform: translateX(-50%);
    z-index: -1;
}

/* Loading Screen */
#loadingScreen {
    position: fixed;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    background: #030712;
    z-index: 9999;
    transition: opacity 0.4s ease, visibility 0.4s ease;
}

#loadingScreen.hide {
    opacity: 0;
    visibility: hidden;
}

.falcon-loader {
    width: 100px;
    height: 100px;
    border-radius: 28px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 50px;
    background: linear-gradient(145deg, rgba(59,130,246,0.3), rgba(15,23,42,0.9));
    border: 1px solid rgba(148,163,184,0.3);
    box-shadow: 0 0 35px rgba(37,99,235,0.4);
    animation: pulse 1.5s ease-in-out infinite;
}

.loading-title {
    margin-top: 20px;
    font-size: 22px;
    font-weight: 800;
    letter-spacing: 2px;
}

/* App Layout */
#appContent {
    display: none;
    padding: 20px 16px 30px;
}

#appContent.show {
    display: block;
}

.brand {
    text-align: center;
    margin-bottom: 20px;
}

.brand-icon {
    width: 60px;
    height: 60px;
    margin: 0 auto 10px;
    border-radius: 20px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 30px;
    background: linear-gradient(135deg, #2563eb, #0284c7);
    box-shadow: 0 8px 25px rgba(37,99,235,0.3);
}

.brand-title {
    font-size: 24px;
    font-weight: 900;
    letter-spacing: 1.5px;
}

.brand-subtitle {
    color: #94a3b8;
    font-size: 13px;
    margin-top: 4px;
}

/* Cards & Components */
.verify-card {
    padding: 20px;
    border-radius: 20px;
    background: rgba(15, 23, 42, 0.75);
    border: 1px solid rgba(255, 255, 255, 0.08);
    backdrop-filter: blur(16px);
    box-shadow: 0 10px 30px rgba(0,0,0,0.3);
}

.verify-title {
    font-size: 18px;
    font-weight: 800;
    display: flex;
    align-items: center;
    gap: 8px;
}

.progress-row {
    display: flex;
    justify-content: space-between;
    margin-top: 15px;
    font-size: 13px;
    color: #94a3b8;
}

.progress-bar {
    width: 100%;
    height: 8px;
    margin-top: 8px;
    border-radius: 10px;
    background: rgba(255, 255, 255, 0.08);
    overflow: hidden;
}

.progress-fill {
    width: 0%;
    height: 100%;
    background: linear-gradient(90deg, #2563eb, #38bdf8);
    transition: width 0.4s ease;
}

/* Channel List */
.channel-list {
    margin-top: 16px;
    display: flex;
    flex-direction: column;
    gap: 10px;
}

.channel-card {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 14px;
    border-radius: 16px;
    background: rgba(15, 23, 42, 0.6);
    border: 1px solid rgba(255, 255, 255, 0.05);
}

.channel-info {
    display: flex;
    align-items: center;
    gap: 12px;
}

.channel-icon {
    width: 40px;
    height: 40px;
    border-radius: 12px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 18px;
    background: rgba(37, 99, 235, 0.15);
    border: 1px solid rgba(59, 130, 246, 0.2);
}

.channel-name {
    font-size: 14px;
    font-weight: 700;
}

.channel-username {
    font-size: 12px;
    color: #64748b;
}

.channel-button {
    border: none;
    padding: 8px 16px;
    border-radius: 10px;
    background: #2563eb;
    color: white;
    font-size: 13px;
    font-weight: 700;
    cursor: pointer;
    transition: all 0.2s ease;
}

.channel-button.joined {
    background: rgba(34, 197, 94, 0.15);
    color: #4ade80;
    border: 1px solid rgba(74, 222, 128, 0.3);
    cursor: default;
}

.check-button {
    width: 100%;
    margin-top: 20px;
    padding: 15px;
    border: none;
    border-radius: 16px;
    background: linear-gradient(135deg, #2563eb, #0284c7);
    color: white;
    font-size: 15px;
    font-weight: 800;
    cursor: pointer;
    box-shadow: 0 8px 25px rgba(37, 99, 235, 0.3);
}

.check-button:disabled {
    opacity: 0.6;
}

/* Dashboard View */
.dashboard {
    display: none;
    text-align: center;
    padding: 20px 0;
}

.dashboard.show {
    display: block;
}

.dash-card {
    background: rgba(15, 23, 42, 0.8);
    border: 1px solid rgba(255, 255, 255, 0.1);
    border-radius: 20px;
    padding: 30px 20px;
    margin-top: 20px;
}

@keyframes pulse {
    0%, 100% { transform: scale(1); }
    50% { transform: scale(1.05); }
}
</style>
</head>
<body>

<div class="app-bg"></div>
<div class="glow"></div>

<!-- LOADING SCREEN -->
<div id="loadingScreen">
    <div class="falcon-loader">🦅</div>
    <div class="loading-title">FALCON WORLD</div>
</div>

<!-- MAIN CONTENT -->
<div id="appContent">

    <div class="brand">
        <div class="brand-icon">🦅</div>
        <div class="brand-title">FALCON WORLD</div>
        <div class="brand-subtitle">Earn • Refer • Grow</div>
    </div>

    <!-- VERIFICATION SECTION -->
    <div id="verificationArea">
        <div class="verify-card">
            <div class="verify-title">🔐 REQUIRED CHANNELS</div>
            <div style="font-size: 13px; color: #94a3b8; margin-top: 4px;">
                Join all required channels to access the bot main menu.
            </div>

            <div class="progress-row">
                <span>Progress</span>
                <span id="progressCount" style="color: #60a5fa; font-weight: 800;">0/6</span>
            </div>
            <div class="progress-bar">
                <div id="progressFill" class="progress-fill"></div>
            </div>
        </div>

        <div id="channelList" class="channel-list"></div>

        <button id="checkButton" class="check-button" onclick="checkMembership(true)">
            🔄 Check Verification
        </button>
    </div>

    <!-- MAIN DASHBOARD (HIDDEN UNTIL VERIFIED) -->
    <div id="dashboard" class="dashboard">
        <div style="font-size: 60px;">🎉</div>
        <h2 style="font-size: 26px; font-weight: 900; margin-top: 10px;">WELCOME ABOARD!</h2>
        <p style="color: #94a3b8; font-size: 14px;">Your verification was successful.</p>

        <div class="dash-card">
            <h3 style="margin: 0; color: #60a5fa;">🚀 Falcon Earning Dashboard</h3>
            <p style="color: #64748b; font-size: 13px; margin-top: 10px;">
                You now have full access to Falcon World tasks, daily rewards, and referrals!
            </p>
        </div>
    </div>

</div>

<script>
const tg = window.Telegram.WebApp;
tg.ready();
tg.expand();

let initData = tg.initData || "";

function openChannel(url) {
    try {
        if (tg && typeof tg.openTelegramLink === "function") {
            tg.openTelegramLink(url);
        } else {
            window.open(url, "_blank");
        }
    } catch (e) {
        window.open(url, "_blank");
    }
}

async function checkMembership(userClicked = false) {
    const btn = document.getElementById("checkButton");
    if (userClicked) {
        btn.disabled = true;
        btn.innerText = "Checking...";
    }

    try {
        const res = await fetch("/api/verify", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-Telegram-Init-Data": initData
            },
            body: JSON.stringify({})
        });

        const data = await res.json();

        if (res.ok) {
            renderChannels(data.channels || []);
            updateProgress(data.verified_count, data.total);

            if (data.verified) {
                showDashboard();
            }
        }
    } catch (e) {
        console.error("Verification error", e);
    } finally {
        if (userClicked) {
            btn.disabled = false;
            btn.innerText = "🔄 Check Verification";
        }
    }
}

function renderChannels(channels) {
    const container = document.getElementById("channelList");
    container.innerHTML = "";

    channels.forEach(ch => {
        const card = document.createElement("div");
        card.className = "channel-card";

        const isJoined = ch.joined;
        const btnText = isJoined ? "Done ✓" : "Join";
        const btnClass = isJoined ? "channel-button joined" : "channel-button";
        const btnAction = isJoined ? "" : `onclick="openChannel('${ch.url}')"`;

        card.innerHTML = `
            <div class="channel-info">
                <div class="channel-icon">${isJoined ? "✓" : "📢"}</div>
                <div>
                    <div class="channel-name">${escapeHtml(ch.name)}</div>
                    <div class="channel-username">${escapeHtml(ch.username)}</div>
                </div>
            </div>
            <button class="${btnClass}" ${btnAction}>${btnText}</button>
        `;
        container.appendChild(card);
    });
}

function updateProgress(count, total) {
    document.getElementById("progressCount").innerText = `${count}/${total}`;
    const pct = total > 0 ? (count / total) * 100 : 0;
    document.getElementById("progressFill").style.width = `${pct}%`;
}

function showDashboard() {
    document.getElementById("verificationArea").style.display = "none";
    document.getElementById("dashboard").classList.add("show");
}

function escapeHtml(str) {
    return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// Auto-check when returning to web app
document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
        checkMembership(false);
    }
});

window.addEventListener("focus", () => {
    checkMembership(false);
});

// App Start
setTimeout(() => {
    document.getElementById("loadingScreen").classList.add("hide");
    document.getElementById("appContent").classList.add("show");
    checkMembership(false);
}, 1500);

</script>
</body>
</html>
"""
    return HTMLResponse(content=html)


@app.post("/api/verify")
async def verify_user(request: Request):
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    user = validate_init_data(init_data)

    if not user:
        return JSONResponse({"error": "telegram_required"}, status_code=401)

    user_id = int(user["id"])
    verification = await check_all_channels(user_id)
    return JSONResponse(verification)


@app.post("/webhook")
async def webhook(request: Request):
    try:
        update = await request.json()
    except Exception:
        return {"ok": True}

    message = update.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text = message.get("text", "")

    if not chat_id:
        return {"ok": True}

    if text.startswith("/start"):
        welcome_message = """
🦅 *WELCOME TO FALCON WORLD*

💰 *Earn & Complete Tasks*
🎁 *Daily Rewards*
👥 *Referral Rewards*
🚀 *New Opportunities*

🚀 Open Falcon World using the button below to complete verification and enter!
"""
        await send_message(chat_id, welcome_message)

    return {"ok": True}


@app.on_event("startup")
async def startup():
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN is missing.")
        return

    await telegram_request("setWebhook", {"url": WEBHOOK_URL, "allowed_updates": ["message"]})
    await set_menu_button()
