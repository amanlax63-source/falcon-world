import os
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

app = FastAPI()

# ==============================
# CONFIGURATION
# ==============================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = os.getenv("ADMIN_ID", "").strip()

BOT_USERNAME = "FalconWorld_Bot"

WEBHOOK_URL = "https://falcon-world.onrender.com/webhook"
MINI_APP_URL = "https://falcon-world.onrender.com/app"

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"


# ==============================
# TELEGRAM API HELPER
# ==============================

async def telegram_request(method: str, data: dict):
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            f"{TELEGRAM_API}/{method}",
            json=data
        )

        try:
            return response.json()
        except Exception:
            return {
                "ok": False,
                "description": response.text
            }


# ==============================
# SEND MESSAGE
# ==============================

async def send_message(chat_id: int, text: str):
    return await telegram_request(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown"
        }
    )


# ==============================
# MENU BUTTON
# ==============================

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


# ==============================
# STARTUP
# ==============================

@app.on_event("startup")
async def startup():

    if not BOT_TOKEN:
        print("ERROR: BOT_TOKEN is missing.")
        return

    # Set webhook
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

    # Set menu button
    menu_result = await set_menu_button()

    print("Menu button setup:", menu_result)


# ==============================
# HOME
# ==============================

@app.get("/")
async def home():
    return {
        "status": "online",
        "bot": "Falcon World"
    }


# ==============================
# HEALTH CHECK
# ==============================

@app.get("/health")
async def health():
    return {
        "status": "healthy"
    }


# ==============================
# MINI APP
# ==============================

