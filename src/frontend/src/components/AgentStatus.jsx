function AgentStatus({ health, sessionId }) {
  return (
    <section className="card">
      <h2>Agent Status</h2>
      <p><strong>Status:</strong> {health.status || "unknown"}</p>
      <p><strong>Provider:</strong> {health.provider || "n/a"}</p>
      <p><strong>Model:</strong> {health.model || "n/a"}</p>
      <p><strong>API Key Loaded:</strong> {health.key_configured || "false"}</p>
      <p><strong>Session:</strong> {sessionId || "(new)"}</p>
    </section>
  );
}

export default AgentStatus;
