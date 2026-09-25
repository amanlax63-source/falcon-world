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
# FASTAPI
# =========================================================

app = FastAPI()


# =========================================================
# TELEGRAM API
# =========================================================

async def telegram_request(
    method: str,
    data: dict | None = None
):
    if not BOT_TOKEN:
        return {
            "ok": False,
            "description": "BOT_TOKEN is missing"
        }

    try:
        async with httpx.AsyncClient(
            timeout=20
        ) as client:

            response = await client.post(
                f"{TELEGRAM_API}/{method}",
                json=data or {}
            )

            return response.json()

    except Exception as e:
        return {
            "ok": False,
            "description": str(e)
        }


# =========================================================
# MENU BUTTON
# =========================================================

async def set_menu_button():

    return await telegram_request(
        "setChatMenuButton",
        {
            "menu_button": {
                "type": "web_app",
                "text": "🚀 Open Falcon",
                "web_app": {
                    "url": MINI_APP_URL
                }
            }
        }
    )


# =========================================================
# SEND MESSAGE
# =========================================================

async def send_message(
    chat_id: int,
    text: str
):

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
# TELEGRAM MINI APP INIT DATA VALIDATION
# =========================================================

def validate_init_data(init_data: str):

    if not init_data or not BOT_TOKEN:
        return None

    try:

        parsed = dict(
            parse_qsl(
                init_data,
                keep_blank_values=True
            )
        )

        received_hash = parsed.pop(
            "hash",
            None
        )

        if not received_hash:
            return None

        data_check_string = "\n".join(
            f"{key}={parsed[key]}"
            for key in sorted(parsed.keys())
        )

        secret_key = hmac.new(
            b"WebAppData",
            BOT_TOKEN.encode(),
            hashlib.sha256
        ).digest()

        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(
            calculated_hash,
            received_hash
        ):
            return None

        auth_date = int(
            parsed.get(
                "auth_date",
                "0"
            )
        )

        if auth_date <= 0:
            return None

        # Reject data older than 24 hours.
        if time.time() - auth_date > 86400:
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
# CHECK ONE CHANNEL
# =========================================================

async def check_channel_membership(
    user_id: int,
    channel_username: str
):

    result = await telegram_request(
        "getChatMember",
        {
            "chat_id": channel_username,
            "user_id": user_id,
        }
    )

    if not result.get("ok"):
        return False

    member = result.get(
        "result",
        {}
    )

    status = member.get(
        "status"
    )

    return status in {
        "member",
        "administrator",
        "creator",
    }


# =========================================================
# CHECK ALL CHANNELS
# =========================================================

async def check_all_channels(
    user_id: int
):

    async def check(channel):

        joined = await check_channel_membership(
            user_id,
            channel["username"]
        )

        return {
            **channel,
            "joined": joined,
        }

    results = await asyncio.gather(
        *(
            check(channel)
            for channel in REQUIRED_CHANNELS
        )
    )

    verified_count = sum(
        1
        for channel in results
        if channel["joined"]
    )

    verified = (
        verified_count ==
        len(REQUIRED_CHANNELS)
    )

    return {
        "verified": verified,
        "verified_count": verified_count,
        "total": len(REQUIRED_CHANNELS),
        "channels": results,
    }


# =========================================================
# HOME
# =========================================================

@app.get("/")
async def home():

    return {
        "status": "online",
        "app": "Falcon World"
    }


# =========================================================
# HEALTH
# =========================================================

@app.get("/health")
async def health():

    return {
        "status": "ok"
    }


# =========================================================
# MINI APP
# =========================================================

