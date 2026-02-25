import asyncio
import os
import tempfile
from dotenv import load_dotenv
from telegram import Update
from telegram.error import Conflict
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.ext import _applicationbuilder as _ptb_appbuilder
from telegram.ext import _updater as _ptb_updater

from config import (
    client,
    VOICE_INPUT_ENABLED,
    VOICE_OUTPUT_ENABLED,
    STT_MODEL,
    TTS_MODEL,
)
from services.qa import answer_question
from services.summarizer import (
    generate_summary,
    generate_deepdive,
    generate_action_points,
    generate_research_brief,
)
from services.transcript import get_transcript_data
from utils.helpers import extract_video_id
from utils.language import (
    extract_requested_language,
    get_user_language,
    normalize_language,
    EXAMPLE_LANGUAGES,
)

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
MAX_TTS_CHARS = 2000
MAX_TELEGRAM_MSG_CHARS = 3800
CONFLICT_REPORTED = False


def _is_openai_quota_error(err: Exception) -> bool:
    msg = str(err).lower()
    return "insufficient_quota" in msg or "error code: 429" in msg or "exceeded your current quota" in msg


def _is_invalid_api_key_error(err: Exception) -> bool:
    msg = str(err).lower()
    return "invalid_api_key" in msg or "incorrect api key provided" in msg or "error code: 401" in msg


def _chunk_text(text: str, max_chars: int = MAX_TELEGRAM_MSG_CHARS):
    text = (text or "").strip()
    if not text:
        return []

    chunks = []
    current = []
    current_len = 0

    for line in text.splitlines():
        line = line.rstrip()
        if not line:
            line = " "
        line_len = len(line) + 1
        if current and current_len + line_len > max_chars:
            chunks.append("\n".join(current))
            current = [line]
            current_len = line_len
        else:
            current.append(line)
            current_len += line_len

    if current:
        chunks.append("\n".join(current))
    return chunks


async def _send_long_text(update: Update, text: str):
    chunks = _chunk_text(text)
    if not chunks:
        await update.message.reply_text("No transcript text available.")
        return

    total = len(chunks)
    for idx, chunk in enumerate(chunks, start=1):
        if total == 1:
            await update.message.reply_text(chunk)
        else:
            await update.message.reply_text(f"[Part {idx}/{total}]\n{chunk}")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    global CONFLICT_REPORTED
    err = context.error
    if isinstance(err, Conflict):
        if not CONFLICT_REPORTED:
            print(
                "Telegram polling conflict detected. "
                "Another bot instance is already running with this token. "
                "Stopping this instance."
            )
            CONFLICT_REPORTED = True
        # Safe shutdown signal; avoids RuntimeError when app isn't fully running.
        context.application.stop_running()
        return

    print(f"Unhandled error: {err}")


def _patch_updater_for_python313() -> None:
    """
    PTB 20.7 has a __slots__ issue on Python 3.13.
    Patch only when needed so the project still runs with current dependency lock.
    """
    missing_slot = "_Updater__polling_cleanup_cb"
    if missing_slot in getattr(_ptb_updater.Updater, "__slots__", ()):
        return

    class PatchedUpdater(_ptb_updater.Updater):
        __slots__ = _ptb_updater.Updater.__slots__ + (missing_slot,)

        def __init__(self, bot, update_queue):
            self.bot = bot
            self.update_queue = update_queue
            self._last_update_id = 0
            self._running = False
            self._initialized = False
            self._httpd = None
            self._Updater__lock = asyncio.Lock()
            self._Updater__polling_task = None
            self._Updater__polling_cleanup_cb = None

    _ptb_updater.Updater = PatchedUpdater
    _ptb_appbuilder.Updater = PatchedUpdater


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    voice_line = (
        "6) Send voice message for speech-to-text\n\n"
        if VOICE_INPUT_ENABLED
        else "6) Voice input is disabled for current API provider. Please send text input.\n\n"
    )
    await update.message.reply_text(
        "Welcome to Global YouTube AI Assistant!\n\n"
        "1) Send a YouTube link\n"
        "2) Ask questions about that video\n"
        "3) Change language: 'summarize in Arabic' or /setlang Arabic\n"
        "4) Use /fulltranscript to read full line-by-line transcript\n"
        "5) Use /research for deep research brief\n"
        f"{voice_line}"
        f"Examples: {', '.join(EXAMPLE_LANGUAGES)}"
    )


