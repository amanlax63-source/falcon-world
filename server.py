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

from bot import (
    init_db,
    configure_bot,
    handle_update,
    get_user,
    is_banned,
    add_balance,
    claim_daily_bonus,
    get_referral_count,
    get_setting,
    save_wallet,
    create_withdrawal,
    get_active_tasks,
    submit_task,
    reward_referrer_after_verification,
    REQUIRED_CHANNELS,
    telegram_request,
    send_message,
    send_admin_message,
    withdrawal_keyboard,
    DEFAULT_DAILY_BONUS,
    DEFAULT_REFERRAL_REWARD,
    DEFAULT_MIN_WITHDRAW,
)

# ============================================================
# FALCON WORLD - FASTAPI + MINI APP SERVER
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
BOT_USERNAME = os.getenv("BOT_USERNAME", "FalconWorld_Bot").strip().lstrip("@")
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", os.getenv("ADMIN_ID", "")).strip()

WEBHOOK_URL = os.getenv(
    "WEBHOOK_URL",
    "https://falcon-world.onrender.com/webhook",
).strip()

MINI_APP_URL = os.getenv(
    "MINI_APP_URL",
    "https://falcon-world.onrender.com/app",
).strip()

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

app = FastAPI(title="Falcon World")


# ============================================================
# TELEGRAM MINI APP INIT DATA VALIDATION
# ============================================================

