from rag_agent.chunking import chunk_text


def words(n: int, prefix: str = "w") -> str:
    return " ".join(f"{prefix}{i}" for i in range(n))


def test_short_text_is_one_chunk():
    assert chunk_text("hello world\nsecond line", size=300, overlap=50) == ["hello world\nsecond line"]


def test_empty_text_has_no_chunks():
    assert chunk_text("  \n\n ", size=300, overlap=50) == []


def test_lines_are_kept_and_chunks_respect_size():
    text = "\n".join(words(10, f"l{i}_") for i in range(10))  # 10 lines x 10 words
    chunks = chunk_text(text, size=30, overlap=0)
    assert chunks == ["\n".join(words(10, f"l{i}_") for i in range(s, s + 3)) for s in (0, 3, 6)] + [words(10, "l9_")]


def test_consecutive_chunks_overlap_by_whole_lines():
    text = "\n".join(words(10, f"l{i}_") for i in range(6))
    chunks = chunk_text(text, size=30, overlap=10)
    assert chunks[0].splitlines()[-1] == chunks[1].splitlines()[0]  # last line repeated
    assert "".join(chunks).count("l5_0") == 1


def test_long_line_is_split():
    chunks = chunk_text(words(700), size=300, overlap=0)
    assert [len(c.split()) for c in chunks] == [300, 300, 100]


def test_no_chunk_is_only_the_carried_overlap():
    # 280 + 20 words fill chunk 1; its 20-word last line is carried over, then a 290-word line follows.
    # The carried line alone must not become a chunk.
    text = "\n".join([words(280, "a"), words(20, "b"), words(290, "c")])
    chunks = chunk_text(text, size=300, overlap=20)
    assert len(chunks) == 2
    assert chunks[1].startswith("b0")  # overlap line leads the next chunk
    assert chunks[1].endswith("c289")
