import hashlib
from pathlib import Path

from sqlalchemy.orm import Session

from .config import settings
from .models import Document


def project_content_digest(project_id: int, raw: bytes) -> str:
    return hashlib.sha256(f"project:{project_id}:".encode() + raw).hexdigest()


def upload_root() -> Path:
    root = Path(settings.upload_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def project_upload_dir(project_id: int) -> Path:
    directory = (upload_root() / f"project-{project_id}").resolve()
    if upload_root() not in directory.parents:
        raise ValueError("项目资料存储路径不安全")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def write_project_file(project_id: int, digest: str, suffix: str, raw: bytes) -> Path:
    target = project_upload_dir(project_id) / f"{digest}{suffix}"
    target.write_bytes(raw)
    return target


def cleanup_unreferenced_files(db: Session, storage_paths: list[str | None]) -> None:
    root = upload_root()
    for stored_path in {path for path in storage_paths if path}:
        if db.query(Document.id).filter(Document.storage_path == stored_path).first():
            continue
        path = Path(stored_path).expanduser().resolve()
        if path != root and root not in path.parents:
            continue
        path.unlink(missing_ok=True)
        parent = path.parent
        if parent != root and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
