# Project Atlas

帮助开发者更快理解陌生代码库。

当前版本：`v0.3.0`

Project Atlas 将项目文档、仓库历史、Issue 和架构说明整理成可检索的项目上下文，为新成员提供一个可以自托管的上手助手。项目面向小型团队和个人维护者，默认在本地运行，项目资料不会因为使用助手而自动发送到第三方 SaaS。

## 为什么需要它

开发者加入一个陌生项目时，最难的问题通常不是语法问题：

- 项目如何在本地启动？
- 登录或支付功能由哪个模块负责？
- 为什么要修改这个依赖？
- 目前还有哪些问题没有解决？
- 新成员应该先读哪些文档？

Atlas 根据项目资料回答这些问题，并展示使用到的来源文档或仓库上下文。

## 当前功能

- 创建相互隔离的项目 Workspace。
- 将公开 GitHub 仓库克隆到本地，并为每个 Workspace 独立保存代码快照。
- 后端 API 也支持传入本地 Git 仓库路径，复制快照后建立索引。
- 解析源码、README、配置、依赖清单、文件树和最近 50 条 Git 历史。
- 上传 Markdown、TXT、JSON 和 PDF 项目资料。
- 将公开 GitHub 仓库的 README、最近 Commit 和 Issue 导入项目 Workspace。
- 对文档进行分块、轻量向量化和混合检索。
- 基于项目证据回答问题，并展示来源片段。
- 根据项目上下文生成新成员上手路径。
- 在页面创建和切换项目，并同步关联的公开 GitHub 仓库。
- 通过只读工具查询项目任务和未关闭故障。
- 通过 SSE 返回 Agent 工具调用事件。
- 支持 SQLite 本地运行，也支持 Docker Compose + MySQL。

## 使用流程示例

```text
创建项目 Workspace
        ↓
导入 README / 上传架构说明 / 上传 Runbook
        ↓
提问：“项目如何启动？”
        ↓
Atlas 检索证据并标注来源
        ↓
提问：“新成员应该先阅读哪些文档？”
        ↓
Atlas 返回结构化上手路径
```

## 快速启动

以下命令请在仓库根目录执行。

```powershell
Copy-Item .env.example .env
```

这条命令只用于首次初始化：它把配置模板复制为本地 `.env`。如果 `.env` 已存在并且已经填写 API Key，不要再次执行，否则 PowerShell 会用模板覆盖现有配置。`.env` 已被 Git 忽略，不会提交到仓库。

如果 Docker Desktop 正在运行，可以直接启动完整服务：

```powershell
docker compose up --build
```

打开 http://localhost:5173，然后上传 `data/examples/getting-started.md` 或 `data/examples/payment-service-runbook.md`。

如果暂时不使用 Docker，也可以分别启动后端和前端。先打开一个 PowerShell 窗口启动后端：

Windows 本地启动后端：

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload
```

再打开第二个 PowerShell 窗口启动前端：

```powershell
Set-Location frontend
npm run dev
```

本地启动时访问 http://localhost:5173。默认使用 SQLite，不需要配置大模型 API Key 也可以体验文档索引和检索问答。

## 配置真实大模型

不配置 API Key 时，Atlas 仍然可以返回可解释的检索结果。需要使用真实的 OpenAI-compatible 模型时，在 `.env` 中填写：

```text
LLM_BASE_URL=https://your-provider.example/v1
LLM_API_KEY=your-key
LLM_MODEL=your-model
LLM_REASONING_EFFORT=auto
GITHUB_TOKEN=your-optional-github-token
GITHUB_CLONE_PROXY=https://gh-proxy.org
WORKSPACE_DIR=E:/program/agent
```

`GITHUB_TOKEN` 不是必填项。同步公开仓库时可以匿名访问 GitHub API；如果遇到请求次数限制，可以配置只读 Token 提高限额。真实 Token 只放在本地 `.env`，不要提交到仓库。

公开仓库克隆默认按照 [GH-Proxy GitHub 加速指南](https://gh-proxy.com/docs/github-accelerator) 通过 `GITHUB_CLONE_PROXY` 加速，实际地址形如 `https://gh-proxy.org/https://github.com/owner/repo.git`。设置为空字符串可恢复 GitHub 直连。该公共代理仅用于公开仓库，不要通过它发送私有仓库凭据。

