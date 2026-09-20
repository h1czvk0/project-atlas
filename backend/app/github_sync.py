from urllib.parse import urlparse
import base64
import httpx
from .config import settings


def parse_repo_url(repo_url: str) -> tuple[str, str]:
    parsed = urlparse(repo_url)
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if parsed.netloc != "github.com" or len(parts) < 2:
        raise ValueError("repo_url 必须是 github.com/owner/repo")
    return parts[0], parts[1].removesuffix(".git")


def _get_json(url: str):
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    response = httpx.get(url, headers=headers, timeout=20, follow_redirects=True)
    if response.status_code == 403 and response.headers.get("x-ratelimit-remaining") == "0":
        raise RuntimeError("GitHub API 请求次数已用完，请配置 GITHUB_TOKEN 后重试")
    response.raise_for_status()
    return response.json()


def fetch_context(repo_url: str, limit: int = 20) -> list[dict]:
    owner, repo = parse_repo_url(repo_url)
    base = f"https://api.github.com/repos/{owner}/{repo}"
    items: list[dict] = []

    readme = _get_json(f"{base}/readme")
    items.append({
        "kind": "github_readme",
        "name": f"{repo}-{readme.get('name', 'README.md')}",
        "url": readme.get("html_url", f"https://github.com/{owner}/{repo}"),
        "content": base64.b64decode(readme["content"]).decode("utf-8", errors="ignore"),
    })

    for commit in _get_json(f"{base}/commits?per_page={limit}"):
        message = commit.get("commit", {}).get("message", "").strip()
        items.append({
            "kind": "github_commit",
            "name": f"{repo}-commit-{commit.get('sha', '')[:7]}.md",
            "url": commit.get("html_url", ""),
            "content": f"# Commit {commit.get('sha', '')[:7]}\n\n作者：{commit.get('commit', {}).get('author', {}).get('name', '未知')}\n\n提交信息：{message}\n",
        })

    for issue in _get_json(f"{base}/issues?state=all&per_page={limit}"):
        if issue.get("pull_request"):
            continue
        items.append({
            "kind": "github_issue",
            "name": f"{repo}-issue-{issue.get('number')}.md",
            "url": issue.get("html_url", ""),
            "content": f"# Issue #{issue.get('number')}：{issue.get('title', '')}\n\n状态：{issue.get('state', '')}\n\n标签：{', '.join(label.get('name', '') for label in issue.get('labels', [])) or '无'}\n\n{issue.get('body') or '没有描述'}\n",
        })
    return items
