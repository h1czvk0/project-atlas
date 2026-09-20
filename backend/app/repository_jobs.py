from datetime import datetime
from threading import Lock, Thread

from .db import SessionLocal
from .github_sync import fetch_context
from .models import Document, Project
from .repository_analyzer import RepositoryImportError, build_repository_items, clone_repository


_running: set[int] = set()
_lock = Lock()


def repository_import_running(project_id: int) -> bool:
    with _lock:
        return project_id in _running


def _apply(project: Project, values: dict) -> None:
    for field, value in values.items():
        setattr(project, field, value)


def _update(project_id: int, **values) -> None:
    with SessionLocal() as db:
        project = db.get(Project, project_id)
        if not project:
            return
        _apply(project, values)
        db.commit()


def _worker(project_id: int) -> None:
    from .main import _index_remote_items

    try:
        with SessionLocal() as db:
            project = db.get(Project, project_id)
            if not project or not project.repo_url:
                raise RepositoryImportError("项目尚未配置公开 GitHub 仓库地址")
            repo_url = project.repo_url

            project_name = project.name

        _update(project_id, repo_status="importing", repo_progress=8, repo_stage="正在克隆仓库（大仓库可能需要数分钟）", repo_error=None)

        def report_clone_progress(percent: int) -> None:
            mapped = 8 + round(percent * 0.24)
            _update(project_id, repo_progress=min(mapped, 32), repo_stage=f"正在克隆仓库 · Git {percent}%")

        repo_path = clone_repository(project_id, repo_url, project_name, report_clone_progress)
        _update(project_id, repo_progress=35, repo_stage="正在解析源码与配置")
        items, report = build_repository_items(repo_path, repo_url)

        with SessionLocal() as db:
            project = db.get(Project, project_id)
            _apply(project, {"repo_progress": 58, "repo_stage": "正在建立知识索引"})
            old_documents = db.query(Document).filter(
                Document.project_id == project_id,
                Document.source_type.like("repository_%"),
            ).all()
            for document in old_documents:
                db.delete(document)
            db.commit()
            _index_remote_items(db, project_id, items)

        _update(project_id, repo_progress=88, repo_stage="正在同步 README、Commit 与 Issue")
        try:
            context_items = fetch_context(repo_url)
            with SessionLocal() as db:
                _index_remote_items(db, project_id, context_items)
        except Exception:
            # GitHub API context is supplemental; the local code index remains usable.
            pass

        _update(
            project_id,
            repo_status="ready",
            repo_progress=100,
            repo_stage="分析完成",
            repo_error=None,
            repo_local_path=str(repo_path),
            repo_last_commit=report["commit"],
            repo_indexed_files=report["indexed_files"],
            repo_last_synced_at=datetime.utcnow(),
        )
    except Exception as exc:
        _update(
            project_id,
            repo_status="failed",
            repo_stage="分析失败",
            repo_error=str(exc)[:1000],
        )
    finally:
        with _lock:
            _running.discard(project_id)


def start_repository_import(project_id: int) -> bool:
    with _lock:
        if project_id in _running:
            return False
        _running.add(project_id)
    Thread(target=_worker, args=(project_id,), daemon=True, name=f"atlas-repo-{project_id}").start()
    return True
