"""Text -> chunks of about `size` words, keeping line breaks (tables/CSV rows stay readable)."""


def chunk_text(text: str, size: int, overlap: int) -> list[str]:
    """Pack whole lines into chunks of at most ~`size` words. Lines longer than `size` are split.

    Consecutive chunks share the last lines of the previous chunk (up to `overlap` words), so text
    cut at a chunk boundary is still complete in one of the two chunks.
    """
    pieces = []
    for line in text.splitlines():
        words = line.split()
        for start in range(0, len(words), size):
            pieces.append(" ".join(words[start:start + size]))

    chunks: list[str] = []
    current: list[str] = []
    count = 0
    carried = 0  # lines at the start of `current` copied from the previous chunk
    for piece in pieces:
        n = len(piece.split())
        if len(current) > carried and count + n > size:
            chunks.append("\n".join(current))
            current, count = _tail(current, overlap)
            carried = len(current)
        current.append(piece)
        count += n
    if len(current) > carried:
        chunks.append("\n".join(current))
    return chunks


def _tail(lines: list[str], overlap: int) -> tuple[list[str], int]:
    """The last lines of a chunk whose total word count fits in `overlap`."""
    tail: list[str] = []
    count = 0
    for line in reversed(lines):
        n = len(line.split())
        if count + n > overlap:
            break
        tail.insert(0, line)
        count += n
    return tail, count
