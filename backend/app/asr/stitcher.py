from __future__ import annotations

from dataclasses import dataclass

from backend.app.asr.postprocess import clean_asr_text, normalize_for_overlap


@dataclass
class TranscriptState:
    committed_text: str = ""
    partial_text: str = ""
    committed_end: float = 0.0
    revision: int = 0


class TranscriptStitcher:
    def __init__(self) -> None:
        self.state = TranscriptState()

    def apply_partial(self, text: str, start: float, end: float) -> tuple[str, int]:
        text = clean_asr_text(text)
        self.state.partial_text = self._merge_preview(text)
        self.state.revision += 1
        return self.state.partial_text, self.state.revision

    def apply_final(self, text: str, start: float, end: float) -> tuple[str, int]:
        text = clean_asr_text(text)
        self.state.committed_text = merge_overlap(self.state.committed_text, text)
        self.state.partial_text = ""
        self.state.committed_end = max(self.state.committed_end, end)
        self.state.revision += 1
        return self.state.committed_text, self.state.revision

    def _merge_preview(self, text: str) -> str:
        if not self.state.committed_text:
            return text
        return merge_overlap(self.state.committed_text, text)


def merge_overlap(existing: str, incoming: str, min_overlap: int = 4) -> str:
    existing = clean_asr_text(existing)
    incoming = clean_asr_text(incoming)
    if not existing:
        return incoming
    if not incoming:
        return existing

    normalized_existing = normalize_for_overlap(existing)
    normalized_incoming = normalize_for_overlap(incoming)
    max_len = min(len(normalized_existing), len(normalized_incoming))

    best = 0
    for size in range(max_len, min_overlap - 1, -1):
        if normalized_existing[-size:] == normalized_incoming[:size]:
            best = size
            break

    if best == 0:
        separator = "" if _ends_with_cjk(existing) or _starts_with_cjk(incoming) else " "
        return f"{existing}{separator}{incoming}".strip()

    consumed = _find_prefix_chars_to_consume(incoming, best)
    return f"{existing}{incoming[consumed:]}".strip()


def _find_prefix_chars_to_consume(text: str, normalized_chars: int) -> int:
    seen = 0
    for index, char in enumerate(text):
        if normalize_for_overlap(char):
            seen += 1
        if seen >= normalized_chars:
            return index + 1
    return len(text)


def _starts_with_cjk(text: str) -> bool:
    return bool(text) and "\u4e00" <= text[0] <= "\u9fff"


def _ends_with_cjk(text: str) -> bool:
    return bool(text) and "\u4e00" <= text[-1] <= "\u9fff"

