# API 摘要

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/health` | 进程健康检查 |
| GET | `/api/ready` | 数据库就绪检查 |
| GET | `/api/projects` | 项目 Workspace 列表 |
| POST | `/api/projects` | 创建项目 Workspace |
| POST | `/api/projects/{id}/sync-readme` | 导入公开 GitHub README |
| POST | `/api/documents/upload` | 上传并索引项目资料 |
| GET | `/api/documents?project_id=1` | 获取某个项目的资料 |
| POST | `/api/documents/{id}/reindex` | 重新建立索引 |
| POST | `/api/sessions` | 创建对话会话 |
| GET | `/api/sessions/{id}/messages` | 获取会话历史 |
| POST | `/api/chat` | 调用 Project Atlas Agent |
| POST | `/api/chat/stream` | 获取 SSE 工具事件 |
| GET | `/api/incidents` | 查询故障记录 |
| POST | `/api/incidents` | 创建故障记录 |

