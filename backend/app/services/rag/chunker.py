"""Split extracted document text into overlapping chunks for embedding.

Chunks break on sentence boundaries where possible, and consecutive chunks
overlap by roughly ``chunk_overlap`` characters so a fact that straddles a
boundary stays retrievable from at least one chunk.
"""

import re

# Sentence terminators, including the Devanagari danda "।" used in Hindi.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?।])\s+")
# Collapse runs of spaces/tabs but keep newlines (they mark paragraph breaks).
_INLINE_WHITESPACE_RE = re.compile(r"[ \t\f\v]+")
# Collapse three or more newlines (paragraph breaks) down to two.
_BLANK_LINES_RE = re.compile(r"\n{3,}")


def normalize_text(text: str) -> str:
    """Tidy whitespace while preserving single paragraph breaks."""
    text = _BLANK_LINES_RE.sub("\n\n", text or "")
    lines = [_INLINE_WHITESPACE_RE.sub(" ", line).strip() for line in text.split("\n")]
    return "\n".join(lines).strip()


def _sentences(text: str) -> list[str]:
    """Return sentence-like pieces, one per non-empty line fragment."""
    pieces: list[str] = []
    for block in text.split("\n"):
        block = block.strip()
        if not block:
            continue
        for sentence in _SENTENCE_SPLIT_RE.split(block):
            sentence = sentence.strip()
            if sentence:
                pieces.append(sentence)
    return pieces


def _hard_split(piece: str, chunk_size: int) -> list[str]:
    """Split a single piece that is longer than one whole chunk."""
    return [piece[i : i + chunk_size] for i in range(0, len(piece), chunk_size)]


def split_text(text: str, chunk_size: int = 1000, chunk_overlap: int = 150) -> list[str]:
    """Split ``text`` into overlapping chunks of at most ~``chunk_size`` chars."""
    chunk_size = max(1, int(chunk_size))
    # Overlap must leave at least one new character per step to guarantee progress.
    chunk_overlap = max(0, min(int(chunk_overlap), chunk_size - 1))

    normalized = normalize_text(text)
    if not normalized:
        return []

    pieces: list[str] = []
    for sentence in _sentences(normalized):
        if len(sentence) > chunk_size:
            pieces.extend(_hard_split(sentence, chunk_size))
        else:
            pieces.append(sentence)
    if not pieces:
        return []

    chunks: list[str] = [pieces[0]]
    for piece in pieces[1:]:
        current = chunks[-1]
        if len(current) + 1 + len(piece) <= chunk_size:
            chunks[-1] = f"{current} {piece}"
            continue
        tail = current[-chunk_overlap:] if chunk_overlap else ""
        chunks.append(f"{tail} {piece}".strip() if tail else piece)

    return [chunk for chunk in chunks if chunk.strip()]
