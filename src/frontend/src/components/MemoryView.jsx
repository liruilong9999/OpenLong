import { useEffect, useMemo, useState } from "react";
import { fetchMemoryDashboard } from "../api/client";

function formatType(type) {
  return String(type || "unknown").replaceAll("_", " ");
}

function MemoryView({ agentId = "main", refreshKey = 0 }) {
  const [state, setState] = useState({ status: "loading", data: null, error: "" });

  useEffect(() => {
    let disposed = false;

    const load = async () => {
      try {
        const data = await fetchMemoryDashboard(agentId);
        if (!disposed) {
          setState({ status: "ready", data, error: "" });
        }
      } catch (error) {
        if (!disposed) {
          setState({ status: "error", data: null, error: error.message });
        }
      }
    };

    load();
    const timer = window.setInterval(load, 8000);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [agentId, refreshKey]);

  const typeItems = useMemo(() => {
    return Object.entries(state.data?.by_type || {}).sort((left, right) => right[1] - left[1]);
  }, [state.data]);

  return (
    <section className="card">
      <h2>Memory</h2>
      <p className="hint">Agent: {agentId}</p>

      {state.status === "loading" && <p className="hint">Loading memory dashboard...</p>}
      {state.status === "error" && <p className="hint">error: {state.error}</p>}

      {state.data && (
        <>
          <div className="stat-grid">
            <div className="stat-card">
              <span className="stat-label">Entries</span>
              <strong>{state.data.entries}</strong>
            </div>
            <div className="stat-card">
              <span className="stat-label">Avg weight</span>
              <strong>{state.data.avg_weight}</strong>
            </div>
          </div>

          <div className="pill-row">
            {typeItems.length ? (
              typeItems.map(([type, count]) => (
                <span key={type} className="pill">
                  {formatType(type)} · {count}
                </span>
              ))
            ) : (
              <span className="pill">No memory yet</span>
            )}
          </div>

          <div className="memory-list">
            {state.data.recent_items?.length ? (
              state.data.recent_items.map((item) => (
                <article key={item.memory_id} className="memory-item">
                  <div className="memory-meta">
                    <strong>{formatType(item.memory_type)}</strong>
                    <span>score {item.score}</span>
                  </div>
                  <p>{item.content}</p>
                </article>
              ))
            ) : (
              <p className="hint">No recent memory records.</p>
            )}
          </div>
        </>
      )}
    </section>
  );
}

export default MemoryView;
