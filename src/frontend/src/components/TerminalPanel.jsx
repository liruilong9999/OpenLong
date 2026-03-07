import { useState } from "react";


function TerminalPanel({
  sessionId,
  onRunCommand,
  approvals = [],
  approvalBusyId = "",
  onApprove,
  onReject,
  liveShellLines = [],
  shellLogs = [],
}) {
  const [command, setCommand] = useState("");
  const [cwd, setCwd] = useState("");
  const [cwdScope, setCwdScope] = useState("project");
  const [running, setRunning] = useState(false);

  const submit = async (event) => {
    event.preventDefault();
    const value = String(command || "").trim();
    if (!value || running) {
      return;
    }
    setRunning(true);
    try {
      await onRunCommand?.({ input: value, cwd, cwdScope });
      setCommand("");
    } finally {
      setRunning(false);
    }
  };

  return (
    <section className="ide-panel ide-terminal-panel">
      <div className="ide-panel-header">
        <div>
          <div className="ide-panel-title">终端 / 任务输出</div>
          <div className="ide-panel-subtitle">发起命令、查看实时输出、审批与历史</div>
        </div>
      </div>

      <form className="terminal-form" onSubmit={submit}>
        <input data-testid="terminal-command" value={command} onChange={(event) => setCommand(event.target.value)} placeholder="例如：pytest -q 或 npm install" />
        <input data-testid="terminal-cwd" value={cwd} onChange={(event) => setCwd(event.target.value)} placeholder="cwd（可选，例如 src/frontend）" />
        <select data-testid="terminal-cwd-scope" value={cwdScope} onChange={(event) => setCwdScope(event.target.value)}>
          <option value="project">Project</option>
          <option value="workspace">Workspace</option>
        </select>
        <button data-testid="terminal-run" type="submit" disabled={running}>{running ? "提交中" : "运行命令"}</button>
      </form>

      <div className="stack-list">
        {!!approvals.length && approvals.map((item) => (
          <div key={item.approval_id} className="mini-card">
            <div className="mini-card-title">待审批 · {item.category}</div>
            <div className="mini-card-text">
              <code>{item.command_preview}</code>
            </div>
            <div className="approval-action-row">
              <button data-testid="approval-approve" data-approval-id={item.approval_id} type="button" disabled={approvalBusyId === item.approval_id} onClick={() => onApprove?.(item.approval_id)}>
                {approvalBusyId === item.approval_id ? "处理中" : "批准"}
              </button>
              <button data-testid="approval-reject" data-approval-id={item.approval_id} type="button" disabled={approvalBusyId === item.approval_id} onClick={() => onReject?.(item.approval_id)}>
                拒绝
              </button>
            </div>
          </div>
        ))}

        {!!liveShellLines.length && (
          <div className="mini-card">
            <div className="mini-card-title">实时输出</div>
            <div className="shell-live-output" data-testid="terminal-live-output">
              {liveShellLines.map((line, index) => (
                <div key={`${line}-${index}`}>{line}</div>
              ))}
            </div>
          </div>
        )}

        {!!shellLogs.length && shellLogs.map((item) => (
          <div key={item.execution_id} className="mini-card">
            <div className="mini-card-title">
              {item.success ? "成功" : "失败"} · {item.result_data?.category || "shell"} · exit {String(item.result_data?.exit_code ?? "n/a")}
            </div>
            <div className="mini-card-text">
              <code>{item.args?.input || ""}</code>
              <div>cwd: {item.result_data?.cwd || item.args?.cwd || "project root"}</div>
              <div>{item.result_preview || item.denied_reason || "暂无输出"}</div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}


export default TerminalPanel;