def validate_init_data(init_data: str):
    if not init_data or not BOT_TOKEN:
        return None

    try:
        parsed = dict(
            parse_qsl(
                init_data,
                keep_blank_values=True,
            )
        )

        received_hash = parsed.pop("hash", None)

        if not received_hash:
            return None

        data_check_string = "\n".join(
            f"{key}={parsed[key]}"
            for key in sorted(parsed.keys())
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

        if not hmac.compare_digest(
            calculated_hash,
            received_hash,
        ):
            return None

        auth_date = int(
            parsed.get("auth_date", "0")
        )

        # Telegram Mini App authorization expires after 24 hours.
        if auth_date <= 0:
            return None

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


async def get_webapp_user(request: Request):
    init_data = request.headers.get(
        "X-Telegram-Init-Data",
        "",
    )

    return validate_init_data(init_data)


# ============================================================
# CHANNEL VERIFICATION
# ============================================================

async def check_channel_membership(
    user_id: int,
    channel_username: str,
):
    result = await telegram_request(
        "getChatMember",
        {
            "chat_id": channel_username,
            "user_id": user_id,
        },
    )

    if not result.get("ok"):
        return False

    member = result.get("result", {})
    status = member.get("status")

    return status in {
        "member",
        "administrator",
        "creator",
    }


async def check_all_channels(user_id: int):
    async def check(channel):
        joined = await check_channel_membership(
            user_id,
            channel["username"],
        )

        return {
            **channel,
            "joined": joined,
        }

    results = await asyncio.gather(
        *(check(channel) for channel in REQUIRED_CHANNELS)
    )

    verified_count = sum(
        1 for channel in results
        if channel["joined"]
    )

    verified = (
        verified_count == len(REQUIRED_CHANNELS)
    )

    return {
        "verified": verified,
        "verified_count": verified_count,
        "total": len(REQUIRED_CHANNELS),
        "channels": results,
    }


# ============================================================
# MINI APP HTML
# ============================================================

HTML = r"""
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
/>

<title>Falcon World</title>

<script src="https://telegram.org/js/telegram-web-app.js"></script>

<style>
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
    font-family:
        Inter,
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        sans-serif;
    background: #06111f;
    color: #ffffff;
}

body {
    overflow-x: hidden;
}

button,
input,
textarea {
    font: inherit;
}

button {
    border: 0;
    cursor: pointer;
}

.hidden {
    display: none !important;
}

/* ============================================================
   LOADING
============================================================ */

#loading {
    position: fixed;
    inset: 0;
    z-index: 9999;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-direction: column;
    background:
        radial-gradient(
            circle at top,
            #123b67 0%,
            #06111f 45%,
            #02070d 100%
        );
}

.logo {
    width: 92px;
    height: 92px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 52px;
    background: linear-gradient(
        145deg,
        #1b8cff,
        #06457e
    );
    box-shadow:
        0 0 35px rgba(27, 140, 255, .35);
    margin-bottom: 20px;
}

.loading-title {
    font-size: 25px;
    font-weight: 900;
    letter-spacing: .5px;
}

.loading-text {
    margin-top: 8px;
    color: #91a8c0;
    font-size: 14px;
}

.progress-wrap {
    width: 220px;
    height: 6px;
    margin-top: 25px;
    border-radius: 10px;
    background: #14283e;
    overflow: hidden;
}

.progress {
    width: 0%;
    height: 100%;
    border-radius: 10px;
    background: linear-gradient(
        90deg,
        #168cff,
        #59c3ff
    );
    transition: width .2s ease;
}

.percent {
    margin-top: 9px;
    color: #6ebfff;
    font-weight: 700;
    font-size: 13px;
}

/* ============================================================
   APP
============================================================ */

#app {
    min-height: 100vh;
    padding-bottom: 35px;
}

.topbar {
    padding:
        22px
        18px
        16px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    background:
        linear-gradient(
            180deg,
            rgba(11, 43, 73, .95),
            rgba(6, 17, 31, .7)
        );
}

.brand {
    display: flex;
    align-items: center;
    gap: 12px;
}

.brand-icon {
    width: 48px;
    height: 48px;
    border-radius: 15px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 27px;
    background: linear-gradient(
        145deg,
        #158fff,
        #07518c
    );
}

.brand-name {
    font-size: 19px;
    font-weight: 900;
}

.brand-sub {
    margin-top: 2px;
    color: #7894af;
    font-size: 11px;
}

.refresh {
    width: 42px;
    height: 42px;
    border-radius: 13px;
    color: white;
    background: #102b43;
    font-size: 19px;
}

.container {
    width: min(720px, 100%);
    margin: auto;
    padding: 0 15px;
}

/* ============================================================
   VERIFICATION
============================================================ */

.verify-card {
    margin-top: 14px;
    padding: 19px;
    border-radius: 22px;
    background:
        linear-gradient(
            145deg,
            rgba(16, 48, 77, .95),
            rgba(8, 25, 42, .95)
        );
    border: 1px solid rgba(79, 153, 214, .15);
}

.verify-title {
    font-size: 21px;
    font-weight: 900;
}

.verify-desc {
    color: #91a8bd;
    font-size: 13px;
    line-height: 1.55;
    margin-top: 7px;
}

.channel {
    margin-top: 10px;
    padding: 12px;
    border-radius: 16px;
    display: flex;
    align-items: center;
    gap: 11px;
    background: #0b2034;
}

.channel-icon {
    width: 42px;
    height: 42px;
    flex: 0 0 42px;
    border-radius: 13px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #123653;
}

.channel-info {
    flex: 1;
    min-width: 0;
}

.channel-name {
    font-size: 14px;
    font-weight: 800;
}

.channel-status {
    margin-top: 3px;
    color: #7f9bb4;
    font-size: 11px;
}

.join-btn {
    padding: 9px 12px;
    border-radius: 11px;
    background: #148cff;
    color: white;
    font-size: 12px;
    font-weight: 800;
}

.join-btn.joined {
    background: #123e37;
    color: #62e0bc;
}

.verify-btn {
    width: 100%;
    margin-top: 14px;
    padding: 14px;
    border-radius: 15px;
    color: white;
    background:
        linear-gradient(
            135deg,
            #168dff,
            #0963b4
        );
    font-weight: 900;
    font-size: 14px;
}

.verify-message {
    margin-top: 10px;
    text-align: center;
    color: #8ea8bf;
    font-size: 12px;
}

/* ============================================================
   DASHBOARD
============================================================ */

.balance-card {
    margin-top: 15px;
    padding: 21px;
    border-radius: 23px;
    background:
        linear-gradient(
            135deg,
            #0b4776,
            #082a49 55%,
            #061d33
        );
    border: 1px solid rgba(83, 177, 255, .18);
    box-shadow:
        0 16px 45px rgba(0, 0, 0, .2);
}

.balance-label {
    color: #a5c7e4;
    font-size: 12px;
}

.balance {
    margin-top: 6px;
    font-size: 33px;
    font-weight: 950;
}

.balance-sub {
    margin-top: 5px;
    color: #87b4d7;
    font-size: 11px;
}

.action-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 11px;
    margin-top: 14px;
}

.action {
    min-height: 90px;
    padding: 15px;
    border-radius: 19px;
    text-align: left;
    color: white;
    background:
        linear-gradient(
            145deg,
            #102b43,
            #0a1d30
        );
    border: 1px solid rgba(105, 164, 211, .11);
}

.action:active {
    transform: scale(.98);
}

.action-icon {
    font-size: 25px;
}

.action-title {
    margin-top: 9px;
    font-size: 13px;
    font-weight: 850;
}

.action-sub {
    margin-top: 3px;
    color: #6f8ba4;
    font-size: 10px;
}

/* ============================================================
   PANELS
============================================================ */

.panel {
    margin-top: 14px;
    padding: 18px;
    border-radius: 21px;
    background: #091c2f;
    border: 1px solid rgba(95, 150, 193, .12);
}

.panel-title {
    font-size: 18px;
    font-weight: 900;
}

.panel-text {
    margin-top: 8px;
    color: #8ea7bd;
    font-size: 13px;
    line-height: 1.6;
}

.copy-box {
    margin-top: 12px;
    padding: 12px;
    border-radius: 13px;
    background: #061522;
    color: #74c5ff;
    font-size: 11px;
    word-break: break-all;
}

.small-btn {
    margin-top: 10px;
    padding: 11px 14px;
    border-radius: 12px;
    background: #12456d;
    color: white;
    font-weight: 800;
    font-size: 12px;
}

.task-item {
    margin-top: 10px;
    padding: 13px;
    border-radius: 15px;
    background: #0d263d;
}

.task-title {
    font-weight: 850;
    font-size: 14px;
}

.task-reward {
    margin-top: 5px;
    color: #5ec3ff;
    font-weight: 800;
    font-size: 12px;
}

.task-link {
    display: block;
    margin-top: 6px;
    color: #8faec8;
    font-size: 11px;
    word-break: break-all;
}

.status {
    margin-top: 6px;
    font-size: 11px;
    color: #8ea8bd;
}

.input {
    width: 100%;
    margin-top: 11px;
    padding: 13px;
    outline: none;
    border: 1px solid #183852;
    border-radius: 13px;
    color: white;
    background: #061522;
}

.input:focus {
    border-color: #158cff;
}

.select {
    width: 100%;
    margin-top: 11px;
    padding: 13px;
    border-radius: 13px;
    color: white;
    background: #061522;
    border: 1px solid #183852;
}

.primary {
    width: 100%;
    margin-top: 12px;
    padding: 13px;
    border-radius: 13px;
    background: #138bfa;
    color: white;
    font-weight: 900;
}

.danger {
    background: #6c2430;
}

.note {
    margin-top: 10px;
    color: #738da5;
    font-size: 10px;
    line-height: 1.5;
}

.empty {
    padding: 20px 5px;
    text-align: center;
    color: #7891a8;
    font-size: 13px;
}

/* ============================================================
   TOAST
============================================================ */

#toast {
    position: fixed;
    left: 15px;
    right: 15px;
    bottom: 18px;
    z-index: 9998;
    padding: 13px 15px;
    border-radius: 14px;
    text-align: center;
    color: white;
    background: rgba(11, 34, 54, .97);
    border: 1px solid rgba(97, 170, 224, .2);
    box-shadow: 0 15px 40px rgba(0,0,0,.35);
    font-size: 12px;
}

.footer {
    padding: 25px 10px 5px;
    text-align: center;
    color: #49657d;
    font-size: 10px;
}
</style>
</head>

<body>

<div id="loading">
    <div class="logo">🦅</div>
    <div class="loading-title">Falcon World</div>
    <div class="loading-text">Loading your account...</div>

    <div class="progress-wrap">
        <div class="progress" id="progress"></div>
    </div>

    <div class="percent" id="percent">0%</div>
</div>

<div id="app" class="hidden">

    <div class="topbar">
        <div class="brand">
            <div class="brand-icon">🦅</div>
            <div>
                <div class="brand-name">Falcon World</div>
                <div class="brand-sub">
                    Earn • Tasks • Rewards
                </div>
            </div>
        </div>

        <button class="refresh" onclick="refreshAll()">↻</button>
    </div>

    <div class="container">

        <!-- VERIFICATION -->
        <div id="verification" class="verify-card hidden">
            <div class="verify-title">
                🔐 Join Required Channels
            </div>

            <div class="verify-desc">
                Join all required channels below, then press
                <b>Verify Membership</b> to unlock Falcon World.
            </div>

            <div id="channels"></div>

            <button
                class="verify-btn"
                onclick="verifyMembership()"
            >
                ✅ Verify Membership
            </button>

            <div
                id="verify-message"
                class="verify-message"
            ></div>
        </div>

        <!-- DASHBOARD -->
        <div id="dashboard" class="hidden">

            <div class="balance-card">
                <div class="balance-label">
                    AVAILABLE BALANCE
                </div>

                <div class="balance">
                    <span id="balance">0.00</span> ETB
                </div>

                <div class="balance-sub">
                    Falcon World rewards
                </div>
            </div>

            <div class="action-grid">

                <button
                    class="action"
                    onclick="showDaily()"
                >
                    <div class="action-icon">🎁</div>
                    <div class="action-title">
                        Daily Bonus
                    </div>
                    <div class="action-sub">
                        Claim every 24 hours
                    </div>
                </button>

                <button
                    class="action"
                    onclick="showReferral()"
                >
                    <div class="action-icon">👥</div>
                    <div class="action-title">
                        Invite Friends
                    </div>
                    <div class="action-sub">
                        Earn referral rewards
                    </div>
                </button>

                <button
                    class="action"
                    onclick="showTasks()"
                >
                    <div class="action-icon">📋</div>
                    <div class="action-title">
                        Tasks
                    </div>
                    <div class="action-sub">
                        Complete & earn
                    </div>
                </button>

                <button
                    class="action"
                    onclick="showWallet()"
                >
                    <div class="action-icon">👛</div>
                    <div class="action-title">
                        Wallet
                    </div>
                    <div class="action-sub">
                        CBE / Telebirr
                    </div>
                </button>

                <button
                    class="action"
                    onclick="showWithdraw()"
                >
                    <div class="action-icon">💸</div>
                    <div class="action-title">
                        Withdraw
                    </div>
                    <div class="action-sub">
                        Request payment
                    </div>
                </button>

                <button
                    class="action"
                    onclick="showHelp()"
                >
                    <div class="action-icon">❓</div>
                    <div class="action-title">
                        Help
                    </div>
                    <div class="action-sub">
                        How it works
                    </div>
                </button>

            </div>

            <div id="panel"></div>

            <div class="footer">
                🦅 Falcon World
            </div>
        </div>

    </div>
</div>

<div id="toast" class="hidden"></div>

<script>
const tg = window.Telegram && window.Telegram.WebApp
    ? window.Telegram.WebApp
    : null;

if (tg) {
    tg.ready();
    tg.expand();
}

let currentVerification = null;
let currentTasks = [];
let user = null;

function toast(message) {
    const box = document.getElementById("toast");
    box.textContent = message;
    box.classList.remove("hidden");

    clearTimeout(window.toastTimer);

    window.toastTimer = setTimeout(() => {
        box.classList.add("hidden");
    }, 3000);
}

function initHeaders() {
    if (!tg) return {};

    return {
        "Content-Type": "application/json",
        "X-Telegram-Init-Data": tg.initData || ""
    };
}

async function api(url, options = {}) {
    const headers = {
        ...initHeaders(),
        ...(options.headers || {})
    };

    const response = await fetch(url, {
        ...options,
        headers
    });

    let data = {};

    try {
        data = await response.json();
    } catch (_) {}

    if (!response.ok) {
        throw new Error(
            data.message ||
            data.error ||
            "Request failed."
        );
    }

    return data;
}

function setProgress(value) {
    document.getElementById("progress").style.width =
        value + "%";

    document.getElementById("percent").textContent =
        value + "%";
}

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

async function boot() {
    try {
        if (!tg || !tg.initData) {
            throw new Error(
                "Please open Falcon World from Telegram."
            );
        }

        setProgress(25);

        currentVerification = await api(
            "/api/verify",
            {method: "POST"}
        );

        setProgress(65);

        if (!currentVerification.verified) {
            renderChannels(
                currentVerification.channels
            );

            document
                .getElementById("verification")
                .classList.remove("hidden");
        } else {
            await openDashboard();
        }

        setProgress(100);

        setTimeout(() => {
            document
                .getElementById("loading")
                .classList.add("hidden");

            document
                .getElementById("app")
                .classList.remove("hidden");
        }, 250);

    } catch (error) {
        setProgress(100);

        setTimeout(() => {
            document
                .getElementById("loading")
                .classList.add("hidden");

            document
                .getElementById("app")
                .classList.remove("hidden");

            document
                .getElementById("verification")
                .classList.remove("hidden");

            document.getElementById("verify-message")
                .textContent = error.message;
        }, 250);
    }
}

function renderChannels(channels) {
    const box = document.getElementById("channels");

    box.innerHTML = channels.map(channel => {
        const joined = channel.joined;

        return `
            <div class="channel">
                <div class="channel-icon">📢</div>

                <div class="channel-info">
                    <div class="channel-name">
                        ${escapeHtml(channel.name)}
                    </div>

                    <div class="channel-status">
                        ${joined
                            ? "✅ Joined"
                            : "⚠️ Not joined"}
                    </div>
                </div>

                <button
                    class="join-btn ${joined ? "joined" : ""}"
                    onclick="openChannel('${channel.url}')"
                >
                    ${joined ? "Joined" : "Join"}
                </button>
            </div>
        `;
    }).join("");
}

function openChannel(url) {
    if (tg && tg.openTelegramLink) {
        tg.openTelegramLink(url);
    } else {
        window.open(url, "_blank");
    }
}

async function verifyMembership() {
    const message =
        document.getElementById("verify-message");

    message.textContent = "Checking membership...";

    try {
        const data = await api(
            "/api/verify",
            {method: "POST"}
        );

        currentVerification = data;

        if (!data.verified) {
            renderChannels(data.channels);

            message.textContent =
                `Joined ${data.verified_count}/${data.total}. ` +
                "Please join all channels.";
            return;
        }

        message.textContent =
            "✅ Verification successful!";

        await openDashboard();

    } catch (error) {
        message.textContent = error.message;
    }
}

async function openDashboard() {
    document
        .getElementById("verification")
        .classList.add("hidden");

    document
        .getElementById("dashboard")
        .classList.remove("hidden");

    await refreshAll();
}

async function refreshAll() {
    try {
        const data = await api("/api/me");

        user = data;

        document.getElementById("balance")
            .textContent =
            Number(data.balance || 0).toFixed(2);

    } catch (error) {
        toast(error.message);
    }
}

function panel(title, body) {
    document.getElementById("panel").innerHTML = `
        <div class="panel">
            <div class="panel-title">${title}</div>
            ${body}
        </div>
    `;
}

async function showDaily() {
    const bonus = Number(
        user?.daily_bonus || 0.50
    );

    panel(
        "🎁 Daily Bonus",
        `
        <div class="panel-text">
            Claim your daily reward once every 24 hours.
            <br><br>
            Today's reward:
            <b>${bonus.toFixed(2)} ETB</b>
        </div>

        <button
            class="primary"
            onclick="claimDaily()"
        >
            🎁 Claim ${bonus.toFixed(2)} ETB
        </button>
        `
    );
}

async function claimDaily() {
    try {
        const data = await api(
            "/api/daily-bonus",
            {
                method: "POST"
            }
        );

        toast(
            `🎁 +${Number(data.reward).toFixed(2)} ETB added!`
        );

        await refreshAll();
        showDaily();

    } catch (error) {
        toast(error.message);
    }
}

async function showReferral() {
    try {
        const data = await api(
            "/api/referral"
        );

        panel(
            "👥 Invite Friends",
            `
            <div class="panel-text">
                Earn
                <b>${Number(data.reward).toFixed(2)} ETB</b>
                for each referral who completes the required
                channel verification.
                <br><br>
                Paid referrals:
                <b>${data.count}</b>
            </div>

            <div class="copy-box" id="refLink">
                ${escapeHtml(data.link)}
            </div>

            <button
                class="small-btn"
                onclick="copyReferral()"
            >
                📋 Copy Link
            </button>

            <button
                class="primary"
                onclick="shareReferral()"
            >
                🚀 Share Referral Link
            </button>
            `
        );

        window.referralLink = data.link;

    } catch (error) {
        toast(error.message);
    }
}

async function copyReferral() {
    try {
        await navigator.clipboard.writeText(
            window.referralLink
        );

        toast("✅ Referral link copied.");
    } catch (_) {
        toast("Copy failed. Long press the link.");
    }
}

function shareReferral() {
    const text =
        "🦅 Join Falcon World and start earning rewards!";

    const url =
        "https://t.me/share/url?url=" +
        encodeURIComponent(window.referralLink) +
        "&text=" +
        encodeURIComponent(text);

    if (tg && tg.openTelegramLink) {
        tg.openTelegramLink(url);
    } else {
        window.open(url, "_blank");
    }
}

async function showTasks() {
    try {
        const data = await api(
            "/api/tasks"
        );

        currentTasks = data.tasks || [];

        if (!currentTasks.length) {
            panel(
                "📋 Tasks",
                `<div class="empty">
                    No active tasks right now.
                </div>`
            );
            return;
        }

        const html = currentTasks.map(task => {
            let status = "🆕 Available";

            if (task.submission_status === "pending") {
                status = "⏳ Pending";
            } else if (
                task.submission_status === "approved"
            ) {
                status = "✅ Approved";
            } else if (
                task.submission_status === "rejected"
            ) {
                status = "❌ Rejected — resubmit";
            }

            return `
                <div class="task-item">
                    <div class="task-title">
                        #${task.id}
                        ${escapeHtml(task.title)}
                    </div>

                    <div class="task-reward">
                        💰 ${Number(task.reward).toFixed(2)} ETB
                    </div>

                    <a
                        class="task-link"
                        href="${escapeHtml(task.link || "#")}"
                        target="_blank"
                    >
                        🔗 ${escapeHtml(task.link || "No link")}
                    </a>

                    <div class="status">
                        ${status}
                    </div>

                    ${
                        task.submission_status !== "approved"
                        ? `
                        <button
                            class="small-btn"
                            onclick="submitTask(${task.id})"
                        >
                            Submit Proof
                        </button>
                        `
                        : ""
                    }
                </div>
            `;
        }).join("");

        panel(
            "📋 Tasks",
            html +
            `
            <div class="note">
                Complete the task, then submit proof for
                admin review.
            </div>
            `
        );

    } catch (error) {
        toast(error.message);
    }
}

async function submitTask(taskId) {
    const proof = prompt(
        "Send your task proof:"
    );

    if (!proof || !proof.trim()) {
        return;
    }

    try {
        const data = await api(
            `/api/tasks/${taskId}/submit`,
            {
                method: "POST",
                body: JSON.stringify({
                    proof: proof.trim()
                })
            }
        );

        toast(data.message);

        await showTasks();

    } catch (error) {
        toast(error.message);
    }
}

async function showWallet() {
    try {
        const data = await api(
            "/api/wallet"
        );

        panel(
            "👛 Wallet",
            `
            <div class="panel-text">
                Current wallet:
                <b>${escapeHtml(
                    data.wallet_type || "Not set"
                )}</b>
                <br>
                <code>
                    ${escapeHtml(
                        data.wallet_number || "Not set"
                    )}
                </code>
            </div>

            <select
                id="walletType"
                class="select"
            >
                <option value="cbe">CBE</option>
                <option value="telebirr">Telebirr</option>
            </select>

            <input
                id="walletNumber"
                class="input"
                inputmode="numeric"
                placeholder="Wallet number"
            />

            <button
                class="primary"
                onclick="saveWallet()"
            >
                💾 Save Wallet
            </button>

            <div class="note">
                CBE: 13 digits starting with 1000.<br>
                Telebirr: 10 digits starting with 09 or 07.
            </div>
            `
        );

    } catch (error) {
        toast(error.message);
    }
}

async function saveWallet() {
    const type =
        document.getElementById("walletType").value;

    const number =
        document.getElementById("walletNumber").value.trim();

    if (!number) {
        toast("Enter your wallet number.");
        return;
    }

    try {
        const data = await api(
            "/api/wallet",
            {
                method: "POST",
                body: JSON.stringify({
                    wallet_type: type,
                    wallet_number: number
                })
            }
        );

        toast(data.message);

        if (data.suspicious) {
            toast(
                "⚠️ Wallet saved but flagged for review."
            );
        }

        await showWallet();

    } catch (error) {
        toast(error.message);
    }
}

async function showWithdraw() {
    try {
        const data = await api(
            "/api/me"
        );

        const minimum =
            Number(data.min_withdraw || 100);

        panel(
            "💸 Withdraw",
            `
            <div class="panel-text">
                Available:
                <b>${Number(data.balance).toFixed(2)} ETB</b>
                <br>
                Minimum:
                <b>${minimum.toFixed(2)} ETB</b>
            </div>

            <input
                id="withdrawAmount"
                class="input"
                type="number"
                min="${minimum}"
                step="0.01"
                placeholder="Amount"
            />

            <button
                class="primary"
                onclick="withdraw()"
            >
                💸 Request Withdrawal
            </button>

            <div class="note">
                Your balance is reserved when the request
                is submitted. If admin rejects it, the amount
                is returned to your balance.
            </div>
            `
        );

    } catch (error) {
        toast(error.message);
    }
}

async function withdraw() {
    const input =
        document.getElementById("withdrawAmount");

    const amount = Number(input.value);

    if (!amount || amount <= 0) {
        toast("Enter a valid amount.");
        return;
    }

    try {
        const data = await api(
            "/api/withdraw",
            {
                method: "POST",
                body: JSON.stringify({
                    amount: amount
                })
            }
        );

        toast(data.message);

        await refreshAll();
        await showWithdraw();

    } catch (error) {
        toast(error.message);
    }
}

function showHelp() {
    panel(
        "❓ Help",
        `
        <div class="panel-text">
            <b>💰 Balance</b><br>
            Check your current ETB balance.
            <br><br>

            <b>🎁 Daily Bonus</b><br>
            Claim your daily reward every 24 hours.
            <br><br>

            <b>👥 Invite Friends</b><br>
            Share your referral link. Your referral reward
            is paid after the invited user completes
            channel verification.
            <br><br>

            <b>📋 Tasks</b><br>
            Complete tasks and submit proof for review.
            <br><br>

            <b>👛 Wallet</b><br>
            CBE and Telebirr are supported.
            <br><br>

            <b>💸 Withdraw</b><br>
            Reach the minimum withdrawal and submit
            your request.
        </div>
        `
    );
}

boot();
</script>

</body>
</html>
"""


# ============================================================
# BASIC ROUTES
# ============================================================

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
    }


