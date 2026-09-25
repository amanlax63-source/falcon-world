import os
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

app = FastAPI()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = os.getenv("ADMIN_ID", "").strip()

BOT_USERNAME = "FalconWorld_Bot"
WEBHOOK_URL = "https://falcon-world.onrender.com/webhook"
MINI_APP_URL = "https://falcon-world.onrender.com/app"

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"


async def telegram_request(method: str, data: dict):
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"{TELEGRAM_API}/{method}",
            json=data
        )
        return response.json()


async def send_message(chat_id: int, text: str):
    return await telegram_request(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }
    )


async def set_menu_button():
    return await telegram_request(
        "setChatMenuButton",
        {
            "menu_button": {
                "type": "web_app",
                "text": "🚀 Open Falcon World",
                "web_app": {
                    "url": MINI_APP_URL
                }
            }
        }
    )


@app.on_event("startup")
async def startup():
    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN is missing.")
        return

    webhook_result = await telegram_request(
        "setWebhook",
        {
            "url": WEBHOOK_URL,
            "allowed_updates": [
                "message"
            ]
        }
    )

    print("Webhook setup:", webhook_result)

    menu_result = await set_menu_button()

    print("Menu button setup:", menu_result)


@app.get("/")
async def home():
    return {
        "status": "online",
        "bot": "Falcon World"
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy"
    }


@app.get("/app", response_class=HTMLResponse)
async def mini_app():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <meta name="viewport"
              content="width=device-width, initial-scale=1.0">
        <title>Falcon World</title>

        <style>
            body {
                margin: 0;
                min-height: 100vh;
                background: #07111f;
                color: white;
                font-family: Arial, sans-serif;
                display: flex;
                justify-content: center;
                align-items: center;
                text-align: center;
            }

            .container {
                padding: 30px;
            }

            .logo {
                font-size: 70px;
            }

            h1 {
                margin: 10px 0;
                font-size: 30px;
                letter-spacing: 2px;
            }

            p {
                color: #aeb8c5;
                font-size: 16px;
            }

            .status {
                margin-top: 25px;
                padding: 15px 20px;
                border-radius: 15px;
                background: #101f33;
            }
        </style>
    </head>

    <body>
        <div class="container">

            <div class="logo">🦅</div>

            <h1>FALCON WORLD</h1>

            <p>
                Earn. Refer. Grow.
            </p>

            <div class="status">
                🚀 Mini App Connected
            </div>

        </div>
    </body>
    </html>
    """


@app.post("/webhook")
async def webhook(request: Request):
    update = await request.json()

    message = update.get("message")

    if not message:
        return {"ok": True}

    chat = message.get("chat", {})
    chat_id = chat.get("id")

    text = message.get("text", "").strip()

    if text.startswith("/start"):
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

        await send_message(chat_id, welcome_message)

    return {"ok": True}
