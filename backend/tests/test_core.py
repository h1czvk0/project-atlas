from app.rag import chunk_text, cosine, embedding
from app.agent import _source_excerpt, _source_markdown, summarize_content
import pytest
from app.github_sync import parse_repo_url


def test_chunk_text_has_overlap_and_content():
    chunks = chunk_text("a" * 1000, size=300, overlap=50)
    assert len(chunks) >= 3
    assert all(chunks)


def test_embedding_is_normalized():
    vector = embedding("FastAPI RAG Agent")
    assert round(cosine(vector, vector), 5) == 1


def test_summary_keeps_key_lines():
    assert "FastAPI" in summarize_content("# FastAPI\n\nVue 3 前端")


def test_source_excerpt_stops_at_complete_line():
    content = "# Runbook\n\n## 排查步骤\n\n1. 检查错误率。\n2. 检查数据库连接池。\n3. 使用回滚方案。"
    excerpt = _source_excerpt(content, limit=42)
    assert "#" not in excerpt
    assert not excerpt.endswith("3. 使")
    assert excerpt.endswith("……")


def test_source_markdown_marks_shortened_content():
    markdown = _source_markdown([{
        "document_name": "runbook.md",
        "source_url": None,
        "content": "# Runbook\n" + "这是完整的一行。\n" * 40,
    }])
    assert "**runbook.md**" in markdown
    assert markdown.endswith("……")


def test_parse_github_repo_url():
    assert parse_repo_url("https://github.com/h1czvk0/project-atlas") == ("h1czvk0", "project-atlas")


def test_parse_github_repo_url_rejects_other_hosts():
    with pytest.raises(ValueError):
        parse_repo_url("https://example.com/h1czvk0/project-atlas")
