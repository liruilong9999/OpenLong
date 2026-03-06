# OpenLong

一个参考 `OpenClaw` 思路实现的本地智能体项目，当前包含：

- Python `Gateway Runtime` / `Agent Runtime`
- 工作区、上下文、记忆、技能、工具系统
- FastAPI + WebSocket 后端
- React + Vite 仪表盘前端

## 快速启动

模型配置默认从 `doc/key.txt` 读取。

先安装后端依赖：

```bash
cd src/backend
python -m pip install -r requirements.txt
```

然后回到仓库根目录启动后端：

```bash
python start.py --reload
```

如果你想一起启动前端开发服务器：

```bash
python start.py --reload --frontend
```

如果默认端口已被旧的 `python/node` 进程占用，启动脚本会先尝试关闭占用进程，再继续启动。

如果只想从仓库根目录启动前端：

```bash
python start.py --frontend-only --frontend-command dev
```

默认地址：`http://127.0.0.1:8000`

## 前端

```bash
cd src/frontend
npm install
npm run dev
```

默认前端地址：`http://127.0.0.1:5173`

## 目录

- `src/backend`: 后端运行时与 API
- `src/frontend`: 仪表盘前端
- `src/shared`: 共享协议
- `doc/key.txt`: 模型配置
- `workspace`: 运行期工作区
