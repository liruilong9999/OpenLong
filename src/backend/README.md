# OpenLong Backend Scaffold

This folder contains the Python backend scaffold based on the architecture document.

## Key points
- Gateway Runtime as the entry point
- Agent Runtime with planner/prompt/tool loop placeholders
- Context/Memory/Skill/Tool/Workspace systems scaffolded
- Reserved extension modules: `channel` and `self_evolution`

## Run (after installing deps)
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Tests
```bash
pytest
```
