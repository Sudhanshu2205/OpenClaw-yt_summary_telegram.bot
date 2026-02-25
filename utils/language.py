import re

LANGUAGE_ALIASES = {
    "english": "English",
    "hindi": "Hindi",
    "kannada": "Kannada",
    "kanada": "Kannada",
    "tamil": "Tamil",
    "telugu": "Telugu",
    "telgu": "Telugu",
    "french": "French",
    "spanish": "Spanish",
    "german": "German",
}

EXAMPLE_LANGUAGES = sorted(set(LANGUAGE_ALIASES.values()))

def normalize_language(language: str) -> str:
    if not language:
        return "English"
    cleaned = language.strip()
    alias = LANGUAGE_ALIASES.get(cleaned.lower())
    if alias:
        return alias
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,:;!?")
    if not cleaned:
        return "English"
    return cleaned[:40]

def extract_requested_language(text: str):
    source = (text or "").strip()

    patterns = [
        r"\b(?:summari[sz]e|summary|answer|respond|reply)\s+(?:in|into)\s+([^\n,.!?;:]{2,50})",
        r"\b(?:in|into)\s+([^\n,.!?;:]{2,50})",
        r"\blanguage\s*[:=]?\s*([^\n,.!?;:]{2,50})",
    ]

    for pattern in patterns:
        match = re.search(pattern, source, flags=re.IGNORECASE)
        if not match:
            continue
        candidate = re.sub(r"\s+", " ", match.group(1)).strip(" .,:;!?")

        candidate = re.split(
            r"\b(?:for|with|using|please|and)\b",
            candidate,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip()
        if not candidate:
            continue
        alias = LANGUAGE_ALIASES.get(candidate.lower())
        if alias:
            return alias
        return candidate[:40]
    return None

def get_user_language(context):
    return normalize_language(context.user_data.get("language", "English"))
