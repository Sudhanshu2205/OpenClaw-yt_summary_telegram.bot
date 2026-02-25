from config import client, CHAT_MODEL
from utils.language import normalize_language

import re


CHUNK_SIZE = 12000
MAX_CHUNKS = 6


def _chat(prompt: str, temperature: float = 0.2) -> str:
    response = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    return response.choices[0].message.content


def _split_text(text: str, chunk_size: int = CHUNK_SIZE, max_chunks: int = MAX_CHUNKS):
    text = (text or "").strip()
    if not text:
        return []
    chunks = []
    idx = 0
    while idx < len(text) and len(chunks) < max_chunks:
        chunks.append(text[idx : idx + chunk_size])
        idx += chunk_size
    return chunks


def _looks_structured_summary(text: str) -> bool:
    if not text:
        return False
    required_headers = ["Video Title:", "5 Key Points:", "Important Timestamps:", "Core Takeaway:"]
    if not all(header in text for header in required_headers):
        return False
    key_point_count = len(re.findall(r"(?m)^\s*[1-5][\.\)]\s+", text))
    has_timestamp_bullet = bool(re.search(r"(?m)^\s*-\s+.+", text.split("Important Timestamps:", 1)[-1]))
    return key_point_count >= 3 and has_timestamp_bullet


def _fallback_structured_summary(raw_text: str, video_title: str) -> str:
    raw_lines = [ln.strip() for ln in (raw_text or "").splitlines() if ln.strip()]
    key_lines = [ln for ln in raw_lines if len(ln) > 20][:5]
    while len(key_lines) < 5:
        key_lines.append("Not enough clear evidence in transcript.")
    timestamp_lines = [ln for ln in raw_lines if re.search(r"\b\d{1,2}:\d{2}(?::\d{2})?\b", ln)][:3]
    if not timestamp_lines:
        timestamp_lines = ["Topic - Approx Timestamp not clearly available"]
    takeaway = raw_lines[0] if raw_lines else "Transcript was parsed, but summary details are limited."
    return (
        f"Video Title:\n{video_title}\n"
        "5 Key Points:\n"
        f"1. {key_lines[0]}\n"
        f"2. {key_lines[1]}\n"
        f"3. {key_lines[2]}\n"
        f"4. {key_lines[3]}\n"
        f"5. {key_lines[4]}\n"
        "Important Timestamps:\n"
        + "\n".join(f"- {line}" for line in timestamp_lines)
        + "\nCore Takeaway:\n"
        + takeaway
    )


def _repair_summary_format(
    draft_summary: str,
    language: str,
    video_title: str,
    timeline_markers: str,
) -> str:
    prompt = f"""
Reformat the draft summary into the exact structure below.
Respond strictly in {language}.
Use only draft and timeline markers. Do not invent facts.

Required exact sections and order:
Video Title:
5 Key Points:
1.
2.
3.
4.
5.
Important Timestamps:
- Topic - Approx Timestamp
Core Takeaway:

Video title to use:
{video_title}

Timeline Markers:
{timeline_markers if timeline_markers else "Not available"}

Draft Summary:
{draft_summary}
"""
    repaired = _chat(prompt, temperature=0.0)
    if _looks_structured_summary(repaired):
        return repaired
    return _fallback_structured_summary(draft_summary, video_title)


def _compress_transcript_for_long_video(
    transcript: str,
    language: str,
    video_title: str,
):
    chunks = _split_text(transcript)
    if len(chunks) <= 1:
        return transcript[:CHUNK_SIZE]

    notes = []
    for i, chunk in enumerate(chunks, start=1):
        prompt = f"""
You are a transcript compression assistant.
Respond strictly in {language}.
Use only the transcript chunk below.

Video title: {video_title}
Chunk: {i}/{len(chunks)}

Return concise notes:
- 6 key facts from this chunk
- 2 notable timestamps/segments if available
- 2 important claims or examples

Transcript Chunk:
{chunk}
"""
        notes.append(_chat(prompt, temperature=0.1))
    return "\n\n".join(notes)[:28000]


