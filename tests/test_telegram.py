from ads_copilot.reporters.telegram import _chunk


def test_chunk_short_message_single() -> None:
    assert _chunk("hello", 100) == ["hello"]


def test_chunk_long_message_splits_on_newlines() -> None:
    text = "\n".join(f"line-{i}" for i in range(200))
    chunks = _chunk(text, 100)
    assert len(chunks) > 1
    assert all(len(c) <= 100 for c in chunks)
    assert "\n".join(chunks) == text


def test_chunk_boundary() -> None:
    text = "a" * 50 + "\n" + "b" * 50
    chunks = _chunk(text, 60)
    assert len(chunks) == 2
