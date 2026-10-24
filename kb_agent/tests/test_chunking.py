"""切片逻辑单测：500 字符 + 50 重叠，且保留段落边界。"""
from __future__ import annotations

from app.services.ingest import chunk_text, split_paragraphs


def test_chunk_respects_size_and_overlap():
    paragraphs = [f"第{i}段。" + "内容" * 60 for i in range(6)]
    text = "\n\n".join(paragraphs)
    chunks = chunk_text(text, size=500, overlap=50)
    assert len(chunks) >= 2
    assert all(len(c) <= 500 for c in chunks)
    # 段首不应被截断成半个段落（首块以“第0段”开头）
    assert chunks[0].startswith("第0段")


def test_overlap_content_shared():
    text = "\n".join("甲" * 200 for _ in range(6))
    chunks = chunk_text(text, size=500, overlap=50)
    assert len(chunks) >= 2
    assert chunks[0][-50:] in chunks[1]


def test_short_text_single_chunk():
    assert chunk_text("很短的一段话", size=500, overlap=50) == ["很短的一段话"]


def test_blank_text():
    assert chunk_text("   \n\n  ") == []


def test_split_long_paragraph_by_sentence():
    text = "这是一个很长的句子。" * 100
    blocks = split_paragraphs(text)
    assert all(len(b) <= 500 for b in blocks)
    assert len(blocks) > 1
