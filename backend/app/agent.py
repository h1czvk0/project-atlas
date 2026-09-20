import httpx
import json
import re
from sqlalchemy.orm import Session
from .config import settings
from .models import Document, Incident, ProjectTask, ToolCall
from .rag import search


def _progress(callback, key: str, label: str, detail: str = "", tool: str | None = None):
    if callback:
        callback({"key": key, "label": label, "detail": detail, "tool": tool})


def _record_tool(db: Session, name: str, args: dict, output: dict, session_id: int | None = None):
    db.add(ToolCall(session_id=session_id, tool_name=name, input_json=args, output_json=output))


def query_document(db: Session, keyword: str, project_id: int = 1) -> list[dict]:
    docs = db.query(Document).filter(Document.project_id == project_id, Document.name.ilike(f"%{keyword}%")).all()
    return [{"id": doc.id, "name": doc.name, "status": doc.status, "chunks": doc.chunk_count} for doc in docs]


def summarize_content(text: str) -> str:
    lines = [line.strip(" -*#") for line in text.splitlines() if line.strip()]
    return "；".join(lines[:5])[:600] if lines else "没有可总结的内容。"


def _source_excerpt(text: str, limit: int = 220) -> str:
    lines = []
    for raw_line in text.splitlines():
        line = re.sub(r"^\s*(?:#{1,6}|[-*+]|>)\s*", "", raw_line).strip()
        if line:
            lines.append(line)

    if not lines:
        return "暂无可展示的摘要。"

    selected = []
    for line in lines:
        candidate = "；".join([*selected, line])
        if len(candidate) > limit:
            break
        selected.append(line)

    if not selected:
        shortened = lines[0][:limit].rstrip("，,；;：:、 ")
        return f"{shortened}……" if len(lines[0]) > limit else shortened

    excerpt = "；".join(selected)
    return f"{excerpt}……" if len(selected) < len(lines) else excerpt


def _source_markdown(hits: list[dict]) -> str:
    if not hits:
        return "- 暂无匹配的项目资料。"
    lines = []
    for hit in hits[:3]:
        name = hit["document_name"]
        label = f"[{name}]({hit['source_url']})" if hit.get("source_url") else f"**{name}**"
        lines.append(f"- {label}：{_source_excerpt(hit['content'])}")
    return "\n".join(lines)


def query_project_data(db: Session, project_id: int = 1) -> list[dict]:
    tasks = db.query(ProjectTask).filter(ProjectTask.project_id == project_id, ProjectTask.completed.is_(False)).order_by(ProjectTask.priority.desc()).all()
    return [{"id": task.id, "title": task.title, "priority": task.priority, "completed": task.completed} for task in tasks]


def build_onboarding_plan(db: Session, project_id: int = 1) -> list[dict]:
    docs = db.query(Document).filter(Document.project_id == project_id, Document.status == "ready").order_by(Document.created_at.asc()).all()
    preferred = ("readme", "getting-started", "架构", "api", "runbook", "部署")
    ordered = sorted(docs, key=lambda doc: (next((idx for idx, key in enumerate(preferred) if key in doc.name.lower()), len(preferred)), doc.created_at))
    return [{"step": idx + 1, "document": doc.name, "reason": "项目入口与启动方式" if idx == 0 else "补充项目结构和运行细节"} for idx, doc in enumerate(ordered[:6])]


def query_incident_history(db: Session, keyword: str = "", project_id: int = 1) -> list[dict]:
    rows = db.query(Incident).filter(Incident.project_id == project_id, Incident.status == "open")
    if keyword:
        rows = rows.filter(Incident.symptom.ilike(f"%{keyword}%"))
    return [{"id": row.id, "title": row.title, "service": row.service, "severity": row.severity,
             "symptom": row.symptom, "status": row.status} for row in rows.order_by(Incident.created_at.desc()).limit(5)]


REASONING_VALUES = {"none", "minimal", "low", "medium", "high", "xhigh", "max"}


def _llm_payload(question: str, context: str, reasoning_effort: str | None = None, history: list[dict] | None = None) -> dict:
    prompt = (
        "你是 Project Atlas 的项目上下文助手。只能根据上下文回答，不能补写没有证据的事实。"
        "请只输出 Markdown，并严格使用以下结构：\n"
        "## 结论\n用 1-3 句话直接回答。\n\n"
        "## 依据\n使用无序列表列出来源和关键证据。\n\n"
        "## 下一步\n给出可执行的下一步；没有建议时写‘暂无’。\n\n"
        "如果证据不足，请在‘结论’中明确说明。不要输出 HTML、JSON 或思考过程。"
        "\n\n上下文：\n" + context + "\n\n问题：" + question
    )
    messages = [{"role": item["role"], "content": item["content"]} for item in (history or [])[-6:]]
    messages.append({"role": "user", "content": prompt})
    payload = {"model": settings.llm_model, "messages": messages}
    effort = reasoning_effort or settings.llm_reasoning_effort
    if effort in REASONING_VALUES:
        payload["reasoning_effort"] = effort
    return payload


