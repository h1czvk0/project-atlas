import httpx
from sqlalchemy.orm import Session
from .config import settings
from .models import Document, Incident, ProjectTask, ToolCall
from .rag import search


def _record_tool(db: Session, name: str, args: dict, output: dict, session_id: int | None = None):
    db.add(ToolCall(session_id=session_id, tool_name=name, input_json=args, output_json=output))


def query_document(db: Session, keyword: str) -> list[dict]:
    docs = db.query(Document).filter(Document.name.ilike(f"%{keyword}%")).all()
    return [{"id": doc.id, "name": doc.name, "status": doc.status, "chunks": doc.chunk_count} for doc in docs]


def summarize_content(text: str) -> str:
    lines = [line.strip(" -*#") for line in text.splitlines() if line.strip()]
    return "；".join(lines[:5])[:600] if lines else "没有可总结的内容。"


def query_project_data(db: Session, project_id: int = 1) -> list[dict]:
    tasks = db.query(ProjectTask).filter(ProjectTask.completed.is_(False)).order_by(ProjectTask.priority.desc()).all()
    return [{"id": task.id, "title": task.title, "priority": task.priority, "completed": task.completed} for task in tasks]


def query_incident_history(db: Session, keyword: str = "", project_id: int = 1) -> list[dict]:
    rows = db.query(Incident).filter(Incident.status == "open")
    if keyword:
        rows = rows.filter(Incident.symptom.ilike(f"%{keyword}%"))
    return [{"id": row.id, "title": row.title, "service": row.service, "severity": row.severity,
             "symptom": row.symptom, "status": row.status} for row in rows.order_by(Incident.created_at.desc()).limit(5)]


def _llm_answer(question: str, context: str) -> str | None:
    if not settings.llm_base_url or not settings.llm_api_key:
        return None
    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    prompt = (
        "你是一个严谨的中文技术文档助手。只能根据上下文回答；如果上下文没有依据，明确说不知道。"
        "回答末尾列出引用的文档名。\n\n上下文：\n" + context + "\n\n问题：" + question
    )
    try:
        response = httpx.post(url, headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                              json={"model": settings.llm_model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.2}, timeout=30)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except (httpx.HTTPError, KeyError, IndexError, TypeError):
        return None


def run_agent(db: Session, question: str, session_id: int | None = None, project_id: int = 1) -> dict:
    lowered = question.lower()
    if any(key in lowered for key in ("有哪些文档", "文档列表", "文件列表")):
        docs = query_document(db, "")
        output = {"documents": docs}
        _record_tool(db, "query_document", {"keyword": ""}, output, session_id)
        answer = "当前知识库共有 {} 份文档：{}".format(len(docs), "、".join(doc["name"] for doc in docs) or "暂无文档")
        return {"answer": answer, "intent": "document_query", "used_tools": ["query_document"], "sources": [], "confidence": "structured"}

    if any(key in lowered for key in ("总结", "摘要", "概括")):
        hits = search(db, question, 4, project_id)
        source_text = "\n".join(hit["content"] for hit in hits)
        summary = summarize_content(source_text)
        output = {"summary": summary, "source_count": len(hits)}
        _record_tool(db, "summarize_content", {"query": question}, output, session_id)
        return {"answer": summary, "intent": "summarize", "used_tools": ["search_knowledge", "summarize_content"], "sources": hits, "confidence": "supported" if hits else "insufficient"}

    if any(key in lowered for key in ("任务", "todo", "待办", "未完成")):
        tasks = query_project_data(db, project_id)
        output = {"tasks": tasks}
        _record_tool(db, "query_project_data", {"completed": False}, output, session_id)
        answer = "当前有 {} 个未完成任务：{}".format(len(tasks), "、".join(task["title"] for task in tasks) or "暂无")
        return {"answer": answer, "intent": "project_data_query", "used_tools": ["query_project_data"], "sources": [], "confidence": "structured"}

    if any(key in lowered for key in ("故障", "告警", "报错", "异常", "503", "500", "error")):
        incidents = query_incident_history(db, "", project_id)
        hits = search(db, question, 4, project_id)
        _record_tool(db, "query_incident_history", {"status": "open"}, {"incidents": incidents}, session_id)
        steps = ["确认影响范围和最近一次发布", "检查服务日志与依赖健康状态", "根据引用的 Runbook 执行回滚或限流", "记录处理结果并关闭事件"]
        evidence = "\n".join(f"《{hit['document_name']}》：{hit['content'][:160]}" for hit in hits[:2]) or "暂无匹配 Runbook"
        answer = "建议先按以下顺序排查：\n" + "\n".join(f"{idx + 1}. {step}" for idx, step in enumerate(steps)) + f"\n\n知识库证据：\n{evidence}"
        return {"answer": answer, "intent": "incident_triage", "used_tools": ["query_incident_history", "search_knowledge"], "sources": hits, "confidence": "supported" if hits else "insufficient", "incidents": incidents}

    hits = search(db, question, 4, project_id)
    output = {"hits": len(hits), "top_score": hits[0]["score"] if hits else 0}
    _record_tool(db, "search_knowledge", {"query": question, "top_k": 4}, output, session_id)
    if not hits or hits[0]["score"] < 0.08:
        answer = "当前知识库没有足够依据回答这个问题，请先上传相关文档。"
        confidence = "insufficient"
    else:
        context = "\n\n".join(f"[{hit['document_name']}] {hit['content']}" for hit in hits)
        answer = _llm_answer(question, context) or "\n".join(f"根据《{hit['document_name']}》：{hit['content'][:180]}" for hit in hits[:2])
        confidence = "supported"
    return {"answer": answer, "intent": "knowledge_qa", "used_tools": ["search_knowledge"], "sources": hits, "confidence": confidence}
