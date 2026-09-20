import hashlib
import json
import base64
from urllib.parse import urlparse
from pathlib import Path
import httpx
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from .agent import run_agent
from .config import settings
from .db import Base, engine, get_db
from .models import ChatSession, Document, Incident, Message, Project, ProjectTask
from .rag import index_document, parse_text
from .schemas import ChatRequest, ChatResponse, ProjectCreate, ProjectOut, SessionCreate, SessionOut

Base.metadata.create_all(bind=engine)
_seed_db = next(get_db())
if _seed_db.query(ProjectTask).count() == 0:
    _seed_db.add_all([
        ProjectTask(title="补充 Agent 评测集", priority="high"),
        ProjectTask(title="接入真实 embedding 服务", priority="medium"),
        ProjectTask(title="完善部署截图", priority="low"),
    ])
    _seed_db.commit()
if _seed_db.query(Project).count() == 0:
    _seed_db.add(Project(name="Demo Project", slug="demo-project", description="用于演示项目上下文检索和新人上手流程"))
    _seed_db.commit()
_seed_db.close()
app = FastAPI(title="Project Atlas", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "project-atlas"}


@app.get("/api/ready")
def ready(db: Session = Depends(get_db)):
    try:
        db.query(Document).count()
        return {"status": "ready", "database": "ok"}
    except Exception as exc:
        raise HTTPException(503, "数据库尚未就绪") from exc


@app.get("/api/projects", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)):
    return db.query(Project).order_by(Project.created_at.asc()).all()


@app.post("/api/projects", response_model=ProjectOut)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)):
    if db.query(Project).filter_by(slug=payload.slug).first():
        raise HTTPException(409, "项目 slug 已存在")
    project = Project(**payload.model_dump())
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@app.get("/api/documents")
def documents(project_id: int = 1, db: Session = Depends(get_db)):
    return db.query(Document).filter(Document.project_id == project_id).order_by(Document.created_at.desc()).all()


@app.get("/api/incidents")
def incidents(db: Session = Depends(get_db)):
    return db.query(Incident).order_by(Incident.created_at.desc()).limit(50).all()


@app.post("/api/incidents")
def create_incident(payload: dict, db: Session = Depends(get_db)):
    required = {"title", "service", "symptom"}
    if not required.issubset(payload):
        raise HTTPException(422, "title、service、symptom 为必填项")
    incident = Incident(title=payload["title"], service=payload["service"], symptom=payload["symptom"], severity=payload.get("severity", "medium"))
    db.add(incident)
    db.commit()
    db.refresh(incident)
    return incident


