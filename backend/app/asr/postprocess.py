import re
import unicodedata


MUSIC_SYMBOLS_RE = re.compile(r"[♩♪♫♬♭♮♯]+")
SPACE_RE = re.compile(r"\s+")


def clean_asr_text(text: str) -> str:
    """Normalize common Whisper artifacts without changing valid Chinese text."""
    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.replace("\ufffd", "")
    normalized = MUSIC_SYMBOLS_RE.sub("", normalized)
    normalized = SPACE_RE.sub(" ", normalized)
    return normalized.strip()


def normalize_for_overlap(text: str) -> str:
    text = clean_asr_text(text)
    return re.sub(r"[\s，。,.!?！？、；;：:]+", "", text)

