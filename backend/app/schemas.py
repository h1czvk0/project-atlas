from datetime import datetime
from pydantic import BaseModel


class SessionCreate(BaseModel):
    title: str = "新会话"


class ProjectCreate(BaseModel):
    name: str
    slug: str
    description: str = ""
    repo_url: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    repo_url: str | None = None


class ProjectOut(ProjectCreate):
    id: int
    repo_status: str = "not_imported"
    repo_last_commit: str | None = None
    repo_indexed_files: int = 0
    repo_last_synced_at: datetime | None = None


class ChatRequest(BaseModel):
    question: str
    session_id: int | None = None
    project_id: int | None = 1


class ChatResponse(BaseModel):
    answer: str
    intent: str
    used_tools: list[str]
    sources: list[dict]
    confidence: str


class SessionOut(BaseModel):
    id: int
    title: str
    created_at: datetime

