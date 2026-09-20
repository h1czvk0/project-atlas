import ast
import json
import re
import shutil
import subprocess
import uuid
from collections import Counter
from pathlib import Path

from .config import settings
from .github_sync import parse_repo_url


ALLOWED_SUFFIXES = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".vue", ".java", ".go", ".rs",
    ".php", ".rb", ".cs", ".kt", ".kts", ".md", ".rst", ".txt", ".json",
    ".toml", ".yaml", ".yml", ".ini", ".cfg", ".sql", ".sh", ".ps1",
    ".html", ".css", ".scss", ".graphql", ".proto",
}
SPECIAL_FILES = {"dockerfile", "makefile", "procfile", "gemfile", "rakefile"}
EXCLUDED_DIRS = {
    ".git", ".idea", ".vscode", ".venv", "venv", "env", "node_modules",
    "dist", "build", "target", "vendor", "coverage", ".next", ".nuxt",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
}
EXCLUDED_NAMES = {
    ".env", ".env.local", ".env.production", ".env.development", "package-lock.json",
    "pnpm-lock.yaml", "yarn.lock", "poetry.lock", "cargo.lock", "composer.lock",
}
LANGUAGES = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript", ".ts": "TypeScript",
    ".tsx": "TypeScript", ".vue": "Vue", ".java": "Java", ".go": "Go",
    ".rs": "Rust", ".php": "PHP", ".rb": "Ruby", ".cs": "C#", ".kt": "Kotlin",
    ".kts": "Kotlin", ".sql": "SQL", ".sh": "Shell", ".ps1": "PowerShell",
    ".html": "HTML", ".css": "CSS", ".scss": "SCSS", ".md": "Markdown",
    ".json": "JSON", ".toml": "TOML", ".yaml": "YAML", ".yml": "YAML",
}
SECRET_RE = re.compile(
    r"(?i)(password|passwd|secret|api[_-]?key|access[_-]?token|private[_-]?key)"
    r"(\s*[:=]\s*)([^\s,}\]]+)"
)


class RepositoryImportError(RuntimeError):
    pass


def _run_git(args: list[str], cwd: Path | None = None, timeout: int = 120) -> str:
    try:
        result = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        message = "未找到 Git，请先安装 Git" if isinstance(exc, FileNotFoundError) else "克隆仓库超时"
        raise RepositoryImportError(message) from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        raise RepositoryImportError(detail[-1] if detail else "Git 命令执行失败")
    return result.stdout.strip()


def _managed_path(path: Path, root: Path) -> Path:
    resolved_root = root.resolve()
    resolved = path.resolve()
    if resolved == resolved_root or resolved_root not in resolved.parents:
        raise RepositoryImportError("仓库存储路径不安全")
    return resolved


def _remove_tree(path: Path) -> None:
    def make_writable_and_retry(function, target, _error):
        Path(target).chmod(0o700)
        function(target)

    shutil.rmtree(path, onexc=make_writable_and_retry)


