# API 摘要

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/health` | 进程健康检查 |
| GET | `/api/ready` | 数据库就绪检查 |
| GET | `/api/projects` | 获取项目工作区列表 |
| POST | `/api/projects` | 创建项目工作区 |
| PATCH | `/api/projects/{id}` | 更新项目名称、说明或仓库地址 |
| POST | `/api/projects/{id}/sync-readme` | 导入公开 GitHub README |
| POST | `/api/projects/{id}/sync-context` | 导入 README、最近 Commit 和 Issue |
| POST | `/api/projects/{id}/import-repository` | 克隆仓库并索引源码、配置和 Git 历史；可传 `local_path` 查询参数导入本地 Git 仓库 |
| GET | `/api/system/status` | 查询大模型和 GitHub Token 配置状态 |
| POST | `/api/documents/upload` | 上传并索引项目资料 |
| GET | `/api/documents?project_id=1` | 获取某个项目的资料 |
| POST | `/api/documents/{id}/reindex` | 重新建立索引 |
| POST | `/api/sessions` | 创建对话会话 |
| GET | `/api/sessions/{id}/messages` | 获取会话历史 |
| POST | `/api/chat` | 调用 Project Atlas 智能助手 |
| POST | `/api/chat/stream` | 获取 SSE 工具事件 |
| GET | `/api/incidents` | 查询故障记录 |
| POST | `/api/incidents` | 创建故障记录 |