def generate_summary(
    transcript: str,
    language="English",
    timeline_markers: str = "",
    source_language: str = "Unknown",
    video_title: str = "Unknown Title",
):
    language = normalize_language(language)
    timeline_markers = (timeline_markers or "").strip()[:4000]
    compact_transcript = _compress_transcript_for_long_video(
        transcript=transcript,
        language=language,
        video_title=video_title,
    )

    prompt = f"""
You are a multilingual video-analysis assistant.

Rules:
- Use only the transcript and timeline markers provided.
- Do not invent claims, names, entities, or timestamps.
- If timing is uncertain, mark it as "approx".
- Respond strictly in {language}.

Detected transcript language: {source_language}
Video title: {video_title}

Output format (exact sections):
Video Title:
5 Key Points:
1.
2.
3.
4.
5.
Important Timestamps:
- Topic - Approx Timestamp
Core Takeaway:

Timeline Markers:
{timeline_markers if timeline_markers else "Not available"}

Transcript:
{compact_transcript}
"""
    draft = _chat(prompt, temperature=0.2)
    if _looks_structured_summary(draft):
        return draft
    return _repair_summary_format(
        draft_summary=draft,
        language=language,
        video_title=video_title,
        timeline_markers=timeline_markers,
    )


def generate_deepdive(
    transcript: str,
    language="English",
    video_title: str = "Unknown Title",
):
    language = normalize_language(language)
    compact_transcript = _compress_transcript_for_long_video(
        transcript=transcript,
        language=language,
        video_title=video_title,
    )

    prompt = f"""
You are a business research assistant.
Respond strictly in {language}.
Use only the transcript below. Do not hallucinate.

Create a deep-dive analysis for this video:
Title: {video_title}

Format:
1) Executive Context (3-4 lines)
2) Strategic Insights (5 bullets)
3) Risks / Limitations (3 bullets)
4) Practical Recommendations (5 bullets)
5) One-line Bottom Line

Transcript:
{compact_transcript}
"""
    return _chat(prompt, temperature=0.2)


def generate_action_points(
    transcript: str,
    language="English",
    video_title: str = "Unknown Title",
):
    language = normalize_language(language)
    compact_transcript = _compress_transcript_for_long_video(
        transcript=transcript,
        language=language,
        video_title=video_title,
    )

    prompt = f"""
You are an execution-focused assistant.
Respond strictly in {language}.
Use only the transcript below.

Create concrete action points from this video:
Title: {video_title}

Format:
- Action Item
- Owner Suggestion
- Priority (High/Medium/Low)
- Expected Outcome

Return 8 action items max.

Transcript:
{compact_transcript}
"""
    return _chat(prompt, temperature=0.2)


def generate_research_brief(
    transcript: str,
    language="English",
    timeline_markers: str = "",
    source_language: str = "Unknown",
    video_title: str = "Unknown Title",
):
    language = normalize_language(language)
    timeline_markers = (timeline_markers or "").strip()[:4000]
    compact_transcript = _compress_transcript_for_long_video(
        transcript=transcript,
        language=language,
        video_title=video_title,
    )

    prompt = f"""
You are a personal AI research assistant for YouTube videos.
Respond strictly in {language}.
Use only the provided transcript evidence.

Detected transcript language: {source_language}
Video title: {video_title}

Output format:
1) Executive Summary (5-7 lines)
2) Core Insights (8 bullets)
3) Evidence Snapshots (5 bullets with short quote/paraphrase + approx timestamp)
4) Open Questions Worth Investigating (5 bullets)
5) Practical Actions (6 bullets)
6) TL;DR (2 lines)

Timeline Markers:
{timeline_markers if timeline_markers else "Not available"}

Transcript:
{compact_transcript}
"""
    return _chat(prompt, temperature=0.2)