def clone_repository(project_id: int, repo_url: str) -> Path:
    owner, repo = parse_repo_url(repo_url)
    clone_url = f"https://github.com/{owner}/{repo}.git"
    root = Path(settings.repository_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = _managed_path(root / f"project-{project_id}", root)
    staging = _managed_path(root / f".project-{project_id}-{uuid.uuid4().hex}.tmp", root)
    try:
        _run_git(["clone", "--depth", "50", "--no-tags", clone_url, str(staging)])
        if target.exists():
            _remove_tree(target)
        staging.replace(target)
    except Exception:
        if staging.exists():
            _remove_tree(staging)
        raise
    return target


def copy_local_repository(project_id: int, source_path: str) -> Path:
    source = Path(source_path).expanduser().resolve()
    if not source.is_dir() or not (source / ".git").exists():
        raise RepositoryImportError("本地路径必须指向一个 Git 仓库目录")
    root = Path(settings.repository_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = _managed_path(root / f"project-{project_id}", root)
    staging = _managed_path(root / f".project-{project_id}-{uuid.uuid4().hex}.tmp", root)
    try:
        _run_git(["clone", "--no-hardlinks", "--no-tags", str(source), str(staging)])
        if target.exists():
            _remove_tree(target)
        staging.replace(target)
    except Exception:
        if staging.exists():
            _remove_tree(staging)
        raise
    return target


def _priority(path: Path) -> tuple[int, str]:
    name = path.name.lower()
    if name.startswith("readme"):
        return 0, path.as_posix()
    if name in {"pyproject.toml", "package.json", "requirements.txt", "dockerfile", "docker-compose.yml", "compose.yml"}:
        return 1, path.as_posix()
    if path.suffix.lower() in {".md", ".toml", ".yaml", ".yml", ".json"}:
        return 2, path.as_posix()
    return 3, path.as_posix()


def _candidate_files(repo_path: Path, max_files: int = 500, max_total_bytes: int = 6 * 1024 * 1024) -> tuple[list[Path], int]:
    candidates = []
    for path in repo_path.rglob("*"):
        relative = path.relative_to(repo_path)
        if not path.is_file() or any(part.lower() in EXCLUDED_DIRS for part in relative.parts):
            continue
        name = path.name.lower()
        if name in EXCLUDED_NAMES or name.startswith(".env."):
            continue
        if path.suffix.lower() not in ALLOWED_SUFFIXES and name not in SPECIAL_FILES:
            continue
        if len(relative.as_posix()) > 240:
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size == 0 or size > 180 * 1024:
            continue
        candidates.append(path)

    candidates.sort(key=lambda item: _priority(item.relative_to(repo_path)))
    selected = []
    total = 0
    for path in candidates:
        size = path.stat().st_size
        if len(selected) >= max_files or total + size > max_total_bytes:
            break
        selected.append(path)
        total += size
    return selected, max(0, len(candidates) - len(selected))


def _read_source(path: Path) -> str | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in raw:
        return None
    text = raw.decode("utf-8", errors="ignore").strip()
    if not text:
        return None
    return SECRET_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}<REDACTED>", text)


def _symbols(path: Path, text: str) -> list[str]:
    if path.suffix.lower() == ".py":
        try:
            tree = ast.parse(text)
            values = []
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    values.append(f"class {node.name}")
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    values.append(f"function {node.name}")
            return values[:40]
        except SyntaxError:
            return []
    pattern = re.compile(
        r"(?m)^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?"
        r"(class|function|interface|type|enum)\s+([A-Za-z_$][\w$]*)"
    )
    return [f"{kind} {name}" for kind, name in pattern.findall(text)[:40]]


def _dependency_summary(repo_path: Path) -> list[str]:
    dependencies = []
    package_json = repo_path / "package.json"
    if package_json.exists():
        try:
            payload = json.loads(package_json.read_text(encoding="utf-8"))
            names = [*payload.get("dependencies", {}), *payload.get("devDependencies", {})]
            dependencies.append("Node: " + ", ".join(names[:40]))
        except (OSError, json.JSONDecodeError):
            pass
    requirements = repo_path / "requirements.txt"
    if requirements.exists():
        names = []
        for line in requirements.read_text(encoding="utf-8", errors="ignore").splitlines():
            value = re.split(r"[<>=!~\[]", line.strip(), maxsplit=1)[0]
            if value and not value.startswith("#"):
                names.append(value)
        if names:
            dependencies.append("Python: " + ", ".join(names[:40]))
    return dependencies


def _git_history(repo_path: Path, limit: int = 50) -> tuple[str, str]:
    sha = _run_git(["rev-parse", "HEAD"], cwd=repo_path)
    log = _run_git([
        "log", f"-{limit}", "--date=short",
        "--pretty=format:%h%x09%ad%x09%an%x09%s",
    ], cwd=repo_path)
    lines = ["# Git 历史", "", "| Commit | 日期 | 作者 | 说明 |", "|---|---|---|---|"]
    for row in log.splitlines():
        parts = row.split("\t", 3)
        if len(parts) == 4:
            lines.append("| " + " | ".join(value.replace("|", "\\|") for value in parts) + " |")
    return sha, "\n".join(lines)


def build_repository_items(repo_path: Path, repo_url: str) -> tuple[list[dict], dict]:
    repo_path = repo_path.resolve()
    files, omitted = _candidate_files(repo_path)
    sha, history = _git_history(repo_path)
    base_url = repo_url.removesuffix(".git").rstrip("/")
    remote_source = base_url.startswith(("http://", "https://"))

    def source_url(relative: str = "") -> str | None:
        if not remote_source:
            return None
        return f"{base_url}/blob/{sha}/{relative}" if relative else f"{base_url}/tree/{sha}"
    language_counts: Counter[str] = Counter()
    indexed = []
    paths = []

    for path in files:
        text = _read_source(path)
        if text is None:
            continue
        relative = path.relative_to(repo_path).as_posix()
        language = LANGUAGES.get(path.suffix.lower(), "Text")
        language_counts[language] += 1
        paths.append(relative)
        symbols = _symbols(path, text)
        kind = "repository_document" if path.suffix.lower() in {".md", ".rst", ".txt"} else "repository_config" if _priority(Path(relative))[0] <= 2 and path.suffix.lower() in {".json", ".toml", ".yaml", ".yml", ".ini", ".cfg"} else "repository_code"
        structure = ", ".join(symbols) if symbols else "未检测到可导出的类或函数"
        content = f"# {relative}\n\n语言：{language}\n\n结构：{structure}\n\n## 文件内容\n\n{text}"
        indexed.append({
            "kind": kind,
            "name": relative,
            "url": source_url(relative),
            "content": content,
        })

    dependencies = _dependency_summary(repo_path)
    tree = "\n".join(f"- `{path}`" for path in paths[:250])
    language_text = "、".join(f"{name} {count}" for name, count in language_counts.most_common()) or "未识别"
    overview = (
        "# 仓库概览\n\n"
        f"- 仓库：{base_url}\n- 当前提交：`{sha}`\n- 已索引文件：{len(indexed)}\n"
        f"- 因数量或大小限制跳过：{omitted}\n- 语言分布：{language_text}\n\n"
        "## 依赖摘要\n\n" + ("\n".join(f"- {item}" for item in dependencies) or "- 未检测到依赖清单") +
        "\n\n## 文件树\n\n" + (tree or "- 没有可索引文件")
    )
    items = [{
        "kind": "repository_overview", "name": "仓库概览.md", "url": source_url(), "content": overview,
    }, {
        "kind": "repository_history", "name": "Git-历史.md", "url": f"{base_url}/commits/{sha}" if remote_source else None, "content": history,
    }, *indexed]
    return items, {
        "commit": sha,
        "indexed_files": len(indexed),
        "omitted_files": omitted,
        "languages": dict(language_counts),
    }
