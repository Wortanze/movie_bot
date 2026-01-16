import os
import re
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_API_KEY)

FRAMES_DIR = "frames"

if not os.path.exists(FRAMES_DIR):
    os.makedirs(FRAMES_DIR)


def clear_frames():
    for f in os.listdir(FRAMES_DIR):
        try:
            os.remove(os.path.join(FRAMES_DIR, f))
        except:
            pass


def extract_youtube_id(url: str) -> str | None:
    patterns = [
        r"v=([a-zA-Z0-9_-]{11})",
        r"youtu\.be/([a-zA-Z0-9_-]{11})",
        r"shorts/([a-zA-Z0-9_-]{11})",
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None


def get_youtube_cdn_frames(video_id: str) -> list[str]:
    base = f"https://img.youtube.com/vi/{video_id}"
    return [
        f"{base}/hqdefault.jpg",
        f"{base}/mqdefault.jpg",
        f"{base}/sddefault.jpg",
        f"{base}/maxresdefault.jpg",
    ]


def download_cdn_frames(urls: list[str]) -> list[str]:
    clear_frames()
    paths = []

    for i, url in enumerate(urls, 1):
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200 and len(r.content) > 10_000:
                path = os.path.join(FRAMES_DIR, f"frame_{i:02d}.jpg")
                with open(path, "wb") as f:
                    f.write(r.content)
                paths.append(path)
        except:
            pass

    return paths


def get_movie_description(frame_paths):
    try:
        model = genai.GenerativeModel("gemini-2.5-flash")

        prompt = """
Это кадры из фильма, сериала, аниме, мультфильма или видео.
Назови ТОЛЬКО:

Название: ...
Год: ...
Рейтинг IMDb: ... или -
Описание: 1–2 предложения без спойлеров

Если не уверен на 90%+ — напиши:
Не удалось точно определить

Ничего лишнего не добавляй.
"""

        content = [prompt]
        for frame in frame_paths:
            with open(frame, "rb") as img:
                content.append({
                    "mime_type": "image/jpeg",
                    "data": img.read()
                })

        response = model.generate_content(content)
        return response.text.strip() or "Не удалось точно определить"

    except Exception as e:
        return f"Ошибка AI: {str(e)}"


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    if not url or "http" not in url.lower():
        return

    msg = await update.message.reply_text("🔎 Анализирую видео по кадрам... ✨")

    try:
        video_id = extract_youtube_id(url)
        if not video_id:
            await msg.edit_text("❌ Сейчас поддерживается только YouTube / Shorts")
            return

        cdn_urls = get_youtube_cdn_frames(video_id)
        frame_files = download_cdn_frames(cdn_urls)

        if len(frame_files) < 2:
            await msg.edit_text("❌ Не удалось получить кадры с YouTube CDN")
            return

        answer = get_movie_description(frame_files)

        if "Не удалось точно определить" in answer:
            final_text = (
                "🤔 Загадочный ролик...\n"
                "Не смог определить с высокой уверенностью.\n\n"
                f"{answer}"
            )
        else:
            final_text = f"🎥 Найдено! ✨\n\n{answer}"

        await update.message.reply_text(final_text)
        await msg.delete()

    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {str(e)}")

    finally:
        clear_frames()


if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    print("🚀 БОТ ЗАПУЩЕН (CDN + GEMINI VISION)")
    app.run_polling()
