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

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

CHANNELS = [
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


# =========================
# TELEGRAM HELPERS
# =========================

async def telegram_request(method: str, payload: dict | None = None):
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


async def send_message(chat_id: int, text: str, reply_markup: dict | None = None):
    payload = {
        "chat_id": chat_id,
        "text": text,
    }

    if reply_markup:
        payload["reply_markup"] = reply_markup

    return await telegram_request("sendMessage", payload)


async def answer_callback(callback_id: str, text: str):
    return await telegram_request(
        "answerCallbackQuery",
        {
            "callback_query_id": callback_id,
            "text": text,
        },
    )


# =========================
# CHANNEL VERIFICATION
# =========================

async def is_user_member(channel_username: str, user_id: int) -> bool:
    result = await telegram_request(
        "getChatMember",
        {
            "chat_id": channel_username,
            "user_id": user_id,
        },
    )

    if not result.get("ok"):
        # If Telegram cannot check the channel, treat it as not verified.
        return False

    member = result.get("result", {})
    status = member.get("status")

    return status in {
        "creator",
        "administrator",
        "member",
        "restricted",
    }


async def get_unjoined_channels(user_id: int):
    unjoined = []

    for channel in CHANNELS:
        joined = await is_user_member(
            channel["username"],
            user_id,
        )

        if not joined:
            unjoined.append(channel)

    return unjoined


# =========================
# JOIN MESSAGE
# =========================

async def send_channel_verification(chat_id: int, user_id: int):
    unjoined = await get_unjoined_channels(user_id)

    # Everything is joined.
    if not unjoined:
        await send_message(
            chat_id,
            "🎉 ሁሉንም Required Channels በትክክል ተቀላቅለዋል!\n\n"
            "✅ Verification complete.\n\n"
            "🚀 Falcon World በቅርቡ ይከፈታል።",
        )
        return

    keyboard = []

    for channel in unjoined:
        keyboard.append(
            [
                {
                    "text": f"📢 Join {channel['name']}",
                    "url": channel["url"],
                }
            ]
        )

    keyboard.append(
        [
            {
                "text": "✅ Verify Membership",
                "callback_data": "verify_membership",
            }
        ]
    )

    text = (
        "🦅 FALCON WORLD\n\n"
        "👋 እንኳን ደህና መጡ!\n\n"
        "Falcon World ለመጠቀም ከታች ያሉትን "
        "Required Channels ይቀላቀሉ።\n\n"
        "ከተቀላቀሉ በኋላ **Verify Membership** ይጫኑ።\n\n"
        f"📌 Remaining: {len(unjoined)}"
    )

    await send_message(
        chat_id,
        text,
        {
            "inline_keyboard": keyboard,
        },
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
# HEALTH CHECK
# =========================

@app.get("/health")
async def health():
    bot_status = "configured" if BOT_TOKEN else "missing"

    return {
        "status": "ok",
        "app": "Falcon World",
        "bot": BOT_USERNAME,
        "database": "not_started",
        "bot_token": bot_status,
    }


# =========================
# ROOT
# =========================

@app.get("/")
async def root():
    return {
        "status": "ok",
        "app": "Falcon World",
        "message": "Falcon World Bot Server is running.",
    }


# =========================
# TELEGRAM WEBHOOK
# =========================

@app.post("/webhook")
async def webhook(request: Request):
    try:
        update = await request.json()
    except Exception:
        return JSONResponse(
            {"ok": False, "error": "Invalid JSON"},
            status_code=400,
        )

    # -------------------------
    # Normal message
    # -------------------------

    if "message" in update:
        message = update["message"]

        chat = message.get("chat", {})
        user = message.get("from", {})

        chat_id = chat.get("id")
        user_id = user.get("id")
        text = message.get("text", "")

        if not chat_id or not user_id:
            return {"ok": True}

        if text.startswith("/start"):
            await send_channel_verification(
                chat_id,
                user_id,
            )

        return {"ok": True}

    # -------------------------
    # Callback query
    # -------------------------

    if "callback_query" in update:
        callback = update["callback_query"]

        callback_id = callback.get("id")
        callback_data = callback.get("data")

        user = callback.get("from", {})
        user_id = user.get("id")

        message = callback.get("message", {})
        chat = message.get("chat", {})
        chat_id = chat.get("id")

        if callback_data == "verify_membership":
            unjoined = await get_unjoined_channels(user_id)

            if not unjoined:
                await answer_callback(
                    callback_id,
                    "✅ Verification complete!",
                )

                await send_message(
                    chat_id,
                    "🎉 **Verification Complete!**\n\n"
                    "ሁሉንም Required Channels ተቀላቅለዋል።\n\n"
                    "🦅 Falcon World ለመጠቀም ዝግጁ ነው።",
                )

            else:
                await answer_callback(
                    callback_id,
                    f"❌ {len(unjoined)} channel(s) remaining.",
                )

                await send_channel_verification(
                    chat_id,
                    user_id,
                )

        return {"ok": True}

    return {"ok": True}