@app.get(
    "/app",
    response_class=HTMLResponse
)
async def mini_app():

    html = r"""
<!DOCTYPE html>

<html lang="en">

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="width=device-width,
    initial-scale=1.0,
    maximum-scale=1.0,
    user-scalable=no"
>

<title>Falcon World</title>

<script src="https://telegram.org/js/telegram-web-app.js"></script>


<style>

/* =====================================================
   GLOBAL
===================================================== */

* {
    box-sizing: border-box;
    -webkit-tap-highlight-color: transparent;
}

html,
body {
    margin: 0;
    padding: 0;
    width: 100%;
    min-height: 100%;

    background: #050914;
    color: #ffffff;

    font-family:
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        Roboto,
        Arial,
        sans-serif;
}

body {
    overflow-x: hidden;
}


/* =====================================================
   BACKGROUND
===================================================== */

.app-bg {
    position: fixed;
    inset: 0;

    z-index: -2;

    background:
        radial-gradient(
            circle at 50% 0%,
            rgba(37, 99, 235, 0.28),
            transparent 42%
        ),
        radial-gradient(
            circle at 100% 100%,
            rgba(14, 165, 233, 0.12),
            transparent 40%
        ),
        #050914;
}

.glow {
    position: fixed;

    width: 280px;
    height: 280px;

    border-radius: 50%;

    background:
        rgba(37, 99, 235, 0.10);

    filter: blur(70px);

    top: -100px;
    left: 50%;

    transform: translateX(-50%);

    z-index: -1;
}


/* =====================================================
   LOADING SCREEN
===================================================== */

#loadingScreen {

    position: fixed;
    inset: 0;

    display: flex;

    flex-direction: column;

    align-items: center;
    justify-content: center;

    background:
        radial-gradient(
            circle at center,
            rgba(30, 64, 175, 0.28),
            transparent 45%
        ),
        #050914;

    z-index: 9999;

    transition:
        opacity 0.55s ease,
        visibility 0.55s ease;
}

#loadingScreen.hide {
    opacity: 0;
    visibility: hidden;
}

.loader-container {
    position: relative;

    width: 128px;
    height: 128px;

    display: flex;

    align-items: center;
    justify-content: center;
}

.loader-ring {

    position: absolute;

    width: 128px;
    height: 128px;

    border-radius: 50%;

    border:
        2px solid rgba(59, 130, 246, 0.12);

    border-top-color: #60a5fa;

    animation:
        spin 1.2s linear infinite;
}

.falcon-loader {

    width: 108px;
    height: 108px;

    border-radius: 32px;

    display: flex;

    align-items: center;
    justify-content: center;

    font-size: 52px;

    background:
        linear-gradient(
            145deg,
            rgba(59,130,246,0.28),
            rgba(15,23,42,0.85)
        );

    border:
        1px solid rgba(148,163,184,0.22);

    box-shadow:
        0 0 45px rgba(37,99,235,0.28),
        inset 0 1px 0 rgba(255,255,255,0.08);

    animation:
        falconPulse 1.5s ease-in-out infinite;
}

.loading-title {

    margin-top: 28px;

    font-size: 24px;

    font-weight: 800;

    letter-spacing: 2px;
}

.loading-subtitle {

    margin-top: 8px;

    font-size: 13px;

    color: #94a3b8;

    letter-spacing: 0.5px;
}

.loading-dots {

    margin-top: 18px;

    font-size: 18px;

    letter-spacing: 5px;

    color: #60a5fa;

    animation:
        dots 1.2s infinite;
}


/* =====================================================
   APP CONTENT
===================================================== */

#appContent {

    display: none;

    min-height: 100vh;

    padding:
        22px
        16px
        30px;
}

#appContent.show {
    display: block;
}


/* =====================================================
   BRAND
===================================================== */

.brand {

    text-align: center;

    margin-top: 8px;

    margin-bottom: 24px;
}

.brand-icon {

    width: 58px;
    height: 58px;

    margin: auto;

    border-radius: 19px;

    display: flex;

    align-items: center;
    justify-content: center;

    font-size: 29px;

    background:
        linear-gradient(
            145deg,
            rgba(59,130,246,0.26),
            rgba(15,23,42,0.88)
        );

    border:
        1px solid rgba(148,163,184,0.20);

    box-shadow:
        0 10px 35px rgba(37,99,235,0.18);
}

.brand-title {

    margin-top: 13px;

    font-size: 23px;

    font-weight: 850;

    letter-spacing: 2px;
}

.brand-subtitle {

    margin-top: 6px;

    color: #94a3b8;

    font-size: 12px;
}


/* =====================================================
   VERIFICATION CARD
===================================================== */

.verify-card {

    padding: 21px;

    border-radius: 24px;

    background:
        linear-gradient(
            145deg,
            rgba(15,23,42,0.92),
            rgba(15,23,42,0.66)
        );

    border:
        1px solid rgba(148,163,184,0.15);

    box-shadow:
        0 18px 45px rgba(0,0,0,0.25);

    backdrop-filter: blur(18px);
}

.verify-title {

    font-size: 20px;

    font-weight: 800;

    margin-bottom: 8px;
}

.verify-description {

    color: #94a3b8;

    line-height: 1.55;

    font-size: 13px;
}

.progress-row {

    display: flex;

    align-items: center;

    justify-content: space-between;

    margin-top: 18px;

    font-size: 12px;

    color: #94a3b8;
}

.progress-count {

    color: #60a5fa;

    font-weight: 800;
}

.progress-bar {

    width: 100%;
    height: 7px;

    margin-top: 9px;

    border-radius: 99px;

    background:
        rgba(148,163,184,0.10);

    overflow: hidden;
}

.progress-fill {

    width: 0%;

    height: 100%;

    border-radius: inherit;

    background:
        linear-gradient(
            90deg,
            #2563eb,
            #38bdf8
        );

    transition:
        width 0.4s ease;
}


/* =====================================================
   CHANNEL LIST
===================================================== */

.channel-list {

    margin-top: 17px;

    display: flex;

    flex-direction: column;

    gap: 10px;
}

.channel-card {

    display: flex;

    align-items: center;

    gap: 12px;

    padding: 13px;

    border-radius: 18px;

    background:
        rgba(15,23,42,0.72);

    border:
        1px solid rgba(148,163,184,0.12);

    transition:
        transform 0.2s ease,
        border-color 0.2s ease;
}

.channel-card:active {
    transform: scale(0.985);
}

.channel-icon {

    width: 43px;
    height: 43px;

    flex-shrink: 0;

    border-radius: 14px;

    display: flex;

    align-items: center;
    justify-content: center;

    font-size: 20px;

    background:
        rgba(37,99,235,0.15);

    border:
        1px solid rgba(59,130,246,0.14);
}

.channel-info {

    min-width: 0;

    flex: 1;
}

.channel-name {

    font-size: 14px;

    font-weight: 700;

    white-space: nowrap;

    overflow: hidden;

    text-overflow: ellipsis;
}

.channel-username {

    margin-top: 3px;

    color: #64748b;

    font-size: 11px;
}

.channel-button {

    border: 0;

    min-width: 72px;

    padding: 9px 12px;

    border-radius: 12px;

    background:
        linear-gradient(
            135deg,
            #2563eb,
            #3b82f6
        );

    color: white;

    font-size: 12px;

    font-weight: 800;

    cursor: pointer;
}

.channel-button.joined {

    background:
        rgba(34,197,94,0.12);

    color: #4ade80;

    border:
        1px solid rgba(74,222,128,0.16);

    cursor: default;
}


/* =====================================================
   CHECK BUTTON
===================================================== */

.check-button {

    width: 100%;

    margin-top: 16px;

    padding: 14px;

    border: 0;

    border-radius: 16px;

    color: white;

    background:
        linear-gradient(
            135deg,
            #2563eb,
            #0284c7
        );

    font-size: 14px;

    font-weight: 800;

    box-shadow:
        0 10px 28px rgba(37,99,235,0.20);

    cursor: pointer;
}

.check-button:disabled {

    opacity: 0.55;

    cursor: default;
}


/* =====================================================
   SUCCESS
===================================================== */

.success-screen {

    display: none;

    text-align: center;

    padding: 38px 20px;
}

.success-screen.show {
    display: block;
}

.success-icon {

    width: 84px;
    height: 84px;

    margin: auto;

    border-radius: 50%;

    display: flex;

    align-items: center;
    justify-content: center;

    font-size: 38px;

    background:
        rgba(34,197,94,0.12);

    border:
        1px solid rgba(74,222,128,0.20);

    box-shadow:
        0 0 45px rgba(34,197,94,0.12);

    animation:
        successPop 0.55s ease;
}

.success-title {

    margin-top: 22px;

    font-size: 24px;

    font-weight: 850;
}

.success-text {

    margin-top: 8px;

    color: #94a3b8;

    font-size: 13px;

    line-height: 1.5;
}


/* =====================================================
   DASHBOARD PLACEHOLDER
===================================================== */

.dashboard {

    display: none;

    text-align: center;

    padding-top: 15px;
}

.dashboard.show {
    display: block;
}

.dashboard-title {

    font-size: 25px;

    font-weight: 850;

    letter-spacing: 1px;
}

.dashboard-subtitle {

    margin-top: 7px;

    color: #94a3b8;

    font-size: 13px;
}

.dashboard-box {

    margin-top: 25px;

    padding: 25px 18px;

    border-radius: 22px;

    background:
        rgba(15,23,42,0.75);

    border:
        1px solid rgba(148,163,184,0.13);
}

.dashboard-box-title {

    font-size: 18px;

    font-weight: 800;
}

.dashboard-box-text {

    margin-top: 8px;

    color: #64748b;

    font-size: 12px;

    line-height: 1.5;
}


/* =====================================================
   ANIMATIONS
===================================================== */

@keyframes spin {

    to {
        transform: rotate(360deg);
    }
}

@keyframes falconPulse {

    0%,
    100% {
        transform: scale(1);
    }

    50% {
        transform: scale(1.06);
    }
}

@keyframes dots {

    0%,
    100% {
        opacity: 0.35;
    }

    50% {
        opacity: 1;
    }
}

@keyframes successPop {

    0% {
        transform: scale(0.5);
        opacity: 0;
    }

    100% {
        transform: scale(1);
        opacity: 1;
    }
}

</style>

</head>


<body>


<div class="app-bg"></div>

<div class="glow"></div>


<!-- =====================================================
     LOADING SCREEN
===================================================== -->

<div id="loadingScreen">

    <div class="loader-container">

        <div class="loader-ring"></div>

        <div class="falcon-loader">
            🦅
        </div>

    </div>

    <div class="loading-title">
        FALCON WORLD
    </div>

    <div class="loading-subtitle">
        Preparing your experience
    </div>

    <div class="loading-dots">
        • • •
    </div>

</div>


<!-- =====================================================
     MAIN APP
===================================================== -->

<div id="appContent">


    <!-- BRAND -->

    <div class="brand">

        <div class="brand-icon">
            🦅
        </div>

        <div class="brand-title">
            FALCON WORLD
        </div>

        <div class="brand-subtitle">
            Earn. Refer. Grow.
        </div>

    </div>


    <!-- =================================================
         VERIFICATION
    ================================================== -->

    <div id="verificationArea">


        <div class="verify-card">

            <div class="verify-title">
                🔐 VERIFY & UNLOCK
            </div>

            <div class="verify-description">
                Join all required channels to unlock
                Falcon World and continue.
            </div>


            <div class="progress-row">

                <span>
                    Verification progress
                </span>

                <span
                    id="progressCount"
                    class="progress-count"
                >
                    0/6
                </span>

            </div>


            <div class="progress-bar">

                <div
                    id="progressFill"
                    class="progress-fill"
                ></div>

            </div>

        </div>


        <div
            id="channelList"
            class="channel-list"
        ></div>


        <button
            id="checkButton"
            class="check-button"
            onclick="checkMembership()"
        >
            🔄 Check Verification
        </button>

    </div>


    <!-- =================================================
         SUCCESS
    ================================================== -->

    <div
        id="successScreen"
        class="success-screen"
    >

        <div class="success-icon">
            ✓
        </div>

        <div class="success-title">
            Verification Complete
        </div>

        <div class="success-text">
            All required channels have been verified.
            Welcome to Falcon World.
        </div>

    </div>


    <!-- =================================================
         DASHBOARD
    ================================================== -->

    <div
        id="dashboard"
        class="dashboard"
    >

        <div class="dashboard-title">
            FALCON WORLD
        </div>

        <div class="dashboard-subtitle">
            Earn. Refer. Withdraw.
        </div>

        <div class="dashboard-box">

            <div class="dashboard-box-title">
                🚀 You're In
            </div>

            <div class="dashboard-box-text">
                Your verification is complete.
                The Falcon World earning dashboard
                will be available in the next stage.
            </div>

        </div>

    </div>


</div>


<script>

/* =====================================================
   TELEGRAM
===================================================== */

const tg =
    window.Telegram.WebApp;

tg.ready();

tg.expand();


/* =====================================================
   GLOBAL
===================================================== */

let initData = "";

let userId = null;


/* =====================================================
   INITIALIZE TELEGRAM
===================================================== */

function initializeTelegram() {

    initData =
        tg.initData || "";

    if (
        tg.initDataUnsafe &&
        tg.initDataUnsafe.user
    ) {

        userId =
            tg.initDataUnsafe.user.id;

    }

}


/* =====================================================
   OPEN CHANNEL
===================================================== */

function openChannel(url) {

    try {

        if (
            tg &&
            typeof tg.openTelegramLink ===
                "function"
        ) {

            tg.openTelegramLink(url);

        } else {

            window.open(
                url,
                "_blank"
            );

        }

    } catch (error) {

        window.open(
            url,
            "_blank"
        );

    }

}


/* =====================================================
   CHECK MEMBERSHIP
===================================================== */

async function checkMembership() {

    const button =
        document.getElementById(
            "checkButton"
        );


    if (!initData) {

        showTelegramError();

        return;

    }


    button.disabled = true;

    button.innerText =
        "Checking...";


    try {

        const response =
            await fetch(
                "/api/verify",
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json",

                        "X-Telegram-Init-Data":
                            initData
                    },

                    body:
                        JSON.stringify({})
                }
            );


        const data =
            await response.json();


        if (!response.ok) {

            if (
                data &&
                data.error ===
                    "telegram_required"
            ) {

                showTelegramError();

                return;

            }


            alert(
                data.error ||
                "Verification failed. Please try again."
            );

            return;

        }


        renderChannels(
            data.channels || []
        );


        updateProgress(
            data.verified_count,
            data.total
        );


        if (data.verified) {

            showSuccess();

        }

    } catch (error) {

        console.error(error);

        alert(
            "Connection error. Please try again."
        );

    } finally {

        button.disabled = false;

        button.innerText =
            "🔄 Check Verification";

    }

}


/* =====================================================
   RENDER CHANNELS
===================================================== */

function renderChannels(
    channels
) {

    const container =
        document.getElementById(
            "channelList"
        );


    container.innerHTML = "";


    channels.forEach(
        (channel) => {

            const card =
                document.createElement(
                    "div"
                );


            card.className =
                "channel-card";


            const buttonText =
                channel.joined
                    ? "Joined ✓"
                    : "Join";


            const buttonClass =
                channel.joined
                    ? "channel-button joined"
                    : "channel-button";


            const disabled =
                channel.joined
                    ? "disabled"
                    : "";


            card.innerHTML = `

                <div class="channel-icon">
                    ${
                        channel.joined
                            ? "✓"
                            : "📢"
                    }
                </div>

                <div class="channel-info">

                    <div class="channel-name">
                        ${escapeHtml(
                            channel.name
                        )}
                    </div>

                    <div class="channel-username">
                        ${escapeHtml(
                            channel.username
                        )}
                    </div>

                </div>

                <button
                    class="${buttonClass}"
                    ${disabled}
                    onclick="openChannel('${channel.url}')"
                >
                    ${buttonText}
                </button>

            `;


            container.appendChild(
                card
            );

        }
    );

}


/* =====================================================
   UPDATE PROGRESS
===================================================== */

function updateProgress(
    count,
    total
) {

    const countElement =
        document.getElementById(
            "progressCount"
        );


    const fill =
        document.getElementById(
            "progressFill"
        );


    countElement.innerText =
        `${count}/${total}`;


    const percentage =
        total > 0
            ? (count / total) * 100
            : 0;


    fill.style.width =
        `${percentage}%`;

}


/* =====================================================
   SUCCESS
===================================================== */

function showSuccess() {

    const verificationArea =
        document.getElementById(
            "verificationArea"
        );


    const successScreen =
        document.getElementById(
            "successScreen"
        );


    const dashboard =
        document.getElementById(
            "dashboard"
        );


    verificationArea.style.display =
        "none";


    successScreen.classList.add(
        "show"
    );


    setTimeout(
        () => {

            successScreen.classList.remove(
                "show"
            );

            dashboard.classList.add(
                "show"
            );

        },
        1300
    );

}


/* =====================================================
   TELEGRAM ERROR
===================================================== */

function showTelegramError() {

    const container =
        document.getElementById(
            "channelList"
        );


    container.innerHTML = `

        <div class="verify-card">

            <div class="verify-title">
                📱 Open in Telegram
            </div>

            <div class="verify-description">
                Please open Falcon World from
                the Telegram Menu Button to
                continue verification.
            </div>

        </div>

    `;

}


/* =====================================================
   ESCAPE HTML
===================================================== */

function escapeHtml(
    value
) {

    return String(value)
        .replaceAll(
            "&",
            "&amp;"
        )
        .replaceAll(
            "<",
            "&lt;"
        )
        .replaceAll(
            ">",
            "&gt;"
        )
        .replaceAll(
            '"',
            "&quot;"
        )
        .replaceAll(
            "'",
            "&#039;"
        );

}


/* =====================================================
   START APP
===================================================== */

async function startApp() {

    initializeTelegram();


    setTimeout(
        () => {

            const loading =
                document.getElementById(
                    "loadingScreen"
                );


            const content =
                document.getElementById(
                    "appContent"
                );


            loading.classList.add(
                "hide"
            );


            content.classList.add(
                "show"
            );


            checkMembership();

        },
        1800
    );

}


/* =====================================================
   WHEN USER RETURNS FROM CHANNEL
===================================================== */

document.addEventListener(
    "visibilitychange",
    () => {

        if (
            document.visibilityState ===
                "visible"
        ) {

            if (initData) {

                setTimeout(
                    () => {

                        checkMembership();

                    },
                    500
                );

            }

        }

    }
);


/* =====================================================
   START
===================================================== */

startApp();

</script>

</body>

</html>
"""

    return HTMLResponse(
        content=html
    )


