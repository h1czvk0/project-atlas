from app.rag import chunk_text, cosine, embedding
from app.agent import summarize_content
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


def test_parse_github_repo_url():
    assert parse_repo_url("https://github.com/h1czvk0/project-atlas") == ("h1czvk0", "project-atlas")


def test_parse_github_repo_url_rejects_other_hosts():
    with pytest.raises(ValueError):
        parse_repo_url("https://example.com/h1czvk0/project-atlas")
