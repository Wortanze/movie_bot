import os
import subprocess
import json
import base64
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_API_KEY)

VIDEOS_DIR = "videos"
FRAMES_DIR = "frames"
VIDEO_BASE = os.path.join(VIDEOS_DIR, "video_temp")

for directory in [VIDEOS_DIR, FRAMES_DIR]:
    if not os.path.exists(directory):
        os.makedirs(directory)


def clear_frames():
    for f in os.listdir(FRAMES_DIR):
        try:
            os.remove(os.path.join(FRAMES_DIR, f))
        except:
            pass


def get_video_duration(video_path):
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                video_path,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(result.stdout)
        return float(data["format"]["duration"])
    except Exception as e:
        print(f"[ERROR] Duration error: {e}")
        return 0


def get_movie_description(frame_paths):
    try:
        model = genai.GenerativeModel("gemini-2.5-flash")

        prompt = """
Это кадр из фильма, сериала, аниме, мультфильма или любого видео-контента. Назови только:
- Название (на русском или английском, оригинальное предпочтительнее)
- Год выпуска
- IMDb рейтинг (если знаешь точно, иначе -)
- Краткое описание (1–2 предложения, без спойлеров, чтобы заинтересовать: подчеркни атмосферу, жанр, уникальность)

Формат ответа строго:
Название: [название]
Год: [год]
Рейтинг IMDb: [число или -]
Описание: [краткое описание]

Если не уверен на 90%+ — пиши "Не удалось точно определить".
Не добавляй ничего лишнего!
"""

        content = [prompt]
        for frame in frame_paths:
            with open(frame, "rb") as img_file:
                content.append({"mime_type": "image/jpeg", "data": img_file.read()})

        response = model.generate_content(content)
        return response.text.strip() or "Не удалось определить"

    except Exception as e:
        return f"Ошибка: {str(e)}"


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    if not url or "http" not in url.lower():
        return

    msg = await update.message.reply_text("🔎 Качаю видео и пытаюсь угадать... ✨")

    clear_frames()
    downloaded_file = None

    try:
        print("Проверяю куки:", os.path.exists("/cookies.txt"))
        subprocess.run(
            [
                "yt-dlp",
                "--cookies",
                "cookies.txt",
                "-o",
                f"{VIDEO_BASE}.%(ext)s",
                "--force-overwrites",
                "--merge-output-format",
                "mp4",
                "--retries",
                "10",
                url,
            ],
            check=True,
            capture_output=True,
        )

        possible_files = [
            f"{VIDEO_BASE}.mp4",
            f"{VIDEO_BASE}.webm",
            f"{VIDEO_BASE}.mkv",
        ]
        for candidate in possible_files:
            if os.path.exists(candidate):
                downloaded_file = candidate
                break

        if not downloaded_file:
            raise FileNotFoundError("Видео не найдено после скачивания")

        duration = get_video_duration(downloaded_file)
        if duration <= 0:
            raise ValueError("Не удалось определить длительность видео")

        positions = [10, 30, 50, 70, 90]
        frame_files = []

        for i, percent in enumerate(positions, 1):
            seek_time = (percent / 100.0) * duration
            output_frame = os.path.join(FRAMES_DIR, f"frame_{i:02d}.jpg")

            cmd = [
                "ffmpeg",
                "-y",
                "-ss",
                str(seek_time),
                "-i",
                downloaded_file,
                "-frames:v",
                "1",
                "-q:v",
                "2",
                output_frame,
            ]

            try:
                subprocess.run(cmd, check=True, capture_output=True)
                if os.path.exists(output_frame):
                    frame_files.append(output_frame)
            except Exception as sub_e:
                print(f"[WARNING] Кадр {percent}%: {sub_e}")

        if len(frame_files) < 3:
            for extra in [0.0, duration - 1]:
                if extra > 0:
                    output_frame = os.path.join(
                        FRAMES_DIR, f"frame_extra_{len(frame_files)+1:02d}.jpg"
                    )
                    cmd = [
                        "ffmpeg",
                        "-y",
                        "-ss",
                        str(extra),
                        "-i",
                        downloaded_file,
                        "-frames:v",
                        "1",
                        "-q:v",
                        "2",
                        output_frame,
                    ]
                    try:
                        subprocess.run(cmd, check=True, capture_output=True)
                        if os.path.exists(output_frame):
                            frame_files.append(output_frame)
                    except:
                        pass

        if not frame_files:
            raise FileNotFoundError("Ни один кадр не извлёкся")

        answer = get_movie_description(frame_files)

        if "Не удалось точно определить" in answer:
            final_text = f"🤔 Хм, загадочное видео! Не смог уверенно определить... Попробуй другой ролик! 🎬\n\n{answer}"
        else:
            final_text = f"🎥 Успешно найдено! ✨\n\n{answer}\n\nЗахватывающее зрелище, не так ли? 😎"

        await update.message.reply_text(final_text)
        await msg.delete()

    except subprocess.CalledProcessError as e:
        error_msg = (
            f"❌ Ошибка yt-dlp/ffmpeg: {e.stderr.decode() if e.stderr else str(e)}"
        )
        await msg.edit_text(error_msg)
    except Exception as e:
        await msg.edit_text(f"❌ Критическая ошибка: {str(e)}")
    finally:
        if downloaded_file and os.path.exists(downloaded_file):
            try:
                os.remove(downloaded_file)
            except:
                pass
        clear_frames()


if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    print("--- БОТ ЗАПУЩЕН (Gemini Vision MODE) ---")
    app.run_polling()
