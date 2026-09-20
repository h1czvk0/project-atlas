import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app


GOLDEN = ROOT / "data" / "evals" / "golden.jsonl"


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    client = TestClient(app)
    cases = [json.loads(line) for line in GOLDEN.read_text(encoding="utf-8").splitlines() if line.strip()]
    passed = 0
    details = []
    for case in cases:
        response = client.post("/api/chat", json={"question": case["question"], "project_id": 1})
        payload = response.json()
        intent_ok = payload.get("intent") == case["expected_intent"]
        tools_ok = all(tool in payload.get("used_tools", []) for tool in case["expected_tools"])
        ok = response.status_code == 200 and intent_ok and tools_ok
        passed += int(ok)
        details.append({"question": case["question"], "passed": ok, "actual_intent": payload.get("intent"), "actual_tools": payload.get("used_tools", [])})
    print(json.dumps({"passed": passed, "total": len(cases), "details": details}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