def _llm_answer(
    question: str,
    context: str,
    reasoning_effort: str | None = None,
    history: list[dict] | None = None,
    on_delta=None,
) -> str | None:
    if not settings.llm_base_url or not settings.llm_api_key:
        return None
    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    payload = _llm_payload(question, context, reasoning_effort, history)
    try:
        if on_delta:
            payload["stream"] = True
            attempts = [payload]
            if "reasoning_effort" in payload:
                fallback = dict(payload)
                fallback.pop("reasoning_effort")
                attempts.append(fallback)
            for index, candidate in enumerate(attempts):
                with httpx.stream(
                    "POST", url, headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                    json=candidate, timeout=60,
                ) as response:
                    if response.status_code in {400, 422} and index + 1 < len(attempts):
                        continue
                    response.raise_for_status()
                    answer_parts = []
                    for line in response.iter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if not data or data == "[DONE]":
                            continue
                        chunk = json.loads(data)
                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        delta = choices[0].get("delta", {}).get("content")
                        if delta:
                            answer_parts.append(delta)
                            on_delta(delta)
                    return "".join(answer_parts) or None
        response = httpx.post(url, headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                              json=payload, timeout=60)
        if response.status_code in {400, 422} and "reasoning_effort" in payload:
            payload.pop("reasoning_effort")
            response = httpx.post(url, headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                                  json=payload, timeout=60)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except (httpx.HTTPError, json.JSONDecodeError, KeyError, IndexError, TypeError):
        return None


def check_llm_connection() -> dict:
    if not settings.llm_base_url or not settings.llm_api_key or not settings.llm_model:
        return {"configured": False, "reachable": False, "model": None, "message": "未配置大模型"}
    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    try:
        response = httpx.post(
            url,
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            json={
                "model": settings.llm_model,
                "messages": [{"role": "user", "content": "Reply with OK."}],
                "max_tokens": 1,
            },
            timeout=10,
        )
        response.raise_for_status()
        return {"configured": True, "reachable": True, "model": settings.llm_model, "message": "连接正常"}
    except httpx.HTTPError as exc:
        status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        message = f"连接失败（HTTP {status}）" if status else "连接失败"
        return {"configured": True, "reachable": False, "model": settings.llm_model, "message": message}