`WORKSPACE_DIR` 用于指定仓库工作区的统一存放目录。Windows 的 `.env` 推荐写成 `E:/program/agent`；Atlas 会在其中按“项目名-ID”创建独立目录，例如 `E:/program/agent/slsc-2`。旧版 `REPOSITORY_DIR` 仍然兼容，但仅在未配置 `WORKSPACE_DIR` 时使用。

创建 Workspace 时填写仓库地址后，Atlas 会在后台自动完成克隆、源码解析、知识索引和 GitHub 动态同步，页面会显示当前阶段和进度。模型连接不会在打开页面时自动发起；点击“测试模型”才会进行一次最小请求。

`LLM_REASONING_EFFORT` 可设为 `auto`、`none`、`minimal`、`low`、`medium`、`high`、`xhigh` 或 `max`。也可在页面按次选择。若兼容服务不支持 `reasoning_effort`，Atlas 会自动移除该参数后重试。

## 主要接口

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/projects` | 获取项目 Workspace 列表 |
| POST | `/api/projects` | 创建项目 Workspace |
| DELETE | `/api/projects/{id}` | 删除 Workspace 及其文档、对话、索引和本地仓库快照 |
| POST | `/api/projects/{id}/sync-readme` | 导入公开 GitHub README |
| POST | `/api/projects/{id}/sync-context` | 导入公开 GitHub README、Commit 和 Issue |
| POST | `/api/projects/{id}/import-repository` | 克隆并索引完整仓库上下文 |
| POST | `/api/documents/upload` | 上传并索引项目资料 |
| GET | `/api/documents?project_id=1` | 获取某个项目的资料 |
| POST | `/api/chat` | 向 Agent 提问 |
| POST | `/api/chat/stream` | 获取 SSE 工具事件 |

## 系统架构

```text
Vue 3 → FastAPI API → 项目 Workspace
                         ├─ Git clone → 本地仓库快照
                         ├─ 程序解析源码 / 配置 / 依赖 / Git 历史
                         ├─ 文档和代码分块 → MySQL / SQLite
                         ├─ search_knowledge → 混合检索
                         ├─ query_project_data → 项目任务
                         ├─ query_incident_history → 未关闭故障
                         ├─ build_onboarding_plan → 新人上手路径
                         └─ sync_context → GitHub 公共 API
                                      ↓
                         OpenAI-compatible API（可选）
```

详细说明见 [架构说明](docs/architecture.md) 和 [接口说明](docs/api.md)。

## 开发检查

```powershell
cd backend
$env:PYTHONPATH='.'
..\.venv\Scripts\python.exe -m pytest -q
cd ..\frontend
npm run build
```

运行离线 Agent 评测：

```powershell
Set-Location backend
$env:PYTHONPATH='.'
..\.venv\Scripts\python.exe scripts\evaluate.py
```

## 后续计划

- [x] 项目 Workspace、切换和基于来源的问答
- [x] 导入公开 GitHub README、Commit 和 Issue
- [x] 项目任务和故障只读查询工具
- [x] 新成员上手路径工具
- [x] SSE 增量回答和 Markdown 渲染
- [x] 后端评测脚本和前后端 CI
- [x] 本地克隆并索引公开代码仓库
- [ ] 使用 LangGraph 表达复杂条件工作流
- [ ] 接入 Qdrant 或托管 embedding 服务
- [ ] 增加浏览器扩展，用于保存项目上下文

## 当前限制

这是一个本地优先的开源项目，不是生产级代码智能平台。仓库导入目前支持公开 GitHub 仓库，最多索引 500 个文本文件和 6MB 文本内容，并排除依赖目录、构建产物、锁文件及 `.env`。默认 embedding 实现强调轻量和可复现，暂不宣称生产环境准确率、用户数量或企业级 SLA。

## 开源许可

MIT License
