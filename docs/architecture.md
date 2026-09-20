# Project Atlas architecture

```text
Vue 3 workspace UI
      ↓ JSON / SSE
FastAPI application
      ↓
Project workspace boundary
      ├─ documents and chunks → MySQL / SQLite
      ├─ public README import → GitHub REST API
      ├─ hybrid retrieval → hashed embedding + keyword overlap
      └─ Agent tools
            ├─ search_knowledge
            ├─ query_document
            ├─ query_project_data
            ├─ query_incident_history
            └─ summarize_content
                    ↓
          OpenAI-compatible Chat API (optional)
```

The workspace is the product boundary: every uploaded document belongs to a project. The next iteration will attach commit history and Issues to the same project, allowing the onboarding Agent to explain not only what the codebase says, but also how it has changed.