def run_agent(db: Session, question: str, session_id: int | None = None, project_id: int = 1, reasoning_effort: str | None = None, history: list[dict] | None = None, on_delta=None, on_progress=None) -> dict:
    lowered = question.lower()
    _progress(on_progress, "analyze", "正在理解问题", "识别意图并选择需要使用的项目工具")
    if any(key in lowered for key in ("有哪些文档", "文档列表", "文件列表")):
        _progress(on_progress, "documents", "正在读取文档目录", "查询当前 Workspace 的已索引资料", "query_document")
        docs = query_document(db, "", project_id)
        output = {"documents": docs}
        _record_tool(db, "query_document", {"keyword": ""}, output, session_id)
        answer = "## 文档概览\n当前知识库共有 **{}** 份文档。\n\n## 文档列表\n{}".format(
            len(docs), "\n".join(f"- **{doc['name']}** · {doc['status']} · {doc['chunks']} 个片段" for doc in docs) or "- 暂无文档"
        )
        return {"answer": answer, "intent": "document_query", "used_tools": ["query_document"], "sources": [], "confidence": "structured", "answer_mode": "structured"}

    if any(key in lowered for key in ("新人", "上手", "先阅读", "了解项目", "学习顺序")):
        _progress(on_progress, "onboarding", "正在生成阅读顺序", "按文档类型和项目入口组织上手路径", "build_onboarding_plan")
        plan = build_onboarding_plan(db, project_id)
        _record_tool(db, "build_onboarding_plan", {"project_id": project_id}, {"steps": plan}, session_id)
        lines = "\n".join(f"{item['step']}. **{item['document']}**：{item['reason']}" for item in plan) or "暂无足够项目资料，请先上传 README 或架构文档。"
        answer = f"## 新成员上手路径\n建议按以下顺序阅读：\n\n{lines}\n\n## 使用建议\n阅读每份资料后，尝试向 Atlas 提一个具体问题，确认自己理解了项目边界。"
        return {"answer": answer, "intent": "onboarding_plan", "used_tools": ["build_onboarding_plan"], "sources": [], "confidence": "structured" if plan else "insufficient", "answer_mode": "structured"}

    if any(key in lowered for key in ("总结", "摘要", "概括")):
        _progress(on_progress, "search", "正在检索项目知识", "计算问题与代码、文档片段的相关度", "search_knowledge")
        hits = search(db, question, 4, project_id)
        _progress(on_progress, "summarize", "正在整理检索证据", f"选取 {len(hits)} 个相关片段生成摘要", "summarize_content")
        source_text = "\n".join(hit["content"] for hit in hits)
        summary = summarize_content(source_text)
        output = {"summary": summary, "source_count": len(hits)}
        _record_tool(db, "summarize_content", {"query": question}, output, session_id)
        context = "\n\n".join(f"[{hit['document_name']}] {hit['content']}" for hit in hits)
        _progress(on_progress, "generate", "正在生成回答", "将检索证据发送给已配置的模型")
        model_answer = _llm_answer(question, context, reasoning_effort, history, on_delta)
        if not model_answer:
            _progress(on_progress, "fallback", "正在生成本地摘要", "模型未配置或请求失败，使用可解释的本地结果")
        answer = model_answer or f"## 摘要\n{summary}\n\n## 来源\n{_source_markdown(hits)}"
        return {"answer": answer, "intent": "summarize", "used_tools": ["search_knowledge", "summarize_content"], "sources": hits, "confidence": "supported" if hits else "insufficient", "answer_mode": "model" if model_answer else "local"}

    if any(key in lowered for key in ("任务", "todo", "待办", "未完成")):
        _progress(on_progress, "tasks", "正在查询项目任务", "读取当前 Workspace 的未完成任务", "query_project_data")
        tasks = query_project_data(db, project_id)
        output = {"tasks": tasks}
        _record_tool(db, "query_project_data", {"completed": False}, output, session_id)
        answer = "## 未完成任务\n当前共有 **{}** 个未完成任务。\n\n## 任务列表\n{}".format(
            len(tasks), "\n".join(f"- **{task['title']}** · 优先级：{task['priority']}" for task in tasks) or "- 暂无未完成任务"
        )
        return {"answer": answer, "intent": "project_data_query", "used_tools": ["query_project_data"], "sources": [], "confidence": "structured", "answer_mode": "structured"}

    if any(key in lowered for key in ("故障", "告警", "报错", "异常", "503", "500", "error")):
        _progress(on_progress, "incidents", "正在查询故障记录", "读取当前 Workspace 的未关闭故障", "query_incident_history")
        incidents = query_incident_history(db, "", project_id)
        _progress(on_progress, "search", "正在检索排障资料", "查找与错误现象相关的 Runbook 和代码片段", "search_knowledge")
        hits = search(db, question, 4, project_id)
        _record_tool(db, "query_incident_history", {"status": "open"}, {"incidents": incidents}, session_id)
        steps = ["确认影响范围和最近一次发布", "检查服务日志与依赖健康状态", "根据引用的 Runbook 执行回滚或限流", "记录处理结果并关闭事件"]
        incident_lines = "\n".join(f"- **{item['title']}** · {item['service']} · 严重级别：{item['severity']}" for item in incidents) or "- 暂无未关闭故障记录"
        answer = "## 建议结论\n建议先按以下顺序排查，不直接执行生产变更。\n\n## 排查步骤\n" + "\n".join(f"{idx + 1}. {step}" for idx, step in enumerate(steps)) + f"\n\n## 当前未关闭故障\n{incident_lines}\n\n## 知识库依据\n{_source_markdown(hits)}"
        return {"answer": answer, "intent": "incident_triage", "used_tools": ["query_incident_history", "search_knowledge"], "sources": hits, "confidence": "supported" if hits else "insufficient", "answer_mode": "structured", "incidents": incidents}

    _progress(on_progress, "search", "正在检索项目知识", "计算问题与代码、文档片段的相关度", "search_knowledge")
    hits = search(db, question, 4, project_id)
    output = {"hits": len(hits), "top_score": hits[0]["score"] if hits else 0}
    _record_tool(db, "search_knowledge", {"query": question, "top_k": 4}, output, session_id)
    if not hits or hits[0]["score"] < 0.08:
        _progress(on_progress, "evidence", "未找到足够证据", "建议补充项目资料或换一个更具体的问题")
        answer = "## 结论\n当前知识库没有足够依据回答这个问题。\n\n## 下一步\n请先上传 README、架构文档或 Runbook，再重新提问。"
        confidence = "insufficient"
        answer_mode = "local"
    else:
        _progress(on_progress, "evidence", "已找到相关证据", f"选取 {len(hits)} 个片段作为回答依据")
        context = "\n\n".join(f"[{hit['document_name']}] {hit['content']}" for hit in hits)
        _progress(on_progress, "generate", "正在生成回答", "模型将根据检索证据组织最终答案")
        model_answer = _llm_answer(question, context, reasoning_effort, history, on_delta)
        if not model_answer:
            _progress(on_progress, "fallback", "正在生成本地回答", "模型未配置或请求失败，返回可解释的检索结果")
        answer = model_answer or f"## 结论\n根据项目资料，最相关的内容来自 **{hits[0]['document_name']}**。\n\n## 依据\n{_source_markdown(hits)}\n\n## 下一步\n如果需要更具体的结论，请补充模块名、错误信息或运行环境。"
        confidence = "supported"
        answer_mode = "model" if model_answer else "local"
    return {"answer": answer, "intent": "knowledge_qa", "used_tools": ["search_knowledge"], "sources": hits, "confidence": confidence, "answer_mode": answer_mode}
