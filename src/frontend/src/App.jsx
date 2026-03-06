import { useEffect, useMemo, useRef, useState } from "react";
import { checkHealth, createChatSocket } from "./api/client";
import ChatPanel from "./components/ChatPanel";
import AgentStatus from "./components/AgentStatus";
import MemoryView from "./components/MemoryView";

function App() {
  const [sessionId, setSessionId] = useState("");
  const [messages, setMessages] = useState([]);
  const [health, setHealth] = useState({ status: "checking" });
  const [socketStatus, setSocketStatus] = useState("idle");
  const socketRef = useRef(null);

  useEffect(() => {
    checkHealth()
      .then((payload) => setHealth(payload))
      .catch(() => setHealth({ status: "unreachable" }));

    return () => {
      socketRef.current?.close();
    };
  }, []);

  const title = useMemo(() => {
    return health.model ? `OpenLong Dashboard (${health.model})` : "OpenLong Dashboard";
  }, [health]);

  const appendMessage = (message) => {
    setMessages((prev) => [...prev, message]);
  };

  const toEventMessage = (payload) => {
    const eventName = payload?.name || "event";
    const body = payload?.payload || {};

    if (eventName === "agent.execution.started") {
      return "agent: 正在处理请求...";
    }
    if (eventName === "tool.execution.completed") {
      return `tool: ${body.tool_name || "unknown"} 执行完成`;
    }
    if (eventName === "tool.execution.denied") {
      return `tool: ${body.tool_name || "unknown"} 被拦截`;
    }
    if (eventName === "memory.write.completed") {
      return "memory: 已写入记忆";
    }
    return `${eventName}`;
  };

  const ensureSocket = async (nextSessionId) => {
    if (socketRef.current && socketRef.current.sessionId === nextSessionId) {
      return socketRef.current;
    }

    socketRef.current?.close();
    const client = createChatSocket(nextSessionId, {
      onStatus: (status) => setSocketStatus(status),
      onMessage: (payload) => {
        if (payload.type === "chat.reply") {
          appendMessage({ role: "assistant", content: payload.reply });
          return;
        }

        if (payload.type === "event") {
          appendMessage({ role: "system", content: toEventMessage(payload) });
          return;
        }

        if (payload.type === "error") {
          appendMessage({ role: "system", content: `error: ${payload.error}` });
          return;
        }
      },
    });
    socketRef.current = client;
    await client.connect();
    return client;
  };

  const onSend = async (text) => {
    const nextSessionId = sessionId || crypto.randomUUID();
    if (!sessionId) {
      setSessionId(nextSessionId);
    }

    appendMessage({ role: "user", content: text });

    try {
      const client = await ensureSocket(nextSessionId);
      await client.sendChat(text);
    } catch (error) {
      appendMessage({ role: "system", content: `error: ${error.message}` });
    }
  };

  return (
    <main className="layout">
      <header className="header">
        <h1>{title}</h1>
        <p>Realtime mode: websocket events and final replies are shown live.</p>
      </header>

      <section className="panels">
        <AgentStatus
          health={{ ...health, status: health.status === "ok" ? `ok / ws:${socketStatus}` : health.status }}
          sessionId={sessionId}
        />
        <ChatPanel messages={messages} onSend={onSend} />
        <MemoryView />
      </section>
    </main>
  );
}

export default App;
