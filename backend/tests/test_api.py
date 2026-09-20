from fastapi.testclient import TestClient
from app.main import app


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


def test_system_status_does_not_expose_api_key():
    response = client.get("/api/system/status")
    assert response.status_code == 200
    assert "llm_configured" in response.json()
    assert "llm_reachable" in response.json()
    assert response.json()["llm_reachable"] is None
    assert "llm_api_key" not in response.json()


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
