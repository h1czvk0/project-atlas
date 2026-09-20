import json
from queue import Queue
from threading import Thread
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
import httpx
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from .agent import check_llm_connection, run_agent
from .config import settings
from .db import Base, SessionLocal, engine, get_db
from .document_storage import cleanup_unreferenced_files, project_content_digest, write_project_file
from .github_sync import fetch_context
from .migrations import migrate_legacy_schema
from .models import ChatSession, Document, Incident, Message, Project, ProjectTask, ToolCall
from .rag import index_document, parse_text
from .repository_analyzer import RepositoryImportError, build_repository_items, copy_local_repository, project_workspace_path, repository_root
from .repository_jobs import repository_import_running, start_repository_import
from .schemas import ChatRequest, ChatResponse, ProjectCreate, ProjectOut, ProjectUpdate, SessionCreate, SessionOut

Base.metadata.create_all(bind=engine)
migrate_legacy_schema(engine)
_seed_db = next(get_db())
if _seed_db.query(Project).count() == 0:
    _seed_db.add(Project(name="Demo Project", slug="demo-project", description="用于演示项目上下文检索和新人上手流程"))
    _seed_db.commit()
demo_project = _seed_db.query(Project).filter_by(slug="demo-project").first()
if demo_project and _seed_db.query(ProjectTask).filter_by(project_id=demo_project.id).count() == 0:
    _seed_db.add_all([
        ProjectTask(project_id=demo_project.id, title="补充 Agent 评测集", priority="high"),
        ProjectTask(project_id=demo_project.id, title="接入真实 embedding 服务", priority="medium"),
        ProjectTask(project_id=demo_project.id, title="完善部署截图", priority="low"),
    ])
    _seed_db.commit()
_seed_db.close()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    with SessionLocal() as db:
        interrupted = db.query(Project).filter(Project.repo_status.in_(["queued", "importing"])).all()
        project_ids = [project.id for project in interrupted if project.repo_url]
        for project in interrupted:
            project.repo_status = "queued"
            project.repo_progress = 2
            project.repo_stage = "服务重启，准备恢复导入"
        db.commit()
    for project_id in project_ids:
        start_repository_import(project_id)
    yield


app = FastAPI(title="Project Atlas", version="0.3.0", lifespan=lifespan)
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


@app.get("/api/system/status")
def system_status(check: bool = False):
    llm = check_llm_connection() if check else {
        "configured": bool(settings.llm_base_url and settings.llm_api_key and settings.llm_model),
        "reachable": None,
        "model": settings.llm_model if settings.llm_base_url and settings.llm_api_key else None,
        "message": "点击测试连接" if settings.llm_base_url and settings.llm_api_key else "未配置大模型",
    }
    return {
        "llm_configured": llm["configured"],
        "llm_reachable": llm["reachable"],
        "llm_model": llm["model"],
        "llm_message": llm["message"],
        "llm_reasoning_effort": settings.llm_reasoning_effort,
        "github_token_configured": bool(settings.github_token),
    }


@app.get("/api/projects", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)):
    return db.query(Project).order_by(Project.created_at.asc()).all()


@app.post("/api/projects", response_model=ProjectOut, status_code=201)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)):
    if db.query(Project).filter_by(slug=payload.slug).first():
        raise HTTPException(409, "项目 slug 已存在")
    project = Project(**payload.model_dump())
    db.add(project)
    db.commit()
    db.refresh(project)
    if project.repo_url:
        project.repo_status = "queued"
        project.repo_stage = "等待分析"
        project.repo_progress = 2
        db.commit()
        start_repository_import(project.id)
    return project


@app.patch("/api/projects/{project_id}", response_model=ProjectOut)
def update_project(project_id: int, payload: ProjectUpdate, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "项目不存在")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, field, value.strip() if isinstance(value, str) else value)
    db.commit()
    db.refresh(project)
    return project


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "项目不存在")
    if repository_import_running(project_id):
        raise HTTPException(409, "仓库正在导入，请等待完成后再删除工作区")

    documents = db.query(Document).filter(Document.project_id == project_id).all()
    storage_paths = [document.storage_path for document in documents]

    sessions = db.query(ChatSession).filter(ChatSession.project_id == project_id).all()
    session_ids = [session.id for session in sessions]
    if session_ids:
        db.query(ToolCall).filter(ToolCall.session_id.in_(session_ids)).delete(synchronize_session=False)
        db.query(Message).filter(Message.session_id.in_(session_ids)).delete(synchronize_session=False)
        db.query(ChatSession).filter(ChatSession.id.in_(session_ids)).delete(synchronize_session=False)
    db.query(Incident).filter(Incident.project_id == project_id).delete(synchronize_session=False)
    db.query(ProjectTask).filter(ProjectTask.project_id == project_id).delete(synchronize_session=False)
    for document in documents:
        db.delete(document)
    workspace_root = repository_root()
    repository_path = Path(project.repo_local_path).resolve() if project.repo_local_path else project_workspace_path(project_id, project.name)
    db.delete(project)
    db.commit()
    cleanup_unreferenced_files(db, storage_paths)

    if workspace_root in repository_path.parents and repository_path.is_dir():
        from .repository_analyzer import _remove_tree
        _remove_tree(repository_path)
    return {"deleted": project_id}