@app.get("/api/documents/{document_id}")
def document_detail(document_id: int, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    return doc


@app.post("/api/documents/upload")
async def upload_document(file: UploadFile = File(...), project_id: int = Form(1), db: Session = Depends(get_db)):
    allowed = {".pdf", ".md", ".markdown", ".txt", ".json"}
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in allowed:
        raise HTTPException(400, "仅支持 PDF、Markdown、TXT、JSON 文件")
    raw = await file.read()
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(413, "文件不能超过 10MB")
    digest = hashlib.sha256(raw).hexdigest()
    existing = db.query(Document).filter_by(sha256=digest).first()
    if existing:
        raise HTTPException(409, f"文件已存在，文档 ID 为 {existing.id}")
    target = Path(settings.upload_dir) / f"{digest}{suffix}"
    target.write_bytes(raw)
    if not db.get(Project, project_id):
        raise HTTPException(404, "项目不存在")
    doc = Document(name=file.filename or "unnamed", file_type=suffix, sha256=digest, size_bytes=len(raw), storage_path=str(target), project_id=project_id)
    db.add(doc)
    db.commit()
    db.refresh(doc)
    try:
        count = index_document(db, doc, parse_text(doc.name, raw))
        db.commit()
        return {"id": doc.id, "name": doc.name, "status": doc.status, "chunk_count": count}
    except Exception as exc:
        doc.status = "failed"
        doc.error_message = str(exc)
        db.commit()
        raise HTTPException(422, "文档解析失败，请检查文件内容") from exc


@app.post("/api/projects/{project_id}/sync-readme")
def sync_readme(project_id: int, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project or not project.repo_url:
        raise HTTPException(400, "项目尚未配置公开 GitHub 仓库地址")
    parsed = urlparse(project.repo_url)
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if parsed.netloc != "github.com" or len(parts) < 2:
        raise HTTPException(422, "repo_url 必须是 github.com/owner/repo")
    owner, repo = parts[0], parts[1].removesuffix(".git")
    response = httpx.get(f"https://api.github.com/repos/{owner}/{repo}/contents/README.md", headers={"Accept": "application/vnd.github+json"}, timeout=20)
    if response.status_code != 200:
        raise HTTPException(502, "无法从 GitHub 读取 README.md")
    payload = response.json()
    raw = base64.b64decode(payload["content"])
    digest = hashlib.sha256(raw).hexdigest()
    if db.query(Document).filter_by(sha256=digest).first():
        return {"status": "unchanged", "name": "README.md"}
    target = Path(settings.upload_dir) / f"{digest}.md"
    target.write_bytes(raw)
    doc = Document(name=f"{repo}-README.md", file_type=".md", sha256=digest, size_bytes=len(raw), storage_path=str(target), project_id=project_id)
    db.add(doc)
    db.commit()
    db.refresh(doc)
    count = index_document(db, doc, parse_text(doc.name, raw))
    db.commit()
    return {"status": "indexed", "document_id": doc.id, "chunk_count": count}


@app.post("/api/documents/{document_id}/reindex")
def reindex_document(document_id: int, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if not doc or not doc.storage_path:
        raise HTTPException(404, "文档或原文件不存在")
    path = Path(doc.storage_path)
    if not path.exists():
        raise HTTPException(410, "原文件已被删除，无法重新索引")
    for chunk in list(doc.chunks):
        db.delete(chunk)
    doc.status = "processing"
    db.flush()
    count = index_document(db, doc, parse_text(doc.name, path.read_bytes()))
    db.commit()
    return {"id": doc.id, "status": doc.status, "chunk_count": count}


@app.delete("/api/documents/{document_id}")
def delete_document(document_id: int, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(404, "文档不存在")
    db.delete(doc)
    db.commit()
    return {"deleted": document_id}


@app.post("/api/sessions", response_model=SessionOut)
def create_session(payload: SessionCreate, db: Session = Depends(get_db)):
    session = ChatSession(title=payload.title)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@app.get("/api/sessions", response_model=list[SessionOut])
def list_sessions(db: Session = Depends(get_db)):
    return db.query(ChatSession).order_by(ChatSession.created_at.desc()).all()


@app.get("/api/sessions/{session_id}/messages")
def session_messages(session_id: int, db: Session = Depends(get_db)):
    if not db.get(ChatSession, session_id):
        raise HTTPException(404, "会话不存在")
    return db.query(Message).filter_by(session_id=session_id).order_by(Message.created_at.asc()).all()


@app.post("/api/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, db: Session = Depends(get_db)):
    session = db.get(ChatSession, payload.session_id) if payload.session_id else None
    if not session:
        session = ChatSession(title=payload.question[:30])
        db.add(session)
        db.commit()
        db.refresh(session)
    db.add(Message(session_id=session.id, role="user", content=payload.question))
    result = run_agent(db, payload.question, session.id, payload.project_id or 1)
    db.add(Message(session_id=session.id, role="assistant", content=result["answer"], metadata_json=result))
    db.commit()
    return result


@app.post("/api/chat/stream")
def chat_stream(payload: ChatRequest, db: Session = Depends(get_db)):
    result = chat(payload, db)
    def events():
        yield f"event: status\ndata: {json.dumps({'status': 'completed'}, ensure_ascii=False)}\n\n"
        for tool in result["used_tools"]:
            yield f"event: tool\ndata: {json.dumps({'tool': tool}, ensure_ascii=False)}\n\n"
        yield f"event: answer\ndata: {json.dumps(result, ensure_ascii=False)}\n\n"
    return StreamingResponse(events(), media_type="text/event-stream")
