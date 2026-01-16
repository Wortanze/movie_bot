import os
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
import google.generativeai as genai
from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

genai.configure(api_key=GOOGLE_API_KEY)

FRAMES_DIR = "frames"
os.makedirs(FRAMES_DIR, exist_ok=True)


def clear_frames():
    for f in os.listdir(FRAMES_DIR):
        try:
            os.remove(os.path.join(FRAMES_DIR, f))
        except:
            pass


async def get_frames_with_playwright(url, positions=[0.1, 0.2, 0.4, 0.6, 0.8]):
    clear_frames()
    frame_paths = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(url, timeout=60_000)
        await page.wait_for_timeout(3000) 

        video = await page.query_selector("video")
        if not video:
            await browser.close()
            return []

        duration = await page.eval_on_selector("video", "v => v.duration") or 60

        for i, p in enumerate(positions, 1):
            t = duration * p
            await page.eval_on_selector("video", f"v => v.currentTime = {t}")
            await page.wait_for_timeout(1000)
            frame_path = os.path.join(FRAMES_DIR, f"frame_{i:02d}.jpg")
            await video.screenshot(path=frame_path)
            frame_paths.append(frame_path)

        await browser.close()
    return frame_paths


def guess_movie(frame_paths):
    model = genai.GenerativeModel("gemini-2.5-flash")
    prompt = """
Перед тобой несколько кадров из ОДНОГО видео.
Определи, из какого фильма, сериала, аниме или мультфильма они взяты.
Проанализируй:
- персонажей, лица, одежду
- визуальный стиль, цветокор
- эпоху, технологии, оружие
- жанр и атмосферу
- возможных актёров
Отвечай ТОЛЬКО если уверен минимум на 90%.
Формат строго:
Название: ...
Год: ...
Рейтинг IMDb: ...
Описание: 1–2 предложения без спойлеров
Если уверенность ниже 90% — напиши:
Не удалось точно определить
"""
    content = [prompt]
    for frame in frame_paths:
        with open(frame, "rb") as img:
            content.append({"mime_type": "image/jpeg", "data": img.read()})

    response = model.generate_content(content)
    return response.text.strip()


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    if not url.lower().startswith(("http://", "https://")):
        return

    msg = await update.message.reply_text("🔎 Анализирую видео через Playwright...")

    try:
        frames = await get_frames_with_playwright(url)
        if len(frames) < 2:
            await msg.edit_text("❌ Не удалось получить кадры")
            return

        guess = guess_movie(frames)

        if "Не удалось точно определить" in guess:
            await msg.edit_text("🤔 Не удалось уверенно определить фильм")
        else:
            await msg.edit_text(f"🎥 Найдено! ✨\n\n{guess}")

    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {e}")
    finally:
        clear_frames()


if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    print(
        "🚀 БОТ ЗАПУЩЕН (Playwright + GEMINI PRO MODE) для YouTube, TikTok и Instagram Reels"
    )
    app.run_polling()