@app.get("/app", response_class=HTMLResponse)
async def mini_app():
    return HTMLResponse(content=HTML)


# ============================================================
# API AUTH HELPER
# ============================================================

async def require_user(request: Request):
    user = await get_webapp_user(request)

    if not user:
        return None, JSONResponse(
            {
                "error": "telegram_required",
                "message": "Open Falcon World from Telegram.",
            },
            status_code=401,
        )

    user_id = int(user["id"])

    db_user = get_user(user_id)

    if not db_user:
        return None, JSONResponse(
            {
                "error": "user_not_found",
                "message": "Start the Falcon World bot first.",
            },
            status_code=404,
        )

    if is_banned(user_id):
        return None, JSONResponse(
            {
                "error": "banned",
                "message": "Your account is restricted.",
            },
            status_code=403,
        )

    return user, None


# ============================================================
# VERIFY API
# ============================================================

@app.post("/api/verify")
async def verify_user(request: Request):
    user = await get_webapp_user(request)

    if not user:
        return JSONResponse(
            {
                "error": "telegram_required",
                "message": "Open Falcon World from Telegram.",
            },
            status_code=401,
        )

    user_id = int(user["id"])

    # Make sure user exists.
    from bot import upsert_user

    upsert_user(
        user_id,
        user.get("username", ""),
        user.get("first_name", ""),
    )

    if is_banned(user_id):
        return JSONResponse(
            {
                "error": "banned",
                "message": "Your account is restricted.",
            },
            status_code=403,
        )

    verification = await check_all_channels(user_id)

    if verification["verified"]:
        from bot import get_db, now

        conn = get_db()
        try:
            conn.execute(
                """
                UPDATE users
                SET verified = 1, last_seen = ?
                WHERE id = ?
                """,
                (now(), user_id),
            )
            conn.commit()
        finally:
            conn.close()

        # Referral reward is paid only once after full verification.
        reward = reward_referrer_after_verification(user_id)

        if reward:
            db_user = get_user(user_id)
            referrer_id = (
                db_user["referred_by"]
                if db_user
                else None
            )

            if referrer_id:
                await send_message(
                    int(referrer_id),
                    "🎉 <b>Referral Reward!</b>\n\n"
                    f"Your referral completed verification.\n"
                    f"💰 +{float(reward):.2f} ETB",
                )

    return JSONResponse(
        verification
    )


