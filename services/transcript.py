import os
import tempfile
import importlib
from types import ModuleType
from urllib.request import urlopen
from urllib.parse import quote
import json

from youtube_transcript_api import YouTubeTranscriptApi

from config import client, VOICE_INPUT_ENABLED, STT_MODEL

MAX_TRANSCRIPT_CHARS = 120000
MAX_FULL_LINES_ITEMS = 5000


def _load_yt_dlp() -> ModuleType | None:
    """
    Lazy-import yt_dlp so static analyzers don't fail when it's optional.
    """
    try:
        return importlib.import_module("yt_dlp")
    except Exception:
        return None


def _format_timestamp(seconds: float) -> str:
    total = int(seconds or 0)
    minutes, sec = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{sec:02d}"
    return f"{minutes:02d}:{sec:02d}"


def _build_timeline_markers(transcript_list, max_items: int = 14) -> str:
    if not transcript_list:
        return ""

    stride = max(1, len(transcript_list) // max_items)
    markers = []
    for idx in range(0, len(transcript_list), stride):
        item = transcript_list[idx]
        text = " ".join(_entry_text(item).split())
        if not text:
            continue
        snippet = text[:110]
        markers.append(f"- {_format_timestamp(_entry_start(item))} | {snippet}")
        if len(markers) >= max_items:
            break
    return "\n".join(markers)


def _build_full_lines_from_entries(transcript_list, max_items: int = 5000) -> str:
    if not transcript_list:
        return ""
    lines = []
    for item in transcript_list[:max_items]:
        text = " ".join(_entry_text(item).split())
        if not text:
            continue
        lines.append(f"[{_format_timestamp(_entry_start(item))}] {text}")
    return "\n".join(lines)


def _entry_text(entry) -> str:
    if isinstance(entry, dict):
        return entry.get("text", "") or ""
    return getattr(entry, "text", "") or ""


def _entry_start(entry) -> float:
    if isinstance(entry, dict):
        return float(entry.get("start", 0) or 0)
    return float(getattr(entry, "start", 0) or 0)


def _list_transcripts_catalog(video_id: str):
    if hasattr(YouTubeTranscriptApi, "list_transcripts"):
        return YouTubeTranscriptApi.list_transcripts(video_id)
    api = YouTubeTranscriptApi()
    if hasattr(api, "list"):
        return api.list(video_id)
    raise Exception("Unsupported youtube-transcript-api version.")


def _from_youtube_captions(video_id: str, preferred_languages=None):
    preferred_languages = preferred_languages or ["en", "hi", "ta", "te", "kn"]
    transcript_obj = None

    transcript_catalog = _list_transcripts_catalog(video_id)

    for lang in preferred_languages:
        try:
            transcript_obj = transcript_catalog.find_manually_created_transcript([lang])
            break
        except Exception:
            pass

    if transcript_obj is None:
        for lang in preferred_languages:
            try:
                transcript_obj = transcript_catalog.find_generated_transcript([lang])
                break
            except Exception:
                pass

    if transcript_obj is None:
        transcript_obj = next(iter(transcript_catalog))

    transcript_list = transcript_obj.fetch()
    full_text = " ".join(_entry_text(t) for t in transcript_list).strip()
    if not full_text:
        raise Exception("Empty transcript")
    full_text, truncated = _cap_transcript_text(full_text)

    return {
        "text": full_text,
        "timeline": _build_timeline_markers(transcript_list),
        "full_lines": _build_full_lines_from_entries(
            transcript_list, max_items=MAX_FULL_LINES_ITEMS
        ),
        "source_language": getattr(transcript_obj, "language", None)
        or getattr(transcript_obj, "language_code", None)
        or "Unknown",
        "is_generated": bool(getattr(transcript_obj, "is_generated", False)),
        "source_type": "youtube_captions",
        "is_truncated": truncated,
    }


def _build_timeline_from_segments(segments, max_items: int = 14) -> str:
    if not segments:
        return ""
    stride = max(1, len(segments) // max_items)
    markers = []
    for idx in range(0, len(segments), stride):
        seg = segments[idx]
        text = " ".join((seg.get("text") or "").split())
        if not text:
            continue
        markers.append(f"- {_format_timestamp(seg.get('start', 0))} | {text[:110]}")
        if len(markers) >= max_items:
            break
    return "\n".join(markers)


def _build_full_lines_from_segments(segments, max_items: int = 5000) -> str:
    if not segments:
        return ""
    lines = []
    for seg in segments[:max_items]:
        text = " ".join((seg.get("text") or "").split())
        if not text:
            continue
        lines.append(f"[{_format_timestamp(seg.get('start', 0))}] {text}")
    return "\n".join(lines)


def _cap_transcript_text(text: str, max_chars: int = MAX_TRANSCRIPT_CHARS) -> tuple[str, bool]:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars], True


def _from_audio_fallback(video_id: str):
    yt_dlp = _load_yt_dlp()

    if not VOICE_INPUT_ENABLED:
        raise Exception("Audio fallback disabled for current API provider.")

    if yt_dlp is None:
        raise Exception(
            "No captions found and yt-dlp is not installed. Install `yt-dlp` to enable audio fallback."
        )

    url = f"https://www.youtube.com/watch?v={video_id}"
    with tempfile.TemporaryDirectory() as tmpdir:
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": os.path.join(tmpdir, "%(id)s.%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            duration = int(info.get("duration") or 0)
            if duration and duration > 3 * 60 * 60:
                raise Exception("Video is too long for fallback transcription.")
            audio_path = ydl.prepare_filename(info)

        with open(audio_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model=STT_MODEL,
                file=audio_file,
                response_format="verbose_json",
            )

        text = (getattr(transcript, "text", None) or "").strip()
        if not text:
            raise Exception("Empty transcript after audio fallback.")
        text, truncated = _cap_transcript_text(text)

        segments = getattr(transcript, "segments", None) or []
        timeline = _build_timeline_from_segments(segments)
        language = getattr(transcript, "language", None) or "Unknown"

        return {
            "text": text,
            "timeline": timeline,
            "full_lines": _build_full_lines_from_segments(
                segments, max_items=MAX_FULL_LINES_ITEMS
            ),
            "source_language": language,
            "is_generated": True,
            "source_type": "audio_fallback",
            "is_truncated": truncated,
        }


def _fetch_video_title(video_id: str) -> str:
    yt_dlp = _load_yt_dlp()
    if yt_dlp is not None:
        try:
            with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
                info = ydl.extract_info(
                    f"https://www.youtube.com/watch?v={video_id}",
                    download=False,
                )
                title = (info or {}).get("title")
                if title:
                    return str(title)
        except Exception:
            pass

    # Public oEmbed fallback (no auth).
    try:
        target = quote(f"https://www.youtube.com/watch?v={video_id}", safe="")
        with urlopen(f"https://noembed.com/embed?url={target}", timeout=8) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            title = payload.get("title")
            if title:
                return str(title)
    except Exception:
        pass

    return "Unknown Title"


def get_transcript_data(video_id: str, preferred_languages=None):
    title = _fetch_video_title(video_id)
    try:
        data = _from_youtube_captions(video_id, preferred_languages=preferred_languages)
        data["video_title"] = title
        return data
    except Exception as caption_error:
        try:
            data = _from_audio_fallback(video_id)
            data["video_title"] = title
            return data
        except Exception as fallback_error:
            raise Exception(
                f"Captions failed: {caption_error}. Audio fallback failed: {fallback_error}"
            ) from fallback_error


def get_transcript(video_id: str):
    """
    Backward compatible wrapper.
    """
    return get_transcript_data(video_id)["text"]
