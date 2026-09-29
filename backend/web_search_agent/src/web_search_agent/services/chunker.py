import re

_PARAGRAPH_SPLIT = re.compile(r"\n+")


def chunk_text(
    text: str,
    chunk_size: int = 220,
    overlap: int = 40,
    max_chunks: int = 12,
    min_words: int = 25,
) -> list[str]:
    """Split text into ~`chunk_size`-word passages, keeping paragraphs together where possible.

    Consecutive chunks share up to `overlap` words so a fact spanning a boundary is not lost.
    """
    # 1. Paragraphs are the units; paragraphs longer than a chunk are windowed.
    units: list[list[str]] = []
    step = max(chunk_size - overlap, 1)
    for paragraph in _PARAGRAPH_SPLIT.split(text):
        words = paragraph.split()
        if not words:
            continue
        if len(words) <= chunk_size:
            units.append(words)
            continue
        for start in range(0, len(words), step):
            units.append(words[start : start + chunk_size])
            if start + chunk_size >= len(words):
                break

    # 2. Pack units into chunks, carrying trailing units forward as overlap.
    chunks: list[str] = []
    current: list[list[str]] = []
    size = 0
    for unit in units:
        if current and size + len(unit) > chunk_size:
            chunks.append(" ".join(word for u in current for word in u))
            if len(chunks) >= max_chunks:
                current = []
                break
            carry: list[list[str]] = []
            carry_size = 0
            for previous in reversed(current):
                if carry_size + len(previous) > overlap or carry_size + len(previous) + len(unit) > chunk_size:
                    break
                carry.insert(0, previous)
                carry_size += len(previous)
            current, size = carry, carry_size
        current.append(unit)
        size += len(unit)
    if current:
        chunks.append(" ".join(word for u in current for word in u))

    # 3. Drop fragments (menus, captions) unless that is all the page had.
    kept = [chunk for chunk in chunks if len(chunk.split()) >= min_words]
    return kept or chunks[:1]