# ============================================================
# USER API
# ============================================================

@app.get("/api/me")
async def api_me(request: Request):
    user, error = await require_user(request)

    if error:
        return error

    user_id = int(user["id"])
    db_user = get_user(user_id)

    return {
        "id": user_id,
        "username": user.get("username", ""),
        "first_name": user.get("first_name", ""),
        "balance": float(db_user["balance"] or 0),
        "verified": bool(db_user["verified"]),
        "referrals": get_referral_count(user_id),
        "daily_bonus": get_setting(
            "daily_bonus",
            DEFAULT_DAILY_BONUS,
        ),
        "referral_reward": get_setting(
            "referral_reward",
            DEFAULT_REFERRAL_REWARD,
        ),
        "min_withdraw": get_setting(
            "min_withdraw",
            DEFAULT_MIN_WITHDRAW,
        ),
        "wallet_type": db_user["wallet_type"] or "",
        "wallet_number": db_user["wallet_number"] or "",
    }


# ============================================================
# DAILY BONUS API
# ============================================================

@app.post("/api/daily-bonus")
async def api_daily_bonus(request: Request):
    user, error = await require_user(request)

    if error:
        return error

    user_id = int(user["id"])

    # Verify membership before allowing reward actions.
    verification = await check_all_channels(user_id)

    if not verification["verified"]:
        return JSONResponse(
            {
                "error": "channels_required",
                "message": "Join all required channels first.",
                **verification,
            },
            status_code=403,
        )

    success, result = claim_daily_bonus(user_id)

    if not success:
        return JSONResponse(
            {
                "error": "daily_unavailable",
                "message": str(result),
            },
            status_code=400,
        )

    return {
        "success": True,
        "reward": float(result),
        "message": (
            f"+{float(result):.2f} ETB added to your balance."
        ),
    }