@app.get("/api/documents")
def documents(project_id: int = 1, db: Session = Depends(get_db)):
    return db.query(Document).filter(Document.project_id == project_id).order_by(Document.created_at.desc()).all()


@app.get("/api/incidents")
def incidents(project_id: int = 1, db: Session = Depends(get_db)):
    return db.query(Incident).filter(Incident.project_id == project_id).order_by(Incident.created_at.desc()).limit(50).all()


@app.post("/api/incidents")
def create_incident(payload: dict, db: Session = Depends(get_db)):
    required = {"title", "service", "symptom", "project_id"}
    if not required.issubset(payload):
        raise HTTPException(422, "project_id、title、service、symptom 为必填项")
    if not db.get(Project, payload["project_id"]):
        raise HTTPException(404, "项目不存在")
    incident = Incident(project_id=payload["project_id"], title=payload["title"], service=payload["service"], symptom=payload["symptom"], severity=payload.get("severity", "medium"))
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
    if not db.get(Project, project_id):
        raise HTTPException(404, "项目不存在")
    digest = project_content_digest(project_id, raw)
    existing = db.query(Document).filter_by(project_id=project_id, sha256=digest).first()
    if existing:
        raise HTTPException(409, f"文件已存在，文档 ID 为 {existing.id}")
    target = write_project_file(project_id, digest, suffix, raw)
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
    try:
        items = [item for item in fetch_context(project.repo_url, limit=1) if item["kind"] == "github_readme"]
    except (ValueError, httpx.HTTPError, KeyError, RuntimeError) as exc:
        raise HTTPException(502, str(exc) if isinstance(exc, (ValueError, RuntimeError)) else "无法从 GitHub 读取 README.md") from exc
    return _index_remote_items(db, project_id, items)


def _index_remote_items(db: Session, project_id: int, items: list[dict]) -> dict:
    indexed = 0
    skipped = 0
    documents = []
    for item in items:
        raw = item["content"].encode("utf-8")
        digest = project_content_digest(project_id, raw)
        if db.query(Document).filter_by(project_id=project_id, sha256=digest).first():
            skipped += 1
            continue
        target = write_project_file(project_id, digest, ".md", raw)
        doc = Document(name=item["name"], file_type=".md", sha256=digest, size_bytes=len(raw), storage_path=str(target), project_id=project_id, source_type=item["kind"], source_url=item.get("url"))
        db.add(doc)
        db.commit()
        db.refresh(doc)
        count = index_document(db, doc, item["content"])
        db.commit()
        indexed += 1
        documents.append({"id": doc.id, "name": doc.name, "chunk_count": count, "source_url": item.get("url")})
    return {"status": "completed", "indexed": indexed, "skipped": skipped, "documents": documents}


