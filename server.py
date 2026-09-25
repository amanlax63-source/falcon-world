import os
import httpx

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="Falcon World")

# =========================
# CONFIG
# =========================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = os.getenv("ADMIN_ID", "").strip()

BOT_USERNAME = "FalconWorld_Bot"

WEBHOOK_URL = "https://falcon-world.onrender.com/webhook"

# Mini App URL
MINI_APP_URL = "https://falcon-world.onrender.com/app"

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"


# =========================
# TELEGRAM API
# =========================

async def telegram_request(
    method: str,
    payload: dict | None = None,
):
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing.")

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            f"{TELEGRAM_API}/{method}",
            json=payload or {},
        )

        try:
            return response.json()
        except Exception:
            return {
                "ok": False,
                "description": response.text,
                "http_status": response.status_code,
            }


# =========================
# SEND MESSAGE
# =========================

async def send_message(
    chat_id: int,
    text: str,
    reply_markup: dict | None = None,
):
    payload = {
        "chat_id": chat_id,
        "text": text,
    }

    if reply_markup:
        payload["reply_markup"] = reply_markup

    return await telegram_request(
        "sendMessage",
        payload,
    )


# =========================
# STARTUP
# =========================

@app.on_event("startup")
async def startup():

    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN is missing.")
        return

    result = await telegram_request(
        "setWebhook",
        {
            "url": WEBHOOK_URL,
            "allowed_updates": [
                "message",
                "callback_query",
            ],
        },
    )

    print("Webhook setup:", result)


# =========================
# HEALTH
# =========================

@app.get("/health")
async def health():

    return {
        "status": "ok",
        "app": "Falcon World",
        "bot": BOT_USERNAME,
        "mini_app": MINI_APP_URL,
        "database": "not_started",
    }


# =========================
# ROOT
# =========================

@app.get("/")
async def root():

    return {
        "status": "ok",
        "app": "Falcon World",
        "message": "Falcon World is running.",
    }


# =========================
# MINI APP TEST PAGE
# =========================

@app.get("/app")
async def mini_app():

    html = """
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

    <style>
        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            min-height: 100vh;
            font-family: Arial, sans-serif;
            background: #07111f;
            color: #ffffff;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 24px;
        }

        .container {
            width: 100%;
            max-width: 420px;
            text-align: center;
        }

        .logo {
            font-size: 64px;
            margin-bottom: 18px;
        }

        h1 {
            font-size: 30px;
            letter-spacing: 2px;
            margin-bottom: 12px;
        }

        .subtitle {
            color: #9eacbd;
            font-size: 15px;
            line-height: 1.6;
            margin-bottom: 30px;
        }

        .status {
            padding: 16px;
            border-radius: 16px;
            background: #101d2e;
            border: 1px solid #1e3148;
            margin-bottom: 18px;
        }

        .status-title {
            font-size: 13px;
            color: #8fa2b8;
            margin-bottom: 7px;
        }

        .status-value {
            font-size: 18px;
            font-weight: bold;
        }

        .open-button {
            width: 100%;
            border: none;
            border-radius: 16px;
            padding: 16px;
            font-size: 16px;
            font-weight: bold;
            background: #ffffff;
            color: #07111f;
        }
    </style>
</head>

<body>

<div class="container">

    <div class="logo">🦅</div>

    <h1>FALCON WORLD</h1>

    <div class="subtitle">
        Earn. Refer. Withdraw.<br>
        Your journey starts here.
    </div>

    <div class="status">
        <div class="status-title">
            PLATFORM STATUS
        </div>

        <div class="status-value">
            Connected
        </div>
    </div>

    <button class="open-button">
        Falcon World
    </button>

</div>

</body>
</html>
"""

    from fastapi.responses import HTMLResponse

    return HTMLResponse(content=html)


# =========================
# TELEGRAM WEBHOOK
# =========================

@app.post("/webhook")
async def webhook(request: Request):

    try:
        update = await request.json()

    except Exception:
        return JSONResponse(
            {
                "ok": False,
                "error": "Invalid JSON",
            },
            status_code=400,
        )

    # =========================
    # MESSAGE
    # =========================

    if "message" in update:

        message = update["message"]

        chat = message.get("chat", {})
        user = message.get("from", {})

        chat_id = chat.get("id")
        text = message.get("text", "")

        if not chat_id:
            return {"ok": True}

        # =========================
        # START
        # =========================

        if text.startswith("/start"):

            keyboard = {
                "inline_keyboard": [
                    [
                        {
                            "text": "🚀 Open Falcon World",
                            "web_app": {
                                "url": MINI_APP_URL
                            },
                        }
                    ]
                ]
            }

            await send_message(
                chat_id,
                (
                    "🦅 FALCON WORLD\n\n"
                    "Welcome to Falcon World.\n\n"
                    "Earn. Refer. Withdraw.\n\n"
                    "Your journey starts here."
                ),
                keyboard,
            )

        return {"ok": True}

    return {"ok": True}