# ============================================================
# REFERRAL API
# ============================================================

@app.get("/api/referral")
async def api_referral(request: Request):
    user, error = await require_user(request)

    if error:
        return error

    user_id = int(user["id"])

    link = (
        f"https://t.me/{BOT_USERNAME}"
        f"?start=ref_{user_id}"
    )

    return {
        "link": link,
        "count": get_referral_count(user_id),
        "reward": get_setting(
            "referral_reward",
            DEFAULT_REFERRAL_REWARD,
        ),
    }


# ============================================================
# WALLET API
# ============================================================

@app.get("/api/wallet")
async def api_wallet(request: Request):
    user, error = await require_user(request)

    if error:
        return error

    db_user = get_user(int(user["id"]))

    return {
        "wallet_type": db_user["wallet_type"] or "",
        "wallet_number": db_user["wallet_number"] or "",
        "suspicious": bool(
            db_user["wallet_suspicious"]
        ),
    }


@app.post("/api/wallet")
async def api_save_wallet(request: Request):
    user, error = await require_user(request)

    if error:
        return error

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            {
                "error": "invalid_json",
                "message": "Invalid request.",
            },
            status_code=400,
        )

    wallet_type = str(
        body.get("wallet_type", "")
    ).strip()

    wallet_number = str(
        body.get("wallet_number", "")
    ).strip()

    success, result, suspicious = save_wallet(
        int(user["id"]),
        wallet_type,
        wallet_number,
    )

    if not success:
        return JSONResponse(
            {
                "error": "invalid_wallet",
                "message": str(result),
            },
            status_code=400,
        )

    if suspicious:
        await send_admin_message(
            "⚠️ <b>Duplicate Wallet Alert</b>\n\n"
            f"User ID: <code>{int(user['id'])}</code>\n"
            f"Wallet: {wallet_type}\n"
            f"Number: <code>{wallet_number}</code>"
        )

    return {
        "success": True,
        "suspicious": suspicious,
        "message": (
            "Wallet saved successfully."
            if not suspicious
            else
            "Wallet saved but flagged for admin review."
        ),
    }


