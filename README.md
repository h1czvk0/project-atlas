# Project Atlas

Understand unfamiliar codebases faster.

Project Atlas turns project documentation, repository history, issues and architecture notes into a searchable project context for developers joining an unfamiliar codebase. It is designed for small teams and individual maintainers who want a reliable onboarding companion without sending their whole project to a third-party SaaS.

## Why this exists

When a developer joins a project, the difficult questions are usually not syntax questions:

- How do I start the project locally?
- Which module owns authentication or payments?
- Why was this dependency changed?
- What is still unresolved?
- Which documents should I read first?

Atlas answers these questions from project evidence and always shows the source document or repository context it used.

## What it does

- Create isolated project workspaces.
- Upload Markdown, TXT, JSON and PDF project documents.
- Import a public GitHub repository README into a workspace.
- Index documents with chunking, lightweight embeddings and hybrid retrieval.
- Ask grounded questions with source snippets.
- Generate a new-member onboarding path from project context.
- Query project tasks and open incidents through read-only tools.
- Stream Agent tool events over SSE.
- Run locally with SQLite or Docker Compose + MySQL.

## Example workflow

```text
Create a project workspace
        ↓
Import README / upload architecture notes / runbooks
        ↓
Ask: “How do I start this project?”
        ↓
Atlas retrieves evidence and cites the source
        ↓
Ask: “What should a new developer read first?”
        ↓
Atlas returns a structured onboarding path
```

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

Open http://localhost:5173 and upload `data/examples/getting-started.md` or `data/examples/payment-service-runbook.md`.

For local backend development on Windows:

```powershell
cd backend
..\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:PYTHONPATH='.'
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

## Optional model provider

Atlas works without an API key by returning explainable retrieval results. To enable a real OpenAI-compatible model, put these values in `.env`:

```text
LLM_BASE_URL=https://your-provider.example/v1
LLM_API_KEY=your-key
LLM_MODEL=your-model
```

## API highlights

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/projects` | List workspaces |
| POST | `/api/projects` | Create a workspace |
| POST | `/api/projects/{id}/sync-readme` | Import a public GitHub README |
| POST | `/api/documents/upload` | Upload and index a document |
| GET | `/api/documents?project_id=1` | List project documents |
| POST | `/api/chat` | Ask the Agent |
| POST | `/api/chat/stream` | Receive SSE tool events |

## Architecture

```text
Vue 3 → FastAPI API → Project Workspace
                         ├─ documents + chunks → MySQL / SQLite
                         ├─ search_knowledge → hybrid retrieval
                         ├─ query_project_data → project tasks
                         ├─ query_incident_history → open incidents
                         └─ sync_readme → GitHub public API
                                      ↓
                         OpenAI-compatible API (optional)
```

See [docs/architecture.md](docs/architecture.md) and [docs/api.md](docs/api.md) for details.

## Development checks

```powershell
cd backend
$env:PYTHONPATH='.'
..\.venv\Scripts\python.exe -m pytest -q
cd ..\frontend
npm run build
```

## Roadmap

- [x] Project workspaces and source-grounded Q&A
- [x] Public GitHub README import
- [x] Task and incident read-only tools
- [ ] Import commit history and Issues
- [ ] LangGraph onboarding workflow
- [ ] Qdrant / hosted embedding provider
- [ ] Browser extension for saving project context

## Limitations

This is a local-first open-source project, not a production code intelligence platform. The default embedding implementation is intentionally lightweight and reproducible. It does not claim production accuracy, user counts or enterprise SLA.

## License

MIT

