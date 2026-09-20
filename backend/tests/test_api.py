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
        assert project.status_code == 200
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