# ============================================================
# TASKS API
# ============================================================

@app.get("/api/tasks")
async def api_tasks(request: Request):
    user, error = await require_user(request)

    if error:
        return error

    rows = get_active_tasks(int(user["id"]))

    tasks = []

    for row in rows:
        tasks.append(
            {
                "id": int(row["id"]),
                "title": row["title"],
                "description": row["description"] or "",
                "link": row["link"] or "",
                "reward": float(row["reward"]),
                "submission_status": (
                    row["submission_status"] or ""
                ),
            }
        )

    return {
        "tasks": tasks,
    }


@app.post("/api/tasks/{task_id}/submit")
async def api_submit_task(
    task_id: int,
    request: Request,
):
    user, error = await require_user(request)

    if error:
        return error

    verification = await check_all_channels(
        int(user["id"])
    )

    if not verification["verified"]:
        return JSONResponse(
            {
                "error": "channels_required",
                "message": "Join all required channels first.",
                **verification,
            },
            status_code=403,
        )

    try:
        body = await request.json()
    except Exception:
        body = {}

    proof = str(
        body.get("proof", "")
    ).strip()

    success, result = submit_task(
        int(user["id"]),
        int(task_id),
        proof,
    )

    if not success:
        return JSONResponse(
            {
                "error": "task_submission_failed",
                "message": str(result),
            },
            status_code=400,
        )

    # Notify admins with the same proof.
    from bot import get_pending_submissions

    pending = get_pending_submissions()

    for row in pending:
        if (
            int(row["task_id"]) == int(task_id)
            and int(row["user_id"]) == int(user["id"])
            and row["status"] == "pending"
        ):
            await send_admin_message(
                "📝 <b>New Task Proof</b>\n\n"
                f"User ID: <code>{int(user['id'])}</code>\n"
                f"Task: <b>{row['title']}</b>\n"
                f"Reward: <b>{float(row['reward']):.2f} ETB</b>\n\n"
                f"<b>Proof:</b>\n{row['proof']}",
                {
                    "inline_keyboard": [
                        [
                            {
                                "text": "✅ Approve",
                                "callback_data":
                                    f"task:approve:{int(row['id'])}",
                            },
                            {
                                "text": "❌ Reject",
                                "callback_data":
                                    f"task:reject:{int(row['id'])}",
                            },
                        ]
                    ]
                },
            )
            break

    return {
        "success": True,
        "message": str(result),
    }


