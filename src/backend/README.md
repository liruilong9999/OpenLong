# OpenLong Backend

## 当前能力

- `Gateway Runtime` 统一处理 API、会话、任务和事件
- `Agent Runtime` 负责 Prompt、Planner、工具循环和回复生成
- 工作区内自动维护 `AGENTS.md`、`TOOLS.md`、`HEARTBEAT.md`
- 首轮成功对话后自动完成 `BOOTSTRAP.md`
- 模型配置默认从仓库根目录 `doc/key.txt` 读取

## 启动

仓库根目录推荐：

```bash
python start.py --reload
```

需要联动前端时：

```bash
python start.py --reload --frontend
```

仅后端目录也可运行：

```bash
python -m app
```

## 测试

```bash
python -m pytest -q
```
