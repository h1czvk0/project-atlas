from datetime import datetime
from typing import Literal
from pydantic import BaseModel


class SessionCreate(BaseModel):
    title: str = "新会话"
    project_id: int = 1


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
    repo_progress: int = 0
    repo_stage: str = "等待导入"
    repo_error: str | None = None
    repo_last_synced_at: datetime | None = None


class ChatRequest(BaseModel):
    question: str
    session_id: int | None = None
    project_id: int | None = 1
    reasoning_effort: Literal["auto", "none", "minimal", "low", "medium", "high", "xhigh", "max"] | None = None


class ChatResponse(BaseModel):
    answer: str
    intent: str
    used_tools: list[str]
    sources: list[dict]
    confidence: str
    session_id: int | None = None


class SessionOut(BaseModel):
    id: int
    project_id: int
    title: str
    created_at: datetime