# ============================================================
# WITHDRAW API
# ============================================================

@app.post("/api/withdraw")
async def api_withdraw(request: Request):
    user, error = await require_user(request)

    if error:
        return error

    verification = await check_all_channels(
        int(user["id"])
    )

    if not verification["verified"]:
        return JSONResponse(
            {
                "error": "channels_required",
                "message": "Join all required channels first.",
                **verification,
            },
            status_code=403,
        )

    try:
        body = await request.json()
        amount = float(body.get("amount"))
    except Exception:
        return JSONResponse(
            {
                "error": "invalid_amount",
                "message": "Enter a valid amount.",
            },
            status_code=400,
        )

    success, result = create_withdrawal(
        int(user["id"]),
        amount,
    )

    if not success:
        return JSONResponse(
            {
                "error": "withdrawal_failed",
                "message": str(result),
            },
            status_code=400,
        )

    withdrawal_id = int(
        result["withdrawal_id"]
    )

    suspicious_text = ""

    if result["suspicious"]:
        suspicious_text = (
            "\n⚠️ <b>Wallet flagged for duplicate use.</b>"
        )

    await send_admin_message(
        "💸 <b>New Withdrawal Request</b>\n\n"
        f"ID: <code>#{withdrawal_id}</code>\n"
        f"User ID: <code>{int(user['id'])}</code>\n"
        f"Amount: <b>{float(result['amount']):.2f} ETB</b>\n"
        f"Wallet: <b>{result['wallet_type']}</b>\n"
        f"Number: <code>{result['wallet_number']}</code>"
        f"{suspicious_text}",
        withdrawal_keyboard(withdrawal_id),
    )

    return {
        "success": True,
        "withdrawal_id": withdrawal_id,
        "message": (
            f"Withdrawal #{withdrawal_id} submitted "
            "successfully and is pending admin review."
        ),
    }


# ============================================================
# TELEGRAM WEBHOOK
# ============================================================

@app.post("/webhook")
async def webhook(request: Request):
    if WEBHOOK_SECRET:
        received_secret = request.headers.get(
            "X-Telegram-Bot-Api-Secret-Token",
            "",
        )

        if not hmac.compare_digest(
            received_secret,
            WEBHOOK_SECRET,
        ):
            return JSONResponse(
                {"ok": False},
                status_code=403,
            )

    try:
        update = await request.json()
    except Exception:
        return {"ok": True}

    await handle_update(update)

    return {"ok": True}


# ============================================================
# STARTUP
# ============================================================

@app.on_event("startup")
async def startup():
    init_db()

    if not BOT_TOKEN:
        print(
            "WARNING: BOT_TOKEN is missing. "
            "The web server can start, but Telegram features "
            "will not work."
        )
        return

    await configure_bot()

    webhook_data = {
        "url": WEBHOOK_URL,
        "allowed_updates": [
            "message",
            "callback_query",
        ],
    }

    if WEBHOOK_SECRET:
        webhook_data["secret_token"] = WEBHOOK_SECRET

    result = await telegram_request(
        "setWebhook",
        webhook_data,
    )

    print(
        "Falcon World webhook:",
        result,
    )