@app.get("/app", response_class=HTMLResponse)
async def mini_app():

    return """
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

        /* =========================
           RESET
        ========================= */

        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }


        /* =========================
           BODY
        ========================= */

        body {

            width: 100%;
            min-height: 100vh;

            overflow-x: hidden;

            background:
                radial-gradient(
                    circle at 50% -10%,
                    #234f80 0%,
                    #102944 25%,
                    #071321 55%,
                    #030811 100%
                );

            color: #ffffff;

            font-family:
                -apple-system,
                BlinkMacSystemFont,
                "Segoe UI",
                Roboto,
                Arial,
                sans-serif;
        }


        /* =========================
           APP
        ========================= */

        .app {

            width: 100%;
            max-width: 480px;

            min-height: 100vh;

            margin: 0 auto;

            position: relative;

            overflow: hidden;
        }


        /* =========================
           BACKGROUND LIGHT
        ========================= */

        .light {

            position: fixed;

            width: 260px;
            height: 260px;

            border-radius: 50%;

            background:
                radial-gradient(
                    circle,
                    rgba(64, 166, 255, 0.20),
                    transparent 70%
                );

            top: -120px;
            left: 50%;

            transform: translateX(-50%);

            pointer-events: none;
        }


        /* =========================
           LOADING SCREEN
        ========================= */

        #loadingScreen {

            position: fixed;

            inset: 0;

            z-index: 9999;

            display: flex;

            justify-content: center;
            align-items: center;

            background:
                radial-gradient(
                    circle at center,
                    #15375b 0%,
                    #081625 45%,
                    #03070d 100%
                );

            transition:
                opacity 0.7s ease,
                visibility 0.7s ease;
        }


        #loadingScreen.hide {

            opacity: 0;

            visibility: hidden;
        }


        .loaderContent {

            width: 100%;

            text-align: center;

            padding: 30px;
        }


        /* =========================
           FALCON LOGO
        ========================= */

        .logoWrap {

            width: 125px;
            height: 125px;

            margin: 0 auto 25px;

            position: relative;

            display: flex;

            align-items: center;
            justify-content: center;

            border-radius: 50%;

            background:
                radial-gradient(
                    circle,
                    rgba(47, 147, 255, 0.16),
                    rgba(47, 147, 255, 0.03) 65%,
                    transparent 70%
                );

            box-shadow:
                0 0 35px rgba(44, 157, 255, 0.25);
        }


        .logoRing {

            position: absolute;

            inset: 0;

            border-radius: 50%;

            border: 2px solid rgba(93, 190, 255, 0.18);

            border-top-color: #4db7ff;
            border-right-color: #4db7ff;

            animation:
                spin 1.8s linear infinite;
        }


        .logoRing2 {

            position: absolute;

            inset: 9px;

            border-radius: 50%;

            border: 1px solid rgba(255,255,255,0.10);

            animation:
                spinReverse 3s linear infinite;
        }


        .eagle {

            font-size: 65px;

            line-height: 1;

            filter:
                drop-shadow(
                    0 0 14px
                    rgba(74, 178, 255, 0.45)
                );

            animation:
                eagleFloat 2s ease-in-out infinite;
        }


        /* =========================
           BRAND
        ========================= */

        .brand {

            font-size: 30px;

            font-weight: 900;

            letter-spacing: 4px;

            margin-bottom: 9px;

            text-shadow:
                0 0 18px
                rgba(84, 183, 255, 0.25);
        }


        .tagline {

            color: #9eb0c5;

            font-size: 14px;

            letter-spacing: 0.8px;
        }


        /* =========================
           LOADING
        ========================= */

        .loadingArea {

            margin-top: 42px;
        }


        .loadingText {

            color: #b9c7d7;

            font-size: 13px;

            margin-bottom: 12px;
        }


        .dots span {

            display: inline-block;

            width: 6px;
            height: 6px;

            margin: 0 3px;

            border-radius: 50%;

            background: #53baff;

            opacity: 0.25;

            animation:
                dotPulse 1.2s infinite;
        }


        .dots span:nth-child(2) {
            animation-delay: 0.2s;
        }


        .dots span:nth-child(3) {
            animation-delay: 0.4s;
        }


        /* =========================
           MAIN SCREEN
        ========================= */

        #mainScreen {

            min-height: 100vh;

            padding: 24px 18px 30px;

            opacity: 0;

            transform: translateY(12px);

            animation:
                mainAppear 0.8s ease forwards;

            animation-delay: 0.2s;
        }


        .topBar {

            display: flex;

            align-items: center;

            justify-content: space-between;

            padding-top: 8px;
        }


        .miniBrand {

            display: flex;

            align-items: center;

            gap: 10px;
        }


        .miniLogo {

            width: 43px;
            height: 43px;

            display: flex;

            align-items: center;
            justify-content: center;

            border-radius: 14px;

            background:
                linear-gradient(
                    145deg,
                    rgba(66, 169, 255, 0.25),
                    rgba(66, 169, 255, 0.06)
                );

            border:
                1px solid
                rgba(106, 194, 255, 0.16);

            font-size: 24px;
        }


        .miniName {

            font-size: 16px;

            font-weight: 800;

            letter-spacing: 1px;
        }


        .miniStatus {

            font-size: 11px;

            color: #59df9a;

            margin-top: 3px;
        }


        /* =========================
           HERO CARD
        ========================= */

        .hero {

            margin-top: 25px;

            padding: 25px 21px;

            border-radius: 24px;

            background:
                linear-gradient(
                    145deg,
                    rgba(38, 88, 139, 0.28),
                    rgba(10, 25, 42, 0.58)
                );

            border:
                1px solid
                rgba(112, 190, 255, 0.12);

            box-shadow:
                0 20px 60px
                rgba(0, 0, 0, 0.25);

            position: relative;

            overflow: hidden;
        }


        .hero::after {

            content: "";

            position: absolute;

            width: 160px;
            height: 160px;

            right: -70px;
            top: -70px;

            border-radius: 50%;

            background:
                radial-gradient(
                    circle,
                    rgba(60, 173, 255, 0.16),
                    transparent 70%
                );
        }


        .heroSmall {

            color: #7fcaff;

            font-size: 12px;

            font-weight: 700;

            letter-spacing: 1.5px;

            margin-bottom: 9px;
        }


        .heroTitle {

            font-size: 25px;

            font-weight: 850;

            line-height: 1.25;
        }


        .heroText {

            margin-top: 9px;

            color: #9eafc2;

            font-size: 13px;

            line-height: 1.6;
        }


        /* =========================
           QUICK CARDS
        ========================= */

        .sectionTitle {

            margin-top: 26px;

            margin-bottom: 12px;

            font-size: 14px;

            font-weight: 750;

            color: #dce8f4;
        }


        .grid {

            display: grid;

            grid-template-columns:
                repeat(2, 1fr);

            gap: 12px;
        }


        .feature {

            padding: 18px;

            min-height: 105px;

            border-radius: 19px;

            background:
                rgba(255,255,255,0.045);

            border:
                1px solid
                rgba(255,255,255,0.07);

            transition:
                transform 0.2s ease,
                background 0.2s ease;
        }


        .feature:active {

            transform: scale(0.97);

            background:
                rgba(255,255,255,0.08);
        }


        .featureIcon {

            font-size: 25px;

            margin-bottom: 10px;
        }


        .featureTitle {

            font-size: 14px;

            font-weight: 750;
        }


        .featureText {

            margin-top: 5px;

            color: #8192a5;

            font-size: 11px;
        }


        /* =========================
           FOOTER
        ========================= */

        .footer {

            text-align: center;

            margin-top: 30px;

            color: #526275;

            font-size: 11px;

            letter-spacing: 0.5px;
        }


        /* =========================
           ANIMATIONS
        ========================= */

        @keyframes spin {

            from {
                transform: rotate(0deg);
            }

            to {
                transform: rotate(360deg);
            }
        }


        @keyframes spinReverse {

            from {
                transform: rotate(360deg);
            }

            to {
                transform: rotate(0deg);
            }
        }


        @keyframes eagleFloat {

            0%, 100% {
                transform: translateY(0);
            }

            50% {
                transform: translateY(-7px);
            }
        }


        @keyframes dotPulse {

            0%, 100% {
                opacity: 0.2;
                transform: scale(0.8);
            }

            50% {
                opacity: 1;
                transform: scale(1.2);
            }
        }


        @keyframes mainAppear {

            from {
                opacity: 0;
                transform: translateY(12px);
            }

            to {
                opacity: 1;
                transform: translateY(0);
            }
        }


        /* =========================
           SMALL PHONES
        ========================= */

        @media (max-width: 360px) {

            .brand {
                font-size: 26px;
            }

            .heroTitle {
                font-size: 22px;
            }

            .feature {
                padding: 15px;
            }
        }

    </style>

</head>


<body>


    <!-- =========================
         LOADING SCREEN
    ========================== -->

    <div id="loadingScreen">

        <div class="loaderContent">

            <div class="logoWrap">

                <div class="logoRing"></div>

                <div class="logoRing2"></div>

                <div class="eagle">
                    🦅
                </div>

            </div>


            <div class="brand">
                FALCON WORLD
            </div>


            <div class="tagline">
                Earn. Refer. Grow.
            </div>


            <div class="loadingArea">

                <div class="loadingText">
                    Preparing your experience
                </div>

                <div class="dots">

                    <span></span>
                    <span></span>
                    <span></span>

                </div>

            </div>

        </div>

    </div>


    <!-- =========================
         MAIN APP
    ========================== -->

    <main id="mainScreen">

        <div class="light"></div>


        <!-- TOP BAR -->

        <div class="topBar">

            <div class="miniBrand">

                <div class="miniLogo">
                    🦅
                </div>

                <div>

                    <div class="miniName">
                        FALCON WORLD
                    </div>

                    <div class="miniStatus">
                        ● Online
                    </div>

                </div>

            </div>

        </div>


        <!-- HERO -->

        <section class="hero">

            <div class="heroSmall">
                WELCOME
            </div>

            <div class="heroTitle">
                Your digital earning
                journey starts here.
            </div>

            <div class="heroText">
                Complete tasks, earn rewards,
                invite friends and discover
                new opportunities.
            </div>

        </section>


        <!-- FEATURES -->

        <div class="sectionTitle">
            Explore Falcon World
        </div>


        <div class="grid">


            <div class="feature">

                <div class="featureIcon">
                    💰
                </div>

                <div class="featureTitle">
                    Earn
                </div>

                <div class="featureText">
                    Complete tasks and earn.
                </div>

            </div>


            <div class="feature">

                <div class="featureIcon">
                    🎁
                </div>

                <div class="featureTitle">
                    Daily Bonus
                </div>

                <div class="featureText">
                    Claim daily rewards.
                </div>

            </div>


            <div class="feature">

                <div class="featureIcon">
                    👥
                </div>

                <div class="featureTitle">
                    Referral
                </div>

                <div class="featureText">
                    Invite friends and earn.
                </div>

            </div>


            <div class="feature">

                <div class="featureIcon">
                    🚀
                </div>

                <div class="featureTitle">
                    Opportunities
                </div>

                <div class="featureText">
                    Discover new opportunities.
                </div>

            </div>


        </div>


        <div class="footer">
            Falcon World • Earn. Refer. Grow.
        </div>


    </main>


    <!-- =========================
         LOADING SCRIPT
    ========================== -->

    <script>

        window.addEventListener(
            "load",
            function() {

                setTimeout(
                    function() {

                        const loader =
                            document.getElementById(
                                "loadingScreen"
                            );

                        if (loader) {
                            loader.classList.add("hide");
                        }

                    },
                    1800
                );

            }
        );

    </script>


</body>

</html>
    """
    

# ==============================
# WEBHOOK
# ==============================

@app.post("/webhook")
async def webhook(request: Request):

    update = await request.json()

    message = update.get("message")

    if not message:
        return {"ok": True}

    chat = message.get("chat", {})

    chat_id = chat.get("id")

    text = message.get("text", "").strip()


    # ==========================
    # START COMMAND
    # ==========================

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

        await send_message(
            chat_id,
            welcome_message
        )


    return {"ok": True}
