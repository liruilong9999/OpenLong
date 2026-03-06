const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

function toWebSocketBase(apiBase) {
  if (apiBase.startsWith("https://")) {
    return apiBase.replace("https://", "wss://");
  }
  if (apiBase.startsWith("http://")) {
    return apiBase.replace("http://", "ws://");
  }
  return apiBase;
}

export async function checkHealth() {
  const response = await fetch(`${API_BASE}/health`);
  if (!response.ok) {
    throw new Error("health check failed");
  }
  return response.json();
}

export class ChatSocketClient {
  constructor(sessionId, handlers = {}) {
    this.sessionId = sessionId;
    this.handlers = handlers;
    this.socket = null;
    this.openPromise = null;
  }

  connect() {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      return Promise.resolve();
    }
    if (this.openPromise) {
      return this.openPromise;
    }

    const wsBase = toWebSocketBase(API_BASE);
    this.socket = new WebSocket(`${wsBase}/ws/${this.sessionId}`);

    this.openPromise = new Promise((resolve, reject) => {
      this.socket.addEventListener("open", () => {
        this.handlers.onStatus?.("connected");
        resolve();
      });

      this.socket.addEventListener("message", (event) => {
        try {
          const payload = JSON.parse(event.data);
          this.handlers.onMessage?.(payload);
        } catch {
          this.handlers.onMessage?.({ type: "error", error: "invalid websocket payload" });
        }
      });

      this.socket.addEventListener("close", () => {
        this.handlers.onStatus?.("closed");
        this.openPromise = null;
      });

      this.socket.addEventListener("error", () => {
        this.handlers.onStatus?.("error");
        reject(new Error("websocket connection failed"));
      });
    });

    return this.openPromise;
  }

  async sendChat(message, agentId = null) {
    await this.connect();
    this.socket.send(
      JSON.stringify({
        message,
        agent_id: agentId,
      })
    );
  }

  close() {
    if (this.socket) {
      this.socket.close();
    }
    this.socket = null;
    this.openPromise = null;
  }
}

export function createChatSocket(sessionId, handlers = {}) {
  return new ChatSocketClient(sessionId, handlers);
}