async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE, language: str):
    normalized = normalize_language(language)
    context.user_data["language"] = normalized
    await update.message.reply_text(f"Language set to {normalized}.")


async def english(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await set_language(update, context, "English")


async def hindi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await set_language(update, context, "Hindi")


async def kannada(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await set_language(update, context, "Kannada")


async def tamil(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await set_language(update, context, "Tamil")


async def telugu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await set_language(update, context, "Telugu")


async def languages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "This bot supports any language name/script as output.\n"
        "Use: /setlang <language>\n"
        f"Examples: {', '.join(EXAMPLE_LANGUAGES)}"
    )


async def setlang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /setlang <language>\nExample: /setlang Japanese")
        return
    await set_language(update, context, " ".join(context.args))


async def summary_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _generate_and_send_summary(update, context)


async def fulltranscript_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    full_lines = context.user_data.get("transcript_lines", "")
    if not full_lines:
        await update.message.reply_text("Please send a YouTube link first.")
        return

    await update.message.reply_text("Sending full transcript (line-by-line with timestamps)...")
    await _send_long_text(update, full_lines)


async def deepdive_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    transcript = context.user_data.get("transcript")
    if not transcript:
        await update.message.reply_text("Please send a YouTube link first.")
        return
    language = get_user_language(context)
    title = context.user_data.get("video_title", "Unknown Title")
    try:
        result = generate_deepdive(transcript=transcript, language=language, video_title=title)
        await update.message.reply_text(result)
        await send_voice_reply(update, result)
    except Exception as e:
        if _is_openai_quota_error(e):
            await update.message.reply_text("Deepdive failed: API quota exceeded.")
        elif _is_invalid_api_key_error(e):
            await update.message.reply_text("Deepdive failed: invalid API key/provider setup.")
        else:
            await update.message.reply_text("Deepdive generation failed.")
        print("Deepdive Error:", e)


async def research_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    transcript = context.user_data.get("transcript")
    if not transcript:
        await update.message.reply_text("Please send a YouTube link first.")
        return
    language = get_user_language(context)
    title = context.user_data.get("video_title", "Unknown Title")
    try:
        result = generate_research_brief(
            transcript=transcript,
            language=language,
            timeline_markers=context.user_data.get("timeline_markers", ""),
            source_language=context.user_data.get("source_language", "Unknown"),
            video_title=title,
        )
        await _send_long_text(update, result)
        await send_voice_reply(update, result)
    except Exception as e:
        if _is_openai_quota_error(e):
            await update.message.reply_text("Research brief failed: API quota exceeded.")
        elif _is_invalid_api_key_error(e):
            await update.message.reply_text("Research brief failed: invalid API key/provider setup.")
        else:
            await update.message.reply_text("Research brief generation failed.")
        print("Research Error:", e)


async def actionpoints_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    transcript = context.user_data.get("transcript")
    if not transcript:
        await update.message.reply_text("Please send a YouTube link first.")
        return
    language = get_user_language(context)
    title = context.user_data.get("video_title", "Unknown Title")
    try:
        result = generate_action_points(
            transcript=transcript,
            language=language,
            video_title=title,
        )
        await update.message.reply_text(result)
        await send_voice_reply(update, result)
    except Exception as e:
        if _is_openai_quota_error(e):
            await update.message.reply_text("Action points failed: API quota exceeded.")
        elif _is_invalid_api_key_error(e):
            await update.message.reply_text("Action points failed: invalid API key/provider setup.")
        else:
            await update.message.reply_text("Action points generation failed.")
        print("Actionpoints Error:", e)


async def send_voice_reply(update: Update, text: str):
    if not VOICE_OUTPUT_ENABLED:
        return

    # Keep TTS prompt short to reduce failures and latency.
    tts_input = (text or "").strip()[:MAX_TTS_CHARS]
    if not tts_input:
        return

    tmp_path = None
    try:
        response = client.audio.speech.create(
            model=TTS_MODEL,
            voice="alloy",
            input=tts_input,
        )
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp_file:
            tmp_path = tmp_file.name

        if hasattr(response, "stream_to_file"):
            response.stream_to_file(tmp_path)
        else:
            with open(tmp_path, "wb") as out:
                out.write(response.content)

        with open(tmp_path, "rb") as f:
            await update.message.reply_voice(f)
    except Exception as e:
        # Do not fail the full flow on TTS issues.
        print("TTS Error:", e)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not VOICE_INPUT_ENABLED:
        await update.message.reply_text(
            "Voice input is disabled for current API provider. Please send text input."
        )
        return

    tmp_path = None
    try:
        voice = update.message.voice
        file = await context.bot.get_file(voice.file_id)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as tmp_file:
            tmp_path = tmp_file.name
        await file.download_to_drive(tmp_path)

        with open(tmp_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model=STT_MODEL,
                file=audio_file,
            )

        user_text = transcript.text.strip()
        await update.message.reply_text(f"You said: {user_text}")
        await process_user_text(update, context, user_text)
    except Exception as e:
        if _is_openai_quota_error(e):
            await update.message.reply_text(
                "Voice processing is unavailable: OpenAI quota exceeded.\n"
                "Please check billing/usage, or send text input for now."
            )
        elif _is_invalid_api_key_error(e):
            await update.message.reply_text(
                "Voice processing failed: invalid API key/provider setup.\n"
                "If using OpenRouter, set OPENAI_BASE_URL=https://openrouter.ai/api/v1 and use OPENROUTER_API_KEY."
            )
        else:
            await update.message.reply_text("Could not process voice message.")
        print("Voice Error:", e)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


async def _generate_and_send_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    transcript = context.user_data.get("transcript")
    if not transcript:
        await update.message.reply_text("Please send a YouTube link first.")
        return

    language = get_user_language(context)
    try:
        summary = generate_summary(
            transcript=transcript,
            language=language,
            timeline_markers=context.user_data.get("timeline_markers", ""),
            source_language=context.user_data.get("source_language", "Unknown"),
            video_title=context.user_data.get("video_title", "Unknown Title"),
        )
        context.user_data["last_summary"] = summary
        await update.message.reply_text(summary)
        await send_voice_reply(update, summary)
    except Exception as e:
        if _is_openai_quota_error(e):
            await update.message.reply_text(
                "Transcript fetched successfully, but summary failed: OpenAI quota exceeded.\n"
                "Please check your OpenAI billing/usage, then retry."
            )
        elif _is_invalid_api_key_error(e):
            await update.message.reply_text(
                "Summary failed: invalid API key/provider setup.\n"
                "If using OpenRouter, set OPENAI_BASE_URL=https://openrouter.ai/api/v1 and use OPENROUTER_API_KEY."
            )
        else:
            raise


async def process_user_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    text = (text or "").strip()
    if not text:
        await update.message.reply_text("Please send text or a voice message.")
        return

    requested_lang = extract_requested_language(text)
    if requested_lang:
        context.user_data["language"] = requested_lang

    language = get_user_language(context)
    lowered = text.lower()

    if requested_lang and ("summarize" in lowered or "summary" in lowered):
        await update.message.reply_text(f"Language set to {requested_lang}.")
        await _generate_and_send_summary(update, context)
        return
    if requested_lang and lowered in {f"in {requested_lang.lower()}", f"language {requested_lang.lower()}"}:
        await update.message.reply_text(f"Language set to {requested_lang}.")
        return

    if (
        "transcript" in context.user_data
        and any(key in lowered for key in ("research brief", "key insights", "extract insights"))
    ):
        try:
            result = generate_research_brief(
                transcript=context.user_data["transcript"],
                language=language,
                timeline_markers=context.user_data.get("timeline_markers", ""),
                source_language=context.user_data.get("source_language", "Unknown"),
                video_title=context.user_data.get("video_title", "Unknown Title"),
            )
            await _send_long_text(update, result)
            await send_voice_reply(update, result)
        except Exception as e:
            await update.message.reply_text("Research brief generation failed.")
            print("Research Trigger Error:", e)
        return

    if "youtube.com" in text or "youtu.be" in text:
        video_id = extract_video_id(text)
        if not video_id:
            await update.message.reply_text("Invalid YouTube URL.")
            return

        await update.message.reply_text("Fetching transcript...")
        try:
            transcript_data = get_transcript_data(video_id)
            context.user_data["transcript"] = transcript_data["text"]
            context.user_data["timeline_markers"] = transcript_data["timeline"]
            context.user_data["source_language"] = transcript_data["source_language"]
            context.user_data["video_title"] = transcript_data.get("video_title", "Unknown Title")
            context.user_data["transcript_source_type"] = transcript_data.get(
                "source_type", "unknown"
            )
            context.user_data["transcript_truncated"] = bool(
                transcript_data.get("is_truncated", False)
            )
            context.user_data["transcript_lines"] = transcript_data.get("full_lines", "")
            context.user_data["qa_history"] = []
            context.user_data["last_summary"] = ""
        except Exception as e:
            await update.message.reply_text(
                "Could not fetch transcript for this video.\n"
                "Try another public video, or install yt-dlp for audio fallback.\n"
                "Reason: " + str(e)[:700]
            )
            print("Transcript Error:", e)
            return

        await update.message.reply_text(
            f"Generating summary... (source: {context.user_data['transcript_source_type']})"
        )
        if context.user_data.get("transcript_truncated"):
            await update.message.reply_text(
                "Transcript is very long. Using a capped transcript window for reliable processing."
            )
        try:
            await update.message.reply_text(f"[VIDEO] Video Title: {context.user_data.get('video_title', 'Unknown Title')}")
            summary = generate_summary(
                transcript=transcript_data["text"],
                language=language,
                timeline_markers=transcript_data["timeline"],
                source_language=transcript_data["source_language"],
                video_title=context.user_data.get("video_title", "Unknown Title"),
            )
            context.user_data["last_summary"] = summary
            await update.message.reply_text(summary)
            await send_voice_reply(update, summary)
        except Exception as e:
            if _is_openai_quota_error(e):
                await update.message.reply_text(
                    "Transcript fetched successfully, but summary failed: OpenAI quota exceeded.\n"
                    "Please check your OpenAI billing/usage, then retry."
                )
            elif _is_invalid_api_key_error(e):
                await update.message.reply_text(
                    "Summary failed: invalid API key/provider setup.\n"
                    "If using OpenRouter, set OPENAI_BASE_URL=https://openrouter.ai/api/v1 and use OPENROUTER_API_KEY."
                )
            else:
                await update.message.reply_text("Summary generation failed.")
            print("Summary Error:", e)
        return

    if "transcript" in context.user_data:
        try:
            qa_history = context.user_data.get("qa_history", [])
            answer = answer_question(
                text,
                context.user_data["transcript"],
                language,
                qa_history=qa_history,
                summary_context=context.user_data.get("last_summary", ""),
                transcript_lines=context.user_data.get("transcript_lines", ""),
            )
            qa_history.append({"q": text, "a": answer})
            context.user_data["qa_history"] = qa_history[-8:]
            await update.message.reply_text(answer)
            await send_voice_reply(update, answer)
        except Exception as e:
            if _is_openai_quota_error(e):
                await update.message.reply_text(
                    "Q&A failed: OpenAI quota exceeded.\n"
                    "Please check your OpenAI billing/usage, then retry."
                )
            elif _is_invalid_api_key_error(e):
                await update.message.reply_text(
                    "Q&A failed: invalid API key/provider setup.\n"
                    "If using OpenRouter, set OPENAI_BASE_URL=https://openrouter.ai/api/v1 and use OPENROUTER_API_KEY."
                )
            else:
                await update.message.reply_text("Could not answer the question right now.")
            print("Q&A Error:", e)
        return

    await update.message.reply_text("Please send a YouTube link first.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await process_user_text(update, context, update.message.text)


def main():
    if not TOKEN:
        raise RuntimeError("Missing TELEGRAM_TOKEN in environment.")

    _patch_updater_for_python313()
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("summary", summary_cmd))
    app.add_handler(CommandHandler("research", research_cmd))
    app.add_handler(CommandHandler("fulltranscript", fulltranscript_cmd))
    app.add_handler(CommandHandler("deepdive", deepdive_cmd))
    app.add_handler(CommandHandler("actionpoints", actionpoints_cmd))
    app.add_handler(CommandHandler("languages", languages))
    app.add_handler(CommandHandler("setlang", setlang))
    app.add_handler(CommandHandler("english", english))
    app.add_handler(CommandHandler("hindi", hindi))
    app.add_handler(CommandHandler("kannada", kannada))
    app.add_handler(CommandHandler("kanada", kannada))
    app.add_handler(CommandHandler("tamil", tamil))
    app.add_handler(CommandHandler("telugu", telugu))
    app.add_handler(CommandHandler("telgu", telugu))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(on_error)

    print("Bot is running globally...")
    app.run_polling()


if __name__ == "__main__":
    main()
