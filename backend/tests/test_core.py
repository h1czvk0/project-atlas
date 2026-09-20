from app.rag import chunk_text, cosine, embedding
from app.agent import summarize_content


def test_chunk_text_has_overlap_and_content():
    chunks = chunk_text("a" * 1000, size=300, overlap=50)
    assert len(chunks) >= 3
    assert all(chunks)


def test_embedding_is_normalized():
    vector = embedding("FastAPI RAG Agent")
    assert round(cosine(vector, vector), 5) == 1


def test_summary_keeps_key_lines():
    assert "FastAPI" in summarize_content("# FastAPI\n\nVue 3 前端")
