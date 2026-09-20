import hashlib
import math
import re
from pathlib import Path
from typing import Iterable
from sqlalchemy.orm import Session
from .models import Document, DocumentChunk

TOKEN_RE = re.compile(r"[\u4e00-\u9fff]|[a-zA-Z0-9_]+")


def parse_text(filename: str, raw: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader
        import io
        return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(raw)).pages)
    if suffix == ".json":
        import json
        return json.dumps(json.loads(raw.decode("utf-8")), ensure_ascii=False, indent=2)
    return raw.decode("utf-8", errors="ignore")


def chunk_text(text: str, size: int = 700, overlap: int = 100) -> list[str]:
    cleaned = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not cleaned:
        return []
    chunks = []
    start = 0
    while start < len(cleaned):
        end = min(len(cleaned), start + size)
        if end < len(cleaned):
            boundary = cleaned.rfind("\n", start + int(size * 0.6), end)
            if boundary > start:
                end = boundary
        piece = cleaned[start:end].strip()
        if piece:
            chunks.append(piece)
        if end == len(cleaned):
            break
        next_start = max(0, end - overlap)
        start = next_start if next_start > start else end
    return chunks


def embedding(text: str, dimensions: int = 64) -> list[float]:
    vector = [0.0] * dimensions
    for token in TOKEN_RE.findall(text.lower()):
        digest = hashlib.sha256(token.encode()).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        vector[index] += 1.0
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def cosine(left: Iterable[float], right: Iterable[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def index_document(db: Session, document: Document, text: str) -> int:
    pieces = chunk_text(text)
    for idx, piece in enumerate(pieces):
        db.add(DocumentChunk(
            document_id=document.id,
            chunk_id=f"doc-{document.id}-chunk-{idx + 1}",
            content=piece,
            section_title=piece.splitlines()[0][:255] if piece else None,
            embedding=embedding(piece),
        ))
    document.chunk_count = len(pieces)
    document.status = "ready"
    return len(pieces)


def search(db: Session, query: str, top_k: int = 4, project_id: int = 1) -> list[dict]:
    qv = embedding(query)
    rows = db.query(DocumentChunk, Document).join(Document).filter(Document.status == "ready", Document.project_id == project_id).all()
    query_tokens = set(TOKEN_RE.findall(query.lower()))

    def score_row(row, document):
        content_tokens = set(TOKEN_RE.findall(row.content.lower()))
        lexical = len(query_tokens & content_tokens) / max(len(query_tokens), 1)
        filename_tokens = set(TOKEN_RE.findall(document.name.lower()))
        filename_match = len(query_tokens & filename_tokens) / max(len(query_tokens), 1)
        return 0.62 * cosine(qv, row.embedding) + 0.3 * lexical + 0.08 * filename_match

    scored = sorted(((score_row(row, doc), row, doc) for row, doc in rows), key=lambda item: item[0], reverse=True)
    selected = []
    per_document: dict[int, int] = {}
    for score, row, doc in scored:
        if per_document.get(doc.id, 0) >= 2:
            continue
        selected.append({
            "chunk_id": row.chunk_id,
            "document_id": doc.id,
            "document_name": doc.name,
            "section_title": row.section_title,
            "content": row.content,
            "score": round(score, 4),
            "source_type": doc.source_type,
            "source_url": doc.source_url,
        })
        per_document[doc.id] = per_document.get(doc.id, 0) + 1
        if len(selected) >= top_k:
            break
    return selected
