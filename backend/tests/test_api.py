import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from app.main import app
from app.models import Document, Project
from app.db import SessionLocal


client = TestClient(app)


def test_project_workspace_document_and_stream_flow():
    project = client.post("/api/projects", json={
        "name": "API Test Project",
        "slug": "api-test-project",
        "description": "接口测试项目",
        "repo_url": None,
    })
    if project.status_code == 409:
        project_id = next(item["id"] for item in client.get("/api/projects").json() if item["slug"] == "api-test-project")
    else:
        assert project.status_code == 201
        project_id = project.json()["id"]

    content = b"# API Test\nRun the service with Docker Compose."
    upload = client.post(
        "/api/documents/upload",
        data={"project_id": project_id},
        files={"file": ("api-test.md", content, "text/markdown")},
    )
    assert upload.status_code in (200, 409)
    assert any(item["name"] == "api-test.md" for item in client.get(f"/api/documents?project_id={project_id}").json())

    stream = client.post("/api/chat/stream", json={"question": "项目如何启动？", "project_id": project_id})
    assert stream.status_code == 200
    assert "event: delta" in stream.text
    assert "event: answer" in stream.text
    status_payload = next(
        line.removeprefix("data: ") for line in stream.text.splitlines()
        if line.startswith("data: ") and '"session_id"' in line
    )
    session_id = json.loads(status_payload)["session_id"]
    follow_up = client.post("/api/chat/stream", json={
        "question": "有哪些文档？",
        "project_id": project_id,
        "session_id": session_id,
    })
    assert follow_up.status_code == 200
    assert f'"session_id": {session_id}' in follow_up.text
    messages = client.get(f"/api/sessions/{session_id}/messages").json()
    assert [message["role"] for message in messages[-4:]] == ["user", "assistant", "user", "assistant"]


def test_incidents_are_isolated_by_project():
    projects = client.get("/api/projects").json()
    project_id = projects[0]["id"]
    response = client.post("/api/incidents", json={
        "project_id": project_id,
        "title": "测试故障",
        "service": "api",
        "symptom": "timeout",
        "severity": "low",
    })
    assert response.status_code == 200
    assert all(item["project_id"] == project_id for item in client.get(f"/api/incidents?project_id={project_id}").json())


def test_project_repository_url_can_be_added_later():
    projects = client.get("/api/projects").json()
    project_id = projects[0]["id"]
    response = client.patch(f"/api/projects/{project_id}", json={
        "repo_url": "https://github.com/h1czvk0/project-atlas",
    })
    assert response.status_code == 200
    assert response.json()["repo_url"] == "https://github.com/h1czvk0/project-atlas"


def test_repository_url_change_resets_repository_context():
    project = client.post("/api/projects", json={
        "name": "Repository Reset Project",
        "slug": f"repository-reset-{uuid4().hex[:8]}",
        "repo_url": None,
    }).json()
    with SessionLocal() as db:
        row = db.get(Project, project["id"])
        row.repo_url = "https://github.com/example/old"
        row.repo_status = "ready"
        row.repo_last_commit = "abc123"
        row.repo_indexed_files = 3
        db.add(Document(name="old.py", file_type=".py", sha256=uuid4().hex, size_bytes=1, status="ready", source_type="repository_code", project_id=row.id))
        db.commit()

    response = client.patch(f"/api/projects/{project['id']}", json={"repo_url": None})
    assert response.status_code == 200
    payload = response.json()
    assert payload["repo_status"] == "not_imported"
    assert payload["repo_last_commit"] is None
    assert all(item["source_type"] != "repository_code" for item in client.get(f"/api/documents?project_id={project['id']}").json())
    client.delete(f"/api/projects/{project['id']}")


def test_system_status_does_not_expose_api_key():
    response = client.get("/api/system/status")
    assert response.status_code == 200
    assert "llm_configured" in response.json()
    assert "llm_reachable" in response.json()
    assert response.json()["llm_reachable"] is None
    assert "llm_api_key" not in response.json()


