from pathlib import Path

from app.rag import chunk_text, cosine, embedding
from app.agent import _llm_payload, _source_excerpt, _source_markdown, summarize_content
import pytest
from app.github_sync import parse_repo_url
from app.repository_analyzer import RepositoryImportError, _candidate_files, _git_proxy_overrides, _read_source, _symbols, clone_repository, copy_local_repository


def test_chunk_text_has_overlap_and_content():
    chunks = chunk_text("a" * 1000, size=300, overlap=50)
    assert len(chunks) >= 3
    assert all(chunks)


def test_embedding_is_normalized():
    vector = embedding("FastAPI RAG Agent")
    assert round(cosine(vector, vector), 5) == 1


def test_summary_keeps_key_lines():
    assert "FastAPI" in summarize_content("# FastAPI\n\nVue 3 前端")


def test_source_excerpt_stops_at_complete_line():
    content = "# Runbook\n\n## 排查步骤\n\n1. 检查错误率。\n2. 检查数据库连接池。\n3. 使用回滚方案。"
    excerpt = _source_excerpt(content, limit=42)
    assert "#" not in excerpt
    assert not excerpt.endswith("3. 使")
    assert excerpt.endswith("……")


def test_source_markdown_marks_shortened_content():
    markdown = _source_markdown([{
        "document_name": "runbook.md",
        "source_url": None,
        "content": "# Runbook\n" + "这是完整的一行。\n" * 40,
    }])
    assert "**runbook.md**" in markdown
    assert markdown.endswith("……")


def test_parse_github_repo_url():
    assert parse_repo_url("https://github.com/h1czvk0/project-atlas") == ("h1czvk0", "project-atlas")


def test_parse_github_repo_url_rejects_other_hosts():
    with pytest.raises(ValueError):
        parse_repo_url("https://example.com/h1czvk0/project-atlas")


def test_repository_analyzer_filters_generated_and_secret_files(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "src" / "service.py").write_text("class PaymentService:\n    def charge(self):\n        return True\n", encoding="utf-8")
    (tmp_path / "node_modules" / "ignored.js").write_text("const ignored = true", encoding="utf-8")
    (tmp_path / ".env").write_text("API_KEY=do-not-index", encoding="utf-8")
    (tmp_path / "config.yml").write_text("api_key: visible-secret", encoding="utf-8")

    files, omitted = _candidate_files(tmp_path)
    relative = {path.relative_to(tmp_path).as_posix() for path in files}

    assert relative == {"src/service.py", "config.yml"}
    assert omitted == 0
    assert "class PaymentService" in _symbols(tmp_path / "src" / "service.py", _read_source(tmp_path / "src" / "service.py"))
    assert "visible-secret" not in _read_source(tmp_path / "config.yml")


def test_local_repository_requires_git_directory(tmp_path):
    with pytest.raises(RepositoryImportError):
        copy_local_repository(99, str(tmp_path))


def test_reasoning_effort_is_optional_in_llm_payload():
    automatic = _llm_payload("问题", "上下文", "auto")
    high = _llm_payload("问题", "上下文", "high")
    assert "reasoning_effort" not in automatic
    assert high["reasoning_effort"] == "high"


def test_dead_local_git_proxy_is_disabled(monkeypatch):
    class Result:
        stdout = "http://127.0.0.1:1"

    monkeypatch.setattr("app.repository_analyzer.subprocess.run", lambda *args, **kwargs: Result())
    monkeypatch.setattr("app.repository_analyzer.socket.create_connection", lambda *args, **kwargs: (_ for _ in ()).throw(OSError()))
    assert _git_proxy_overrides() == ["-c", "http.proxy=", "-c", "https.proxy="]


def test_clone_repository_uses_configured_accelerator(monkeypatch, tmp_path):
    commands = []
    monkeypatch.setattr("app.repository_analyzer.settings.repository_dir", str(tmp_path))
    monkeypatch.setattr("app.repository_analyzer.settings.github_clone_proxy", "https://gh-proxy.org/")
    monkeypatch.setattr("app.repository_analyzer._git_proxy_overrides", lambda: [])

    def fake_run(args, **kwargs):
        commands.append(args)
        Path(args[-1]).mkdir()
        return ""

    monkeypatch.setattr("app.repository_analyzer._run_git", fake_run)
    clone_repository(7, "https://github.com/h1czvk0/slsc.git")
    assert "https://gh-proxy.org/https://github.com/h1czvk0/slsc.git" in commands[0]
