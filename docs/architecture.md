# Project Atlas 架构说明

```text
Vue 3 项目界面
      ↓ JSON / SSE
FastAPI 应用
      ↓
项目 Workspace 边界
      ├─ 文档和分块 → MySQL / SQLite
      ├─ Git clone → Workspace 独立代码快照
      ├─ 确定性解析 → 文件树 / 语言 / 依赖 / 代码符号 / Git 历史
      ├─ README / Commit / Issue 导入 → GitHub REST API
      ├─ 混合检索 → 哈希向量 + 关键词匹配
      └─ Agent 工具
            ├─ search_knowledge：检索项目知识
            ├─ query_document：查询项目文档
            ├─ query_project_data：查询项目任务
            ├─ query_incident_history：查询未关闭故障
            ├─ summarize_content：总结检索内容
            └─ build_onboarding_plan：生成新人上手路径
                    ↓
          OpenAI-compatible Chat API（可选）
```

Workspace 是产品的数据边界：每一份上传的资料、Git commit 和 Issue 都属于一个项目。Atlas 可以同时解释代码库“现在是什么样”和“最近发生了什么变化”。

仓库解析分为两层：程序负责克隆、过滤文件、提取 Python AST / 常见语言符号、依赖和 Git 历史，保证结果可复现；大模型只读取 RAG 检索到的相关片段，用于跨文件解释和自然语言总结。源码不会在导入阶段逐文件发送给大模型。

创建包含仓库地址的 Workspace 后，后台任务依次执行克隆、解析、知识索引和 GitHub 动态同步；项目表保存阶段、进度和错误信息，前端轮询展示。若 Git 的全局配置指向未运行的本地代理，单次克隆会临时禁用该代理，不改写用户的 Git 配置。

上传文件和仓库解析产物按 Workspace 分目录保存，避免相同内容在不同项目间共享物理文件。删除文档、重新分析或删除 Workspace 时，只清理没有数据库引用的文件。

对话请求复用 Workspace 内的会话 ID，并携带最近消息作为大模型上下文。后端通过 SSE 实时发送读取上下文、意图识别、知识检索、工具调用、证据整理和回答生成等阶段事件；配置真实模型时继续转发文本增量，本地检索回退结果也使用同一事件协议。
