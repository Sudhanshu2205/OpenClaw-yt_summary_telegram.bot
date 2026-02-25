import re
from urllib.parse import parse_qs, urlparse

_YT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")


def _valid_video_id(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if _YT_ID_PATTERN.fullmatch(value):
        return value
    return None

def _extract_url(text: str) -> str | None:
    if not text:
        return None
    match = re.search(r"(https?://[^\s]+)", text.strip())
    if not match:
        return None
    return match.group(1).rstrip(").,!?\"'")

def extract_video_id(text: str):
    """
    Extract YouTube video ID from a URL or a text containing a URL.
    """
    url = _extract_url(text) or text.strip()
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower().replace("www.", "")
    path_parts = [p for p in parsed.path.split("/") if p]
    query = parse_qs(parsed.query)

    if "v" in query and query["v"]:
        found = _valid_video_id(query["v"][0])
        if found:
            return found

    if host.endswith("youtu.be") and path_parts:
        found = _valid_video_id(path_parts[0])
        if found:
            return found

    if path_parts and path_parts[0] in {"shorts", "embed", "live"} and len(path_parts) >= 2:
        found = _valid_video_id(path_parts[1])
        if found:
            return found

    patterns = [
        r"(?:v=)([A-Za-z0-9_-]{11})",
        r"(?:youtu\.be/)([A-Za-z0-9_-]{11})",
        r"(?:youtube\.com/(?:shorts|embed|live)/)([A-Za-z0-9_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            found = _valid_video_id(match.group(1))
            if found:
                return found

    return None
