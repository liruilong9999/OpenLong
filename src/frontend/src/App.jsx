import { useEffect, useMemo, useState } from "react";
import { checkHealth, sendChatMessage } from "./api/client";
import ChatPanel from "./components/ChatPanel";
import AgentStatus from "./components/AgentStatus";
import MemoryView from "./components/MemoryView";

function App() {
  const [sessionId, setSessionId] = useState("");
  const [messages, setMessages] = useState([]);
  const [health, setHealth] = useState({ status: "checking" });

  useEffect(() => {
    // 页面加载时先探活后端，展示模型与连接状态。
    checkHealth()
      .then((payload) => setHealth(payload))
      .catch(() => setHealth({ status: "unreachable" }));
  }, []);

  const title = useMemo(() => {
    return health.model ? `OpenLong Dashboard (${health.model})` : "OpenLong Dashboard";
  }, [health]);

  const onSend = async (text) => {
    // 本地先追加用户消息，再请求后端并回写助手回复。
    const userMsg = { role: "user", content: text };
    setMessages((prev) => [...prev, userMsg]);

    const reply = await sendChatMessage(sessionId, text);
    setSessionId(reply.session_id);
    setMessages((prev) => [...prev, { role: "assistant", content: reply.reply }]);
  };

  return (
    <main className="layout">
      <header className="header">
        <h1>{title}</h1>
        <p>Scaffold stage: gateway + agent loop placeholders are active.</p>
      </header>

      <section className="panels">
        <AgentStatus health={health} sessionId={sessionId} />
        <ChatPanel messages={messages} onSend={onSend} />
        <MemoryView />
      </section>
    </main>
  );
}

export default App;
