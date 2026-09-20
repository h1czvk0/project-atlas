# 更新日志

## v0.3.0

- 增加公开仓库本地克隆和 Workspace 独立代码快照。
- 增加源码、配置、依赖清单、文件树、代码符号和 Git 历史解析。
- 增加仓库分析状态、大模型连接状态和重新索引能力。
- 仓库解析使用确定性程序，大模型仅综合检索到的相关片段。
- 创建 Workspace 后自动导入仓库并显示阶段进度。
- 增加手动模型连接测试和按次推理强度选择。
- 检测失效的本地 Git 代理，并仅对当前克隆临时直连。

## v0.2.0

- 增加项目 Workspace 创建、切换和数据隔离。
- 支持导入公开 GitHub 仓库的 README、最近 Commit 和 Issue。
- 增加新人上手路径 Agent 工具。
- 增加 SSE 增量回答、工具事件和 Markdown 安全渲染。
- 增加离线评测脚本、API 集成测试和前端 CI。
- 增加旧版 SQLite / MySQL 数据表的轻量兼容迁移。
- 增加可选 `GITHUB_TOKEN` 配置和 GitHub API 限流提示。

## v0.1.0

- 完成文档上传、解析、分块和混合检索。
- 完成 FastAPI、Vue、MySQL / SQLite、Agent 工具和 OpenAI-compatible API 基础链路。
