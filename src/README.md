# Source Layout

- `backend/`: OpenLong 后端运行时、API、测试
- `frontend/`: React 仪表盘
- `shared/`: 共享 schema / contract

后端核心模块：

- `app/gateway/`: 会话、任务队列、模型路由、WebSocket
- `app/agent/`: Prompt、Planner、Loop、模型客户端
- `app/workspace/`: 工作区与运行时文档
- `app/memory/`: 记忆写入、检索、压缩、摘要
- `app/tools/`: 工具注册、权限、执行
- `app/skills/`: `SKILL.md` 加载与匹配
