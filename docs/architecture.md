# Project Atlas 架构说明

```text
Vue 3 项目界面
      ↓ JSON / SSE
FastAPI 应用
      ↓
项目 Workspace 边界
      ├─ 文档和分块 → MySQL / SQLite
      ├─ 公开 README 导入 → GitHub REST API
      ├─ 混合检索 → 哈希向量 + 关键词匹配
      └─ Agent 工具
            ├─ search_knowledge：检索项目知识
            ├─ query_document：查询项目文档
            ├─ query_project_data：查询项目任务
            ├─ query_incident_history：查询未关闭故障
            └─ summarize_content：总结检索内容
                    ↓
          OpenAI-compatible Chat API（可选）
```

Workspace 是产品的数据边界：每一份上传的资料都属于一个项目。后续会将 Git commit 和 Issue 也关联到同一个项目，让上手助手不仅能解释代码库“现在是什么样”，还能够解释“它为什么变成现在这样”。