def test_session_can_be_deleted_and_metadata_is_compact():
    project_id = client.get("/api/projects").json()[0]["id"]
    response = client.post("/api/chat", json={
        "question": "有哪些文档？",
        "project_id": project_id,
    })
    assert response.status_code == 200
    session_id = response.json()["session_id"]
    messages = client.get(f"/api/sessions/{session_id}/messages").json()
    metadata = messages[-1]["metadata_json"]
    assert "answer" not in metadata
    assert metadata["answer_mode"] == "structured"
    deleted = client.delete(f"/api/sessions/{session_id}")
    assert deleted.status_code == 200
    assert client.get(f"/api/sessions/{session_id}/messages").status_code == 404


def test_workspace_can_be_deleted_with_related_data():
    project = client.post("/api/projects", json={
        "name": "Delete Test Project",
        "slug": "delete-test-project",
        "description": "删除测试",
        "repo_url": None,
    })
    if project.status_code == 409:
        project_id = next(item["id"] for item in client.get("/api/projects").json() if item["slug"] == "delete-test-project")
    else:
        assert project.status_code == 201
        project_id = project.json()["id"]

    upload = client.post(
        "/api/documents/upload",
        data={"project_id": project_id},
        files={"file": ("delete-test.md", b"temporary workspace content", "text/markdown")},
    )
    assert upload.status_code in (200, 409)
    response = client.delete(f"/api/projects/{project_id}")
    assert response.status_code == 200
    assert response.json() == {"deleted": project_id}
    assert all(item["id"] != project_id for item in client.get("/api/projects").json())
    assert client.get(f"/api/documents?project_id={project_id}").json() == []


def test_busy_workspace_cannot_be_deleted(monkeypatch):
    project = client.post("/api/projects", json={
        "name": "Busy Project",
        "slug": "busy-project",
        "description": "导入中",
        "repo_url": None,
    })
    project_id = project.json()["id"] if project.status_code == 201 else next(
        item["id"] for item in client.get("/api/projects").json() if item["slug"] == "busy-project"
    )
    monkeypatch.setattr("app.main.repository_import_running", lambda value: value == project_id)
    response = client.delete(f"/api/projects/{project_id}")
    assert response.status_code == 409
    with SessionLocal() as db:
        db.delete(db.get(Project, project_id))
        db.commit()


def test_same_file_is_isolated_between_workspaces(monkeypatch, tmp_path):
    monkeypatch.setattr("app.document_storage.settings.upload_dir", str(tmp_path))
    token = uuid4().hex[:8]
    project_ids = []
    document_ids = []
    storage_paths = []
    for index in range(2):
        project = client.post("/api/projects", json={
            "name": f"Storage Project {index}",
            "slug": f"storage-project-{token}-{index}",
            "description": "存储隔离测试",
            "repo_url": None,
        })
        assert project.status_code == 201
        project_id = project.json()["id"]
        project_ids.append(project_id)
        upload = client.post(
            "/api/documents/upload",
            data={"project_id": project_id},
            files={"file": ("shared.md", b"same content in two workspaces", "text/markdown")},
        )
        assert upload.status_code in (200, 409)
        with SessionLocal() as db:
            document = db.query(Document).filter_by(project_id=project_id, name="shared.md").first()
            document_ids.append(document.id)
            storage_paths.append(document.storage_path)

    assert storage_paths[0] != storage_paths[1]
    assert all(Path(path).is_file() for path in storage_paths)
    assert client.delete(f"/api/projects/{project_ids[0]}").status_code == 200
    assert not Path(storage_paths[0]).exists()
    assert Path(storage_paths[1]).is_file()
    assert client.post(f"/api/documents/{document_ids[1]}/reindex").status_code == 200
    assert client.delete(f"/api/projects/{project_ids[1]}").status_code == 200
