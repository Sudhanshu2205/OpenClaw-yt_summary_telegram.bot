import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any

from services.qa import answer_question
from services.summarizer import (
    generate_summary,
    generate_deepdive,
    generate_action_points,
    generate_research_brief,
)
from services.transcript import get_transcript_data
from utils.helpers import extract_video_id
from utils.language import extract_requested_language, normalize_language

STATE_DB_PATH = Path("data/openclaw_sessions.db")
DEFAULT_LANGUAGE = "English"


def _is_quota_error(err: Exception) -> bool:
    msg = str(err).lower()
    return "insufficient_quota" in msg or "error code: 429" in msg or "exceeded your current quota" in msg


def _is_invalid_api_key_error(err: Exception) -> bool:
    msg = str(err).lower()
    return "invalid_api_key" in msg or "incorrect api key provided" in msg or "error code: 401" in msg


def _connect_db() -> sqlite3.Connection:
    STATE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(STATE_DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            user_id TEXT PRIMARY KEY,
            state_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    return conn


def _load_user_state(user_id: str) -> Dict[str, Any]:
    with _connect_db() as conn:
        row = conn.execute(
            "SELECT state_json FROM sessions WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if not row:
        return {"language": DEFAULT_LANGUAGE}
    try:
        parsed = json.loads(row[0])
        if isinstance(parsed, dict):
            parsed.setdefault("language", DEFAULT_LANGUAGE)
            return parsed
    except Exception:
        pass
    return {"language": DEFAULT_LANGUAGE}


def _save_user_state(user_id: str, user_state: Dict[str, Any]) -> None:
    payload = json.dumps(user_state, ensure_ascii=False)
    now = datetime.now(timezone.utc).isoformat()
    with _connect_db() as conn:
        conn.execute(
            """
            INSERT INTO sessions (user_id, state_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                state_json = excluded.state_json,
                updated_at = excluded.updated_at
            """,
            (user_id, payload, now),
        )


def handle_message(user_id: str, text: str) -> str:
    user = _load_user_state(user_id)

    def _done(message: str) -> str:
        _save_user_state(user_id, user)
        return message

    text = (text or "").strip()
    if not text:
        return _done("Please send text.")

    requested_lang = extract_requested_language(text)
    if requested_lang:
        user["language"] = normalize_language(requested_lang)
    language = normalize_language(user.get("language", DEFAULT_LANGUAGE))
    lowered = text.lower()

    if lowered.startswith("/setlang"):
        parts = text.split(maxsplit=1)
        if len(parts) == 1:
            return _done("Usage: /setlang <language>")
        user["language"] = normalize_language(parts[1])
        return _done(f"Language set to {user['language']}.")

    if lowered.startswith("/fulltranscript"):
        full_lines = (user.get("transcript_lines") or "").strip()
        if not full_lines:
            return _done("Please send a YouTube link first.")
        return _done(full_lines)

    if lowered in {"/summary", "/research", "/deepdive", "/actionpoints"} and not user.get("transcript"):
        return _done("Please send a YouTube link first.")

    if "youtube.com" in text or "youtu.be" in text:
        video_id = extract_video_id(text)
        if not video_id:
            return _done("Invalid YouTube URL.")

        try:
            transcript_data = get_transcript_data(video_id)
        except Exception as err:
            return _done(
                "Could not fetch transcript for this video.\n"
                "Try another public video, or install yt-dlp for audio fallback.\n"
                f"Reason: {str(err)[:700]}"
            )
        user["transcript"] = transcript_data["text"]
        user["timeline_markers"] = transcript_data["timeline"]
        user["source_language"] = transcript_data["source_language"]
        user["video_title"] = transcript_data.get("video_title", "Unknown Title")
        user["transcript_source_type"] = transcript_data.get("source_type", "unknown")
        user["transcript_truncated"] = bool(transcript_data.get("is_truncated", False))
        user["transcript_lines"] = transcript_data.get("full_lines", "")
        user["qa_history"] = []
        user["last_summary"] = ""

        try:
            summary = generate_summary(
                transcript=user["transcript"],
                language=language,
                timeline_markers=user.get("timeline_markers", ""),
                source_language=user.get("source_language", "Unknown"),
                video_title=user.get("video_title", "Unknown Title"),
            )
        except Exception as err:
            if _is_quota_error(err):
                return _done(
                    "Transcript fetched successfully, but summary failed: API quota exceeded."
                )
            if _is_invalid_api_key_error(err):
                return _done("Summary failed: invalid API key/provider setup.")
            return _done("Summary generation failed.")
        user["last_summary"] = summary
        if user.get("transcript_truncated"):
            summary = (
                "Transcript is very long. Using a capped transcript window for reliable processing.\n\n"
                + summary
            )
        return _done(summary)

    if lowered.startswith("/summary"):
        try:
            summary = generate_summary(
                transcript=user["transcript"],
                language=language,
                timeline_markers=user.get("timeline_markers", ""),
                source_language=user.get("source_language", "Unknown"),
                video_title=user.get("video_title", "Unknown Title"),
            )
        except Exception as err:
            if _is_quota_error(err):
                return _done("Summary failed: API quota exceeded.")
            if _is_invalid_api_key_error(err):
                return _done("Summary failed: invalid API key/provider setup.")
            return _done("Summary generation failed.")
        user["last_summary"] = summary
        return _done(summary)

    if lowered.startswith("/research"):
        try:
            result = generate_research_brief(
                transcript=user["transcript"],
                language=language,
                timeline_markers=user.get("timeline_markers", ""),
                source_language=user.get("source_language", "Unknown"),
                video_title=user.get("video_title", "Unknown Title"),
            )
        except Exception as err:
            if _is_quota_error(err):
                return _done("Research brief failed: API quota exceeded.")
            if _is_invalid_api_key_error(err):
                return _done("Research brief failed: invalid API key/provider setup.")
            return _done("Research brief generation failed.")
        return _done(result)

    if lowered.startswith("/deepdive"):
        try:
            result = generate_deepdive(
                transcript=user["transcript"],
                language=language,
                video_title=user.get("video_title", "Unknown Title"),
            )
        except Exception as err:
            if _is_quota_error(err):
                return _done("Deepdive failed: API quota exceeded.")
            if _is_invalid_api_key_error(err):
                return _done("Deepdive failed: invalid API key/provider setup.")
            return _done("Deepdive generation failed.")
        return _done(result)

    if lowered.startswith("/actionpoints"):
        try:
            result = generate_action_points(
                transcript=user["transcript"],
                language=language,
                video_title=user.get("video_title", "Unknown Title"),
            )
        except Exception as err:
            if _is_quota_error(err):
                return _done("Action points failed: API quota exceeded.")
            if _is_invalid_api_key_error(err):
                return _done("Action points failed: invalid API key/provider setup.")
            return _done("Action points generation failed.")
        return _done(result)

    if requested_lang and ("summarize" in lowered or "summary" in lowered):
        if not user.get("transcript"):
            return _done(f"Language set to {user['language']}. Please send a YouTube link first.")
        try:
            summary = generate_summary(
                transcript=user["transcript"],
                language=user["language"],
                timeline_markers=user.get("timeline_markers", ""),
                source_language=user.get("source_language", "Unknown"),
                video_title=user.get("video_title", "Unknown Title"),
            )
        except Exception as err:
            if _is_quota_error(err):
                return _done("Summary failed: API quota exceeded.")
            if _is_invalid_api_key_error(err):
                return _done("Summary failed: invalid API key/provider setup.")
            return _done("Summary generation failed.")
        user["last_summary"] = summary
        return _done(summary)

    if user.get("transcript") and any(key in lowered for key in ("research brief", "key insights", "extract insights")):
        try:
            result = generate_research_brief(
                transcript=user["transcript"],
                language=language,
                timeline_markers=user.get("timeline_markers", ""),
                source_language=user.get("source_language", "Unknown"),
                video_title=user.get("video_title", "Unknown Title"),
            )
        except Exception as err:
            if _is_quota_error(err):
                return _done("Research brief failed: API quota exceeded.")
            if _is_invalid_api_key_error(err):
                return _done("Research brief failed: invalid API key/provider setup.")
            return _done("Research brief generation failed.")
        return _done(result)

    if user.get("transcript"):
        qa_history = user.get("qa_history", [])
        try:
            answer = answer_question(
                text,
                user["transcript"],
                language,
                qa_history=qa_history,
                summary_context=user.get("last_summary", ""),
                transcript_lines=user.get("transcript_lines", ""),
            )
        except Exception as err:
            if _is_quota_error(err):
                return _done("Q&A failed: API quota exceeded.")
            if _is_invalid_api_key_error(err):
                return _done("Q&A failed: invalid API key/provider setup.")
            return _done("Could not answer the question right now.")
        qa_history.append({"q": text, "a": answer})
        user["qa_history"] = qa_history[-8:]
        return _done(answer)

    return _done("Please send a YouTube link first.")


def main():
    parser = argparse.ArgumentParser(description="OpenClaw runtime bridge for YouTube assistant")
    parser.add_argument("--user", required=True, help="Stable user/session id from channel")
    parser.add_argument("--text", required=True, help="Incoming user message text")
    args = parser.parse_args()

    result = handle_message(args.user, args.text)
    print(result)


if __name__ == "__main__":
    main()
