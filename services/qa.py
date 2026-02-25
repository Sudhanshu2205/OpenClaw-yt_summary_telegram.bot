import re
from config import client, CHAT_MODEL
from utils.language import normalize_language

STOPWORDS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "is",
    "are",
    "to",
    "in",
    "of",
    "for",
    "on",
    "with",
    "this",
    "that",
    "it",
    "be",
    "as",
    "at",
    "by",
    "from",
    "what",
    "when",
    "where",
    "why",
    "how",
}


NO_COVERAGE_REPLY = "This topic is not covered in the video."


def _tokenize(text: str):
    return [
        token
        for token in re.findall(r"[^\W_]+", text.lower(), flags=re.UNICODE)
        if token not in STOPWORDS and len(token) > 1
    ]

def _build_relevant_context(question: str, transcript: str, max_chars: int = 7000) -> str:
    chunks = re.split(r"(?<=[.!?])\s+|\n+", transcript)
    chunks = [chunk.strip() for chunk in chunks if chunk.strip()]
    q_tokens = set(_tokenize(question))

    if not q_tokens:
        return transcript[:max_chars]

    scored = []
    for idx, chunk in enumerate(chunks):
        chunk_tokens = set(_tokenize(chunk))
        overlap = len(q_tokens.intersection(chunk_tokens))
        if overlap > 0:
            scored.append((overlap, idx, chunk))

    if not scored:
        return transcript[:max_chars]

    scored.sort(key=lambda item: (-item[0], item[1]))
    selected = []
    size = 0
    for _, _, chunk in scored:
        if size + len(chunk) + 1 > max_chars:
            break
        selected.append(chunk)
        size += len(chunk) + 1
        if len(selected) >= 18:
            break
    return "\n".join(selected)


def _build_relevant_context_from_lines(
    question: str,
    transcript_lines: str,
    max_chars: int = 9000,
):
    lines = [line.strip() for line in (transcript_lines or "").splitlines() if line.strip()]
    if not lines:
        return {"context": "", "max_overlap": 0, "match_count": 0}

    q_tokens = set(_tokenize(question))
    if not q_tokens:
        default_context = "\n".join(lines[:100])[:max_chars]
        return {"context": default_context, "max_overlap": 0, "match_count": 0}

    scored = []
    for idx, line in enumerate(lines):
        line_tokens = set(_tokenize(line))
        overlap = len(q_tokens.intersection(line_tokens))
        if overlap > 0:
            scored.append((overlap, idx, line))

    if not scored:
        return {"context": "", "max_overlap": 0, "match_count": 0}

    scored.sort(key=lambda item: (-item[0], item[1]))
    selected = []
    size = 0
    max_overlap = scored[0][0]
    for _, _, line in scored:
        if size + len(line) + 1 > max_chars:
            break
        selected.append(line)
        size += len(line) + 1
        if len(selected) >= 80:
            break
    return {
        "context": "\n".join(selected),
        "max_overlap": max_overlap,
        "match_count": len(selected),
    }


def _format_recent_qa(qa_history, max_turns: int = 4, max_chars: int = 1400) -> str:
    if not qa_history:
        return ""

    lines = []
    size = 0
    for turn in qa_history[-max_turns:]:
        question = (turn.get("q", "") if isinstance(turn, dict) else "").strip()
        answer = (turn.get("a", "") if isinstance(turn, dict) else "").strip()
        if not question or not answer:
            continue
        block = f"Q: {question}\nA: {answer}\n"
        if size + len(block) > max_chars:
            break
        lines.append(block)
        size += len(block)
    return "\n".join(lines).strip()


def _extract_timestamps(text: str):
    return set(re.findall(r"\[(\d{1,2}:\d{2}(?::\d{2})?)\]", text or ""))


def _agent_resolve_question(
    question: str,
    language: str,
    recent_qa: str,
    summary_context: str,
) -> str:
    if not question.strip():
        return question

    prompt = f"""
You rewrite user follow-up questions for transcript search.

Rules:
- If question is already clear, return it unchanged.
- If question uses references (that/this/it/second point), rewrite into a self-contained question.
- Use recent context only to resolve references, not to add new facts.
- Return exactly one line in {language}.

Question:
{question}

Recent Q&A:
{recent_qa if recent_qa else "None"}

Recent Summary:
{summary_context if summary_context else "None"}
"""
    try:
        response = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        resolved = (response.choices[0].message.content or "").strip()
        return resolved or question
    except Exception:
        return question


def answer_question(
    question: str,
    transcript: str,
    language="English",
    qa_history=None,
    summary_context: str = "",
    transcript_lines: str = "",
):
    language = normalize_language(language)
    transcript = transcript[:18000]
    recent_qa = _format_recent_qa(qa_history)
    summary_context = (summary_context or "").strip()[:1800]
    resolved_question = _agent_resolve_question(question, language, recent_qa, summary_context)
    line_context_meta = _build_relevant_context_from_lines(
        resolved_question,
        transcript_lines,
        max_chars=9000,
    )
    line_context = line_context_meta["context"]
    text_context = _build_relevant_context(resolved_question, transcript, max_chars=7000)
    relevant_context = line_context or text_context

    history_section = (
        f"\nRecent Q&A Context (for follow-up references only):\n{recent_qa}\n"
        if recent_qa
        else ""
    )
    summary_section = (
        f"\nRecent Video Summary Context:\n{summary_context}\n"
        if summary_context
        else ""
    )

    # Strong evidence gate: if no lexical match found in timestamped lines, return exact fallback.
    if line_context_meta["max_overlap"] <= 0 or line_context_meta["match_count"] == 0:
        return NO_COVERAGE_REPLY

    prompt = f"""
You are a strict multilingual assistant.

Rules:
- Answer only from information grounded in the provided transcript excerpts.
- You may use Recent Q&A Context and Recent Video Summary Context only to resolve references like "that", "this point", or pronouns.
- Do not invent facts not supported by transcript evidence.
- If there is partial evidence, answer with best available evidence and mention uncertainty briefly.
- If answer is not present at all, respond exactly:
"{NO_COVERAGE_REPLY}"
- Include 1-2 inline evidence citations using timestamps from transcript lines, e.g. [03:15].
- Keep answer concise and factual.
- Respond strictly in {language}.

Original Question:
{question}

Resolved Question:
{resolved_question}

{history_section}
{summary_section}

Relevant Transcript Excerpts:
{relevant_context}
"""
    response = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
    )
    answer = (response.choices[0].message.content or "").strip()
    if not answer:
        return NO_COVERAGE_REPLY
    if answer == NO_COVERAGE_REPLY:
        return answer

    # Hard guardrail: reject uncited or invalidly cited answers.
    context_timestamps = _extract_timestamps(line_context)
    answer_timestamps = _extract_timestamps(answer)
    if not answer_timestamps:
        return NO_COVERAGE_REPLY
    if not answer_timestamps.intersection(context_timestamps):
        return NO_COVERAGE_REPLY
    return answer