@app.post("/api/projects/{project_id}/import-repository")
def import_repository(project_id: int, local_path: str | None = None, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "项目不存在")
    if not local_path and not project.repo_url:
        raise HTTPException(400, "请配置公开 GitHub 仓库地址或提供本地 Git 仓库路径")

    if not local_path:
        project.repo_status = "queued"
        project.repo_stage = "等待分析"
        project.repo_progress = 2
        project.repo_error = None
        db.commit()
        if not start_repository_import(project_id):
            raise HTTPException(409, "仓库分析任务正在运行")
        return {"status": "queued", "project_id": project_id}

    project.repo_status = "importing"
    project.repo_stage = "正在导入本地仓库"
    project.repo_progress = 10
    project.repo_error = None
    db.commit()
    try:
        repo_path = copy_local_repository(project_id, local_path, project.name)
        source_url = project.repo_url or repo_path.as_uri()
        items, report = build_repository_items(repo_path, source_url)
        old_documents = db.query(Document).filter(
            Document.project_id == project_id,
            Document.source_type.like("repository_%"),
        ).all()
        storage_paths = [document.storage_path for document in old_documents]
        for document in old_documents:
            db.delete(document)
        db.commit()
        cleanup_unreferenced_files(db, storage_paths)
        result = _index_remote_items(db, project_id, items)
        project = db.get(Project, project_id)
        project.repo_status = "ready"
        project.repo_progress = 100
        project.repo_stage = "分析完成"
        project.repo_error = None
        project.repo_local_path = str(repo_path)
        project.repo_last_commit = report["commit"]
        project.repo_indexed_files = report["indexed_files"]
        project.repo_last_synced_at = datetime.utcnow()
        db.commit()
        return {**result, **report}
    except (RepositoryImportError, OSError, ValueError) as exc:
        db.rollback()
        project = db.get(Project, project_id)
        if project:
            project.repo_status = "failed"
            project.repo_stage = "分析失败"
            project.repo_error = str(exc)[:1000]
            db.commit()
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/projects/{project_id}/sync-context")
def sync_context(project_id: int, db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project or not project.repo_url:
        raise HTTPException(400, "项目尚未配置公开 GitHub 仓库地址")
    try:
        items = fetch_context(project.repo_url)
    except (ValueError, httpx.HTTPError, KeyError, RuntimeError) as exc:
        raise HTTPException(502, str(exc) if isinstance(exc, (ValueError, RuntimeError)) else "无法从 GitHub 读取项目上下文") from exc
    return _index_remote_items(db, project_id, items)


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
    storage_path = doc.storage_path
    db.delete(doc)
    db.commit()
    cleanup_unreferenced_files(db, [storage_path])
    return {"deleted": document_id}


@app.post("/api/sessions", response_model=SessionOut)
def create_session(payload: SessionCreate, db: Session = Depends(get_db)):
    if not db.get(Project, payload.project_id):
        raise HTTPException(404, "项目不存在")
    session = ChatSession(project_id=payload.project_id, title=payload.title)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@app.get("/api/sessions", response_model=list[SessionOut])
def list_sessions(project_id: int | None = None, db: Session = Depends(get_db)):
    query = db.query(ChatSession)
    if project_id is not None:
        query = query.filter(ChatSession.project_id == project_id)
    return query.order_by(ChatSession.created_at.desc()).all()


@app.get("/api/sessions/{session_id}/messages")
def session_messages(session_id: int, db: Session = Depends(get_db)):
    if not db.get(ChatSession, session_id):
        raise HTTPException(404, "会话不存在")
    return db.query(Message).filter_by(session_id=session_id).order_by(Message.created_at.asc()).all()


@app.post("/api/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, db: Session = Depends(get_db)):
    project_id = payload.project_id or 1
    if not db.get(Project, project_id):
        raise HTTPException(404, "项目不存在")
    session = db.get(ChatSession, payload.session_id) if payload.session_id else None
    if session and session.project_id != project_id:
        raise HTTPException(409, "会话不属于当前项目")
    if not session:
        session = ChatSession(project_id=project_id, title=payload.question[:30])
        db.add(session)
        db.commit()
        db.refresh(session)
    history_rows = db.query(Message).filter_by(session_id=session.id).order_by(Message.created_at.desc()).limit(6).all()
    history = [{"role": row.role, "content": row.content} for row in reversed(history_rows)]
    db.add(Message(session_id=session.id, role="user", content=payload.question))
    result = run_agent(db, payload.question, session.id, project_id, payload.reasoning_effort, history)
    result["session_id"] = session.id
    db.add(Message(session_id=session.id, role="assistant", content=result["answer"], metadata_json=result))
    db.commit()
    return result


@app.post("/api/chat/stream")
def chat_stream(payload: ChatRequest, db: Session = Depends(get_db)):
    project_id = payload.project_id or 1
    if not db.get(Project, project_id):
        raise HTTPException(404, "项目不存在")
    session = db.get(ChatSession, payload.session_id) if payload.session_id else None
    if session and session.project_id != project_id:
        raise HTTPException(409, "会话不属于当前项目")
    if not session:
        session = ChatSession(project_id=project_id, title=payload.question[:30])
        db.add(session)
        db.commit()
        db.refresh(session)
    session_id = session.id

    def events():
        queue: Queue = Queue()

        def worker():
            try:
                with SessionLocal() as worker_db:
                    history_rows = worker_db.query(Message).filter_by(session_id=session_id).order_by(Message.created_at.desc()).limit(6).all()
                    history = [{"role": row.role, "content": row.content} for row in reversed(history_rows)]
                    worker_db.add(Message(session_id=session_id, role="user", content=payload.question))
                    result = run_agent(
                        worker_db, payload.question, session_id, project_id,
                        payload.reasoning_effort, history,
                        lambda content: queue.put(("delta", {"content": content})),
                    )
                    result["session_id"] = session_id
                    worker_db.add(Message(session_id=session_id, role="assistant", content=result["answer"], metadata_json=result))
                    worker_db.commit()
                    queue.put(("answer", result))
            except Exception as exc:
                queue.put(("error", {"message": str(exc)[:500]}))
            finally:
                queue.put(("done", None))

        Thread(target=worker, daemon=True, name=f"atlas-chat-{session_id}").start()
        yield f"event: status\ndata: {json.dumps({'status': 'running', 'session_id': session_id}, ensure_ascii=False)}\n\n"
        streamed = False
        while True:
            event, data = queue.get()
            if event == "done":
                break
            if event == "delta":
                streamed = True
            if event == "answer":
                for tool in data["used_tools"]:
                    yield f"event: tool\ndata: {json.dumps({'tool': tool}, ensure_ascii=False)}\n\n"
                if not streamed:
                    yield f"event: delta\ndata: {json.dumps({'content': data['answer']}, ensure_ascii=False)}\n\n"
            yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
    return StreamingResponse(events(), media_type="text/event-stream")
