import os
import shutil
import tempfile
from pathlib import Path


TEST_ROOT = Path(tempfile.mkdtemp(prefix="atlas-tests-"))
os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = f"sqlite:///{(TEST_ROOT / 'atlas.db').as_posix()}"
os.environ["UPLOAD_DIR"] = str(TEST_ROOT / "uploads")
os.environ["WORKSPACE_DIR"] = str(TEST_ROOT / "workspaces")
os.environ["LLM_BASE_URL"] = ""
os.environ["LLM_API_KEY"] = ""
os.environ["GITHUB_TOKEN"] = ""


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(TEST_ROOT, ignore_errors=True)