# =========================================================
# VERIFY API
# =========================================================

@app.post("/api/verify")
async def verify_user(
    request: Request
):

    init_data =
        request.headers.get(
            "X-Telegram-Init-Data",
            ""
        )


    user =
        validate_init_data(
            init_data
        )


    if not user:

        return JSONResponse(
            {
                "error":
                    "telegram_required"
            },
            status_code=401
        )


    user_id =
        int(user["id"])


    verification =
        await check_all_channels(
            user_id
        )


    return JSONResponse(
        verification
    )


# =========================================================
# WEBHOOK
# =========================================================

@app.post("/webhook")
async def webhook(
    request: Request
):

    try:

        update =
            await request.json()

    except Exception:

        return {
            "ok": True
        }


    message =
        update.get(
            "message",
            {}
        )


    chat =
        message.get(
            "chat",
            {}
        )


    chat_id =
        chat.get(
            "id"
        )


    text =
        message.get(
            "text",
            ""
        )


    if not chat_id:

        return {
            "ok": True
        }


    # =====================================================
    # START
    # =====================================================

    if text.startswith(
        "/start"
    ):

        welcome_message = """
🦅 *WELCOME TO FALCON WORLD*

💰 *Earn & Complete Tasks*
🎁 *Daily Rewards*
👥 *Referral Rewards*
🚀 *New Opportunities*

📢 *Ads & Promotions:* Contact us
💱 *USDT Exchange:* Buy & Sell

🚀 Open Falcon World from the Menu below.
"""


        await send_message(
            chat_id,
            welcome_message
        )


    return {
        "ok": True
    }


# =========================================================
# STARTUP
# =========================================================

@app.on_event("startup")
async def startup():

    if not BOT_TOKEN:

        print(
            "ERROR: BOT_TOKEN is missing."
        )

        return


    webhook_result =
        await telegram_request(
            "setWebhook",
            {
                "url":
                    WEBHOOK_URL,

                "allowed_updates": [
                    "message"
                ]
            }
        )


    print(
        "Webhook setup:",
        webhook_result
    )


    menu_result =
        await set_menu_button()


    print(
        "Menu button setup:",
        menu_result
    )
