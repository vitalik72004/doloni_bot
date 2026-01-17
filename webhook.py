import os
import asyncio
from aiohttp import web
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBHOOK_PATH = "/webhook"
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "change-me")

# Render автоматично дає hostname в env
RENDER_HOST = os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip()
WEBHOOK_URL = f"https://{RENDER_HOST}{WEBHOOK_PATH}"

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# ✅ тут підключаєш свій dp з bot.py
# Найпростіше: винеси всі хендлери в окремий файл handlers.py і імпортуй тут
# Але можна і так:
import bot as doloni_bot
dp = doloni_bot.dp  # беремо твій dispatcher

async def on_startup(app: web.Application):
    await bot.set_webhook(WEBHOOK_URL, secret_token=WEBHOOK_SECRET)

async def on_shutdown(app: web.Application):
    await bot.delete_webhook()

async def handle_webhook(request: web.Request):
    # перевірка секрету (захист)
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if secret != WEBHOOK_SECRET:
        return web.Response(status=403, text="Forbidden")

    update = await request.json()
    await dp.feed_raw_update(bot, update)
    return web.Response(text="ok")

app = web.Application()
app.router.add_post(WEBHOOK_PATH, handle_webhook)
app.on_startup.append(on_startup)
app.on_shutdown.append(on_shutdown)

if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    web.run_app(app, host="0.0.0.0", port=port)
