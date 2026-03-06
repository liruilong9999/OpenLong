const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
const DEFAULT_TIMEOUT_MS = 8000;


function toWebSocketBase(apiBase) {
  if (apiBase.startsWith("https://")) {
    return apiBase.replace("https://", "wss://");
  }
  if (apiBase.startsWith("http://")) {
    return apiBase.replace("http://", "ws://");
  }
  return apiBase;
}


export function resolveApiUrl(path) {
  if (!path) {
    return API_BASE;
  }
  if (/^https?:\/\//i.test(path)) {
    return path;
  }
  return `${API_BASE}${path.startsWith("/") ? path : `/${path}`}`;
}


async function requestJson(path, options = {}) {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, headers, ...rest } = options;
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${API_BASE}${path}`, {
      ...rest,
      headers: {
        "Content-Type": "application/json",
        ...headers,
      },
      signal: controller.signal,
    });

    if (!response.ok) {
      let detail = "请求失败";
      try {
        const payload = await response.json();
        detail = payload.detail || detail;
      } catch {
        detail = await response.text();
      }
      throw new Error(detail || `HTTP ${response.status}`);
    }

    return response.json();
  } catch (error) {
    if (error?.name === "AbortError") {
      throw new Error("请求超时，请检查后端是否已经正常启动");
    }
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
}


export async function checkHealth() {
  return requestJson("/health");
}


export async function fetchSessions() {
  return requestJson("/dashboard/sessions");
}


export async function createSession(agentId = "main") {
  return requestJson("/sessions", {
    method: "POST",
    body: JSON.stringify({ agent_id: agentId }),
  });
}


export async function fetchSessionHistory(sessionId, limit = 100) {
  return requestJson(`/sessions/${sessionId}/history?limit=${limit}`);
}


export async function uploadSessionAttachments({ sessionId, files, agentId = "main" }) {
  const formData = new FormData();
  for (const file of files) {
    formData.append("files", file);
  }
  formData.append("agent_id", agentId);

  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), 30000);

  try {
    const response = await fetch(`${API_BASE}/sessions/${sessionId}/attachments`, {
      method: "POST",
      body: formData,
      signal: controller.signal,
    });

    if (!response.ok) {
      let detail = "上传失败";
      try {
        const payload = await response.json();
        detail = payload.detail || detail;
      } catch {
        detail = await response.text();
      }
      throw new Error(detail || `HTTP ${response.status}`);
    }

    return response.json();
  } catch (error) {
    if (error?.name === "AbortError") {
      throw new Error("上传超时，请稍后重试");
    }
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
}


export async function sendChatMessage({ sessionId, message, agentId = "main", attachments = [] }) {
  return requestJson("/chat", {
    method: "POST",
    body: JSON.stringify({
      session_id: sessionId,
      agent_id: agentId,
      message,
      attachments,
    }),
    timeoutMs: 45000,
  });
}


export async function fetchMemoryDashboard(agentId = "main") {
  return requestJson(`/dashboard/memory/${agentId}`);
}


export async function fetchAgentContext(agentId = "main", forceRefresh = false) {
  return requestJson(`/agents/${agentId}/context?force_refresh=${String(forceRefresh)}`);
}


export async function fetchSkillsDashboard(agentId = "main") {
  return requestJson(`/dashboard/skills/${agentId}`);
}


export async function fetchSystemDashboard() {
  return requestJson("/dashboard/system");
}


export async function fetchToolApprovals(limit = 20) {
  return requestJson(`/tools/approvals?limit=${limit}`);
}


export async function approveToolApproval(approvalId) {
  return requestJson(`/tools/approvals/${approvalId}/approve`, {
    method: "POST",
    body: JSON.stringify({}),
    timeoutMs: 180000,
  });
}


export async function rejectToolApproval(approvalId, reason = "manual reject") {
  return requestJson(`/tools/approvals/${approvalId}/reject`, {
    method: "POST",
    body: JSON.stringify({ reason }),
    timeoutMs: 30000,
  });
}


export class ChatSocketClient {
  constructor(sessionId, handlers = {}, connectTimeoutMs = 5000) {
    this.sessionId = sessionId;
    this.handlers = handlers;
    this.connectTimeoutMs = connectTimeoutMs;
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
      let settled = false;
      const timer = window.setTimeout(() => {
        if (settled) {
          return;
        }
        settled = true;
        this.handlers.onStatus?.("error");
        this.socket?.close();
        reject(new Error("WebSocket 连接超时"));
      }, this.connectTimeoutMs);

      this.socket.addEventListener("open", () => {
        if (settled) {
          return;
        }
        settled = true;
        window.clearTimeout(timer);
        this.handlers.onStatus?.("connected");
        resolve();
      });

      this.socket.addEventListener("message", (event) => {
        try {
          const payload = JSON.parse(event.data);
          this.handlers.onMessage?.(payload);
        } catch {
          this.handlers.onMessage?.({ type: "error", error: "无法解析实时消息" });
        }
      });

      this.socket.addEventListener("close", () => {
        window.clearTimeout(timer);
        this.handlers.onStatus?.("closed");
        this.openPromise = null;
      });

      this.socket.addEventListener("error", () => {
        if (settled) {
          this.handlers.onStatus?.("error");
          return;
        }
        settled = true;
        window.clearTimeout(timer);
        this.handlers.onStatus?.("error");
        reject(new Error("WebSocket 连接失败"));
      });
    });

    return this.openPromise;
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
