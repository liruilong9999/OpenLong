import { Children, isValidElement, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  approveToolApproval,
  checkHealth,
  createChatSocket,
  createSession,
  fetchAgentContext,
  fetchMemoryDashboard,
  fetchSessionHistory,
  fetchSessions,
  fetchSkillsDashboard,
  fetchSystemDashboard,
  rejectToolApproval,
  resolveApiUrl,
  sendChatMessage,
  uploadSessionAttachments,
} from "./api/client";


const AGENT_ID = "main";
const SESSION_TITLE_STORAGE_KEY = "openlong.session_titles";


function loadStoredTitles() {
  if (typeof window === "undefined") {
    return {};
  }

  try {
    const raw = window.localStorage.getItem(SESSION_TITLE_STORAGE_KEY);
    if (!raw) {
      return {};
    }
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}


function saveStoredTitles(value) {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(SESSION_TITLE_STORAGE_KEY, JSON.stringify(value));
}


function sortSessions(items) {
  return [...items].sort((left, right) => {
    const leftTime = new Date(left.updated_at || left.created_at || 0).getTime();
    const rightTime = new Date(right.updated_at || right.created_at || 0).getTime();
    return rightTime - leftTime;
  });
}


function previewText(text, maxLength = 28) {
  const normalized = String(text || "").replace(/\s+/g, " ").trim();
  if (!normalized) {
    return "未命名对话";
  }
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, maxLength)}…`;
}


function formatTime(value) {
  if (!value) {
    return "刚刚";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "刚刚";
  }

  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}


function resolveHealthLabel(health) {
  if (health.status === "ok") {
    return "后端在线";
  }
  if (health.status === "unreachable") {
    return "后端不可用";
  }
  if (health.status === "error") {
    return "后端异常";
  }
  return "连接中";
}


function resolveSocketLabel(status) {
  const mapping = {
    idle: "未连接",
    connected: "实时已连接",
    closed: "实时已断开",
    error: "实时连接失败",
    connecting: "实时连接中",
  };
  return mapping[status] || status;
}


function contextBody(snapshot, filename) {
  return snapshot?.files?.[filename]?.body || snapshot?.files?.[filename]?.raw || "暂无内容";
}


function eventToText(payload) {
  const eventName = payload?.name || "event";
  const body = payload?.payload || {};

  if (eventName === "agent.execution.started") {
    return "正在分析";
  }
  if (eventName === "tool.execution.completed") {
    return `工具 ${body.tool_name || "unknown"} 已完成`;
  }
  if (eventName === "tool.execution.denied") {
    return `工具 ${body.tool_name || "unknown"} 被拦截`;
  }
  if (eventName === "tool.approval.created") {
    return `命令待审批：${body.command_preview || body.tool_name || "shell"}`;
  }
  if (eventName === "tool.approval.approved") {
    return `命令已批准：${body.tool_name || "shell"}`;
  }
  if (eventName === "tool.approval.rejected") {
    return `命令已拒绝：${body.tool_name || "shell"}`;
  }
  if (eventName === "tool.execution.stream") {
    return `${body.stream || "stdout"}: ${String(body.text || "").trim()}`;
  }
  if (eventName === "memory.write.completed") {
    return "记忆已更新";
  }
  if (eventName === "context.updated") {
    return "上下文已更新";
  }
  if (eventName === "skill.updated") {
    return "技能已更新";
  }
  if (eventName === "workspace.file_uploaded") {
    return `已上传 ${body.filename || "附件"}`;
  }
  return "";
}


function mergeActivity(items, nextItem) {
  const value = String(nextItem || "").trim();
  if (!value) {
    return items;
  }
  if (items.includes(value)) {
    return items;
  }
  return [...items, value].slice(-5);
}


const TEXT_ATTACHMENT_EXTENSIONS = new Set([
  ".txt",
  ".md",
  ".json",
  ".csv",
  ".log",
  ".py",
  ".js",
  ".ts",
  ".tsx",
  ".jsx",
  ".html",
  ".css",
  ".xml",
  ".yaml",
  ".yml",
  ".toml",
  ".ini",
  ".sh",
  ".ps1",
  ".bat",
  ".c",
  ".cpp",
  ".h",
  ".hpp",
  ".java",
  ".go",
  ".rs",
]);


function formatFileSize(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) {
    return "0 B";
  }

  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  if (bytes < 1024 * 1024 * 1024) {
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}


function fileExtension(name) {
  const index = String(name || "").lastIndexOf(".");
  return index >= 0 ? String(name).slice(index).toLowerCase() : "";
}


function isTextLikeFile(file) {
  const type = String(file?.type || "").toLowerCase();
  if (type.startsWith("text/")) {
    return true;
  }
  return TEXT_ATTACHMENT_EXTENSIONS.has(fileExtension(file?.name || ""));
}


function normalizeUploadedAttachment(item) {
  const type = item.content_type || item.type || "application/octet-stream";
  const previewUrl = item.preview_url || item.previewUrl ? resolveApiUrl(item.preview_url || item.previewUrl) : "";
  return {
    id: item.relative_path || item.absolute_path || `${item.filename || item.saved_name}-${crypto.randomUUID()}`,
    name: item.filename || item.saved_name || "upload.bin",
    savedName: item.saved_name || item.filename || "upload.bin",
    relativePath: item.relative_path || "",
    absolutePath: item.absolute_path || "",
    previewUrl,
    type,
    size: Number(item.size || 0),
    sizeLabel: formatFileSize(Number(item.size || 0)),
    uploadedAt: item.uploaded_at || "",
    category: String(type).split("/")[0] || "file",
    isImage: String(type).toLowerCase().startsWith("image/"),
  };
}


function buildOutgoingMessage(text, attachments) {
  const normalizedText = String(text || "").trim();
  if (normalizedText) {
    return normalizedText;
  }
  if (attachments.length) {
    return "请结合我上传的附件进行分析。";
  }
  return "";
}


function buildDisplayMessage(text, attachments) {
  const normalizedText = String(text || "").trim();
  if (normalizedText) {
    return normalizedText;
  }
  if (attachments.length === 1) {
    return `上传了 1 个附件：${attachments[0].name}`;
  }
  return `上传了 ${attachments.length} 个附件`;
}


function dedupeMemoryItems(items) {
  const seen = new Set();
  const output = [];

  for (const item of items || []) {
    const key = `${item.memory_type || "unknown"}::${item.content || ""}`;
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    output.push(item);
  }

  return output;
}


async function copyText(text) {
  await navigator.clipboard.writeText(String(text || ""));
}


function App() {
  const [health, setHealth] = useState({ status: "checking" });
  const [socketStatus, setSocketStatus] = useState("idle");
  const [sessions, setSessions] = useState([]);
  const [selectedSessionId, setSelectedSessionId] = useState("");
  const [messages, setMessages] = useState([]);
  const [searchText, setSearchText] = useState("");
  const [sending, setSending] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [globalHint, setGlobalHint] = useState("");
  const [activityItems, setActivityItems] = useState([]);
  const [copiedMessageKey, setCopiedMessageKey] = useState("");
  const [sessionTitles, setSessionTitles] = useState(() => loadStoredTitles());
  const [approvalBusyId, setApprovalBusyId] = useState("");
  const [liveShellLines, setLiveShellLines] = useState([]);
  const [inspector, setInspector] = useState({
    loading: true,
    error: "",
    context: null,
    memory: null,
    skills: null,
    system: null,
  });

  const socketRef = useRef(null);
  const messagesRef = useRef(null);

  useEffect(() => {
    saveStoredTitles(sessionTitles);
  }, [sessionTitles]);

  useEffect(() => {
    const initialize = async () => {
      await Promise.all([refreshHealth(), refreshSessions(true), refreshInspector()]);
    };

    initialize();

    return () => {
      socketRef.current?.close();
    };
  }, []);

  useEffect(() => {
    if (!messagesRef.current) {
      return;
    }
    messagesRef.current.scrollTop = messagesRef.current.scrollHeight;
  }, [messages]);

  const selectedSession = useMemo(
    () => sessions.find((item) => item.session_id === selectedSessionId) || null,
    [sessions, selectedSessionId]
  );

  const filteredSessions = useMemo(() => {
    const query = searchText.trim().toLowerCase();
    if (!query) {
      return sessions;
    }

    return sessions.filter((item) => {
      const title = sessionTitles[item.session_id] || "";
      return item.session_id.toLowerCase().includes(query) || title.toLowerCase().includes(query);
    });
  }, [searchText, sessionTitles, sessions]);

  const memoryItems = useMemo(
    () => dedupeMemoryItems(inspector.memory?.recent_items || []).slice(0, 4),
    [inspector.memory]
  );

  const hasConversation = messages.some((item) => item.role === "user" || item.role === "assistant");

  async function refreshHealth() {
    try {
      const payload = await checkHealth();
      setHealth(payload);
    } catch (error) {
      setHealth({ status: "unreachable", error: error.message });
    }
  }

  async function refreshInspector() {
    try {
      const [context, memory, skills, system] = await Promise.all([
        fetchAgentContext(AGENT_ID),
        fetchMemoryDashboard(AGENT_ID),
        fetchSkillsDashboard(AGENT_ID),
        fetchSystemDashboard(),
      ]);

      setInspector({
        loading: false,
        error: "",
        context,
        memory,
        skills,
        system,
      });
    } catch (error) {
      setInspector((current) => ({
        ...current,
        loading: false,
        error: error.message,
      }));
    }
  }

  async function refreshSessions(autoSelect = false) {
    try {
      const data = await fetchSessions();
      const sorted = sortSessions(data);
      setSessions(sorted);

      if (autoSelect && !selectedSessionId && sorted.length > 0) {
        await openSession(sorted[0].session_id);
      }
    } catch (error) {
      setGlobalHint(`读取会话失败：${error.message}`);
    }
  }

  async function ensureSocket(sessionId) {
    if (!sessionId) {
      return null;
    }

    if (socketRef.current && socketRef.current.sessionId === sessionId) {
      try {
        await socketRef.current.connect();
        return socketRef.current;
      } catch (error) {
        setSocketStatus("error");
        setGlobalHint(`实时连接失败：${error.message}`);
        return null;
      }
    }

    setSocketStatus("connecting");
    socketRef.current?.close();
    const client = createChatSocket(sessionId, {
      onStatus: (status) => setSocketStatus(status),
      onMessage: (payload) => {
        if (payload.type === "event") {
          if (payload.name === "tool.execution.stream") {
            const stream = payload?.payload?.stream || "stdout";
            const text = String(payload?.payload?.text || "").trim();
            if (text) {
              setLiveShellLines((current) => [...current, `[${stream}] ${text}`].slice(-24));
              setActivityItems((current) => mergeActivity(current, `${stream}: ${text}`));
            }
            return;
          }
          const text = eventToText(payload);
          if (!text) {
            return;
          }
          setActivityItems((current) => mergeActivity(current, text));
          void refreshInspector();
          return;
        }

        if (payload.type === "error") {
          setGlobalHint(`实时消息异常：${payload.error}`);
        }
      },
    });

    socketRef.current = client;

    try {
      await client.connect();
      return client;
    } catch (error) {
      setSocketStatus("error");
      setGlobalHint(`实时连接失败：${error.message}`);
      return null;
    }
  }

  async function openSession(sessionId) {
    if (!sessionId) {
      return;
    }

    setSelectedSessionId(sessionId);
    setLoadingHistory(true);
    setGlobalHint("");
    setActivityItems([]);
    setLiveShellLines([]);

    try {
      const history = await fetchSessionHistory(sessionId, 100);
      setMessages(history.map((item) => ({
        role: item.role,
        content: item.content,
        attachments: Array.isArray(item.attachments)
          ? item.attachments.map((attachment) => normalizeUploadedAttachment(attachment))
          : [],
        timestamp: item.timestamp,
      })));

      const firstUserMessage = history.find((item) => item.role === "user")?.content;
      if (firstUserMessage) {
        setSessionTitles((current) => ({
          ...current,
          [sessionId]: current[sessionId] || previewText(firstUserMessage),
        }));
      }

      await ensureSocket(sessionId);
      await refreshInspector();
    } catch (error) {
      setMessages([]);
      setGlobalHint(`加载会话失败：${error.message}`);
    } finally {
      setLoadingHistory(false);
    }
  }

  async function createNewConversation() {
    setGlobalHint("");

    try {
      const snapshot = await createSession(AGENT_ID);
      const sessionId = snapshot.session_id;
      setSelectedSessionId(sessionId);
      setMessages([]);
      setLiveShellLines([]);
      setSessions((current) => sortSessions([snapshot, ...current.filter((item) => item.session_id !== sessionId)]));
      await ensureSocket(sessionId);
    } catch (error) {
      setGlobalHint(`创建会话失败：${error.message}`);
    }
  }

  async function ensureActiveSession() {
    if (selectedSessionId) {
      return selectedSessionId;
    }

    const snapshot = await createSession(AGENT_ID);
    const sessionId = snapshot.session_id;
    setSelectedSessionId(sessionId);
    setSessions((current) => sortSessions([snapshot, ...current.filter((item) => item.session_id !== sessionId)]));
    setMessages([]);
    setLiveShellLines([]);
    return sessionId;
  }

  async function handleApproveApproval(approvalId) {
    setApprovalBusyId(approvalId);
    try {
      const payload = await approveToolApproval(approvalId);
      const resultText = payload?.result?.content || payload?.decision_reason || "命令已执行";
      setGlobalHint(`已批准命令：${resultText}`);
      await refreshInspector();
    } catch (error) {
      setGlobalHint(`批准失败：${error.message}`);
    } finally {
      setApprovalBusyId("");
    }
  }

  async function handleRejectApproval(approvalId) {
    setApprovalBusyId(approvalId);
    try {
      await rejectToolApproval(approvalId, "manual reject from web");
      setGlobalHint("已拒绝命令审批");
      await refreshInspector();
    } catch (error) {
      setGlobalHint(`拒绝失败：${error.message}`);
    } finally {
      setApprovalBusyId("");
    }
  }

  async function uploadFilesForSession(files) {
    const fileList = Array.from(files || []);
    if (!fileList.length) {
      return [];
    }

    const sessionId = await ensureActiveSession();
    const payload = await uploadSessionAttachments({
      sessionId,
      files: fileList,
      agentId: AGENT_ID,
    });
    await Promise.all([refreshSessions(false), refreshInspector()]);
    return (payload.items || []).map((item) => normalizeUploadedAttachment(item));
  }

  async function handleSend(payload) {
    const text = typeof payload === "string" ? payload : payload?.text || "";
    const attachments = Array.isArray(payload?.attachments) ? payload.attachments : [];
    const outgoingMessage = buildOutgoingMessage(text, attachments);
    const displayMessage = buildDisplayMessage(text, attachments);

    let sessionId = selectedSessionId;

    if (!sessionId) {
      try {
        sessionId = await ensureActiveSession();
      } catch (error) {
        setGlobalHint(`创建会话失败：${error.message}`);
        return;
      }
    }

    const firstUserTurn = !messages.some((item) => item.role === "user");
    const now = new Date().toISOString();

    setSending(true);
    setGlobalHint("");
    setActivityItems([]);
    setMessages((current) => [
      ...current,
      {
        role: "user",
        content: displayMessage,
        attachments,
        timestamp: now,
      },
    ]);
    setSessionTitles((current) => ({
      ...current,
      [sessionId]: current[sessionId] || previewText(displayMessage),
    }));

    await ensureSocket(sessionId);

    try {
      const result = await sendChatMessage({
        sessionId,
        message: outgoingMessage,
        agentId: AGENT_ID,
        attachments: attachments.map((item) => ({
          filename: item.name,
          saved_name: item.savedName,
          relative_path: item.relativePath,
          absolute_path: item.absolutePath,
          preview_url: item.previewUrl,
          content_type: item.type,
          size: item.size,
        })),
      });

      setMessages((current) => [
        ...current,
        {
          role: "assistant",
          content: result.reply,
          timestamp: new Date().toISOString(),
        },
      ]);
      setActivityItems([]);

      if (firstUserTurn) {
        setSessionTitles((current) => ({
          ...current,
          [sessionId]: current[sessionId] || previewText(displayMessage),
        }));
      }

      await Promise.all([refreshSessions(false), refreshInspector(), refreshHealth()]);
    } catch (error) {
      setMessages((current) => [
        ...current,
        {
          role: "system",
          content: `系统：发送失败，${error.message}`,
          timestamp: new Date().toISOString(),
        },
      ]);
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar-shell">
        <div className="sidebar-top">
          <div className="brand-mark">OL</div>
          <button className="primary-action" onClick={createNewConversation}>
            ＋ 新对话
          </button>
        </div>

        <div className="shortcut-list">
          <button className="shortcut-item" onClick={() => refreshSessions(false)}>
            <span className="shortcut-icon">⌕</span>
            <span>刷新会话</span>
          </button>
          <div className="shortcut-item static">
            <span className="shortcut-icon">🧠</span>
            <span>记忆 {inspector.memory?.entries ?? 0}</span>
          </div>
          <div className="shortcut-item static">
            <span className="shortcut-icon">🛠</span>
            <span>技能 {inspector.skills?.count ?? 0}</span>
          </div>
          <div className="shortcut-item static">
            <span className="shortcut-icon">⌂</span>
            <span>工作区 {AGENT_ID}</span>
          </div>
        </div>

        <div className="sidebar-search">
          <span>⌕</span>
          <input
            value={searchText}
            onChange={(event) => setSearchText(event.target.value)}
            placeholder="搜索会话"
          />
        </div>

        <div className="sidebar-title">你的对话</div>
        <div className="conversation-list">
          {filteredSessions.length === 0 && (
            <div className="sidebar-empty">还没有会话，点击“新对话”开始。</div>
          )}

          {filteredSessions.map((item) => (
            <button
              key={item.session_id}
              className={`conversation-item ${item.session_id === selectedSessionId ? "active" : ""}`}
              onClick={() => openSession(item.session_id)}
            >
              <div className="conversation-item-title">
                {sessionTitles[item.session_id] || `会话 ${item.session_id.slice(0, 8)}`}
              </div>
              <div className="conversation-item-meta">
                <span>{formatTime(item.updated_at || item.created_at)}</span>
                <span>{item.message_count || 0} 条</span>
              </div>
            </button>
          ))}
        </div>
      </aside>

      <main className="workspace-shell">
        <header className="workspace-topbar">
          <div>
            <div className="workspace-title">OpenLong</div>
            <div className="workspace-subtitle">
              {selectedSession ? (sessionTitles[selectedSession.session_id] || selectedSession.session_id) : "开始一段新的对话"}
            </div>
          </div>

          <div className="status-group">
            <span className={`status-pill ${health.status === "ok" ? "ok" : "warn"}`}>
              {resolveHealthLabel(health)}
            </span>
            <span className={`status-pill ${socketStatus === "connected" ? "ok" : "neutral"}`}>
              {resolveSocketLabel(socketStatus)}
            </span>
            <span className="status-pill neutral">模型 {health.model || "未加载"}</span>
          </div>
        </header>

        <section className={`chat-stage ${hasConversation ? "with-history" : "empty"}`}>
          {!hasConversation && !loadingHistory ? (
            <div className="welcome-panel">
              <div className="welcome-title">今天有什么计划？</div>
              <div className="welcome-subtitle">你可以直接提问、写任务、让它调用工具，或者查看右侧的上下文信息。</div>
            </div>
          ) : (
            <div className="message-scroll" ref={messagesRef}>
              {loadingHistory && <div className="panel-hint">正在加载会话记录…</div>}
              {!!activityItems.length && (
                <div className="activity-line">思考中：{activityItems.join(" · ")}</div>
              )}

              {messages.map((item, index) => (
                <div key={`${item.role}-${index}-${item.timestamp || ""}`} className={`message-row ${item.role}`}>
                  <div className={`message-bubble ${item.role}`}>
                    <div className="message-head">
                      <div className="message-role">
                        {item.role === "user" ? "你" : item.role === "assistant" ? "OpenLong" : "系统"}
                      </div>
                      {item.role === "assistant" && (
                        <button
                          className="message-copy-button"
                          type="button"
                          onClick={async () => {
                            await copyText(item.content);
                            const key = `${index}-${item.timestamp || ""}`;
                            setCopiedMessageKey(key);
                            window.setTimeout(() => {
                              setCopiedMessageKey((current) => (current === key ? "" : current));
                            }, 1500);
                          }}
                        >
                          {copiedMessageKey === `${index}-${item.timestamp || ""}` ? "已复制" : "复制回复"}
                        </button>
                      )}
                    </div>
                    <div className="message-content">
                      <MarkdownMessage content={item.content} />
                    </div>
                    {!!item.attachments?.length && (
                      <div className="message-attachments">
                        {item.attachments.map((attachment) => (
                          <div key={attachment.id} className="message-attachment-chip">
                            {attachment.isImage && attachment.previewUrl && (
                              <img
                                className="message-attachment-preview"
                                src={attachment.previewUrl}
                                alt={attachment.name}
                                loading="lazy"
                              />
                            )}
                            <div className="message-attachment-name">{attachment.name}</div>
                            <div className="message-attachment-meta">
                              {attachment.type || "unknown"} · {attachment.sizeLabel}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                    <div className="message-time">{formatTime(item.timestamp)}</div>
                  </div>
                </div>
              ))}
            </div>
          )}

          <ChatComposer
            sending={sending}
            onSend={handleSend}
            onUploadFiles={uploadFilesForSession}
            sessionId={selectedSessionId}
          />
          {globalHint && <div className="global-hint">{globalHint}</div>}
        </section>
      </main>

      <aside className="inspector-shell">
        <div className="inspector-header">
          <div className="inspector-title">运行面板</div>
          <div className="inspector-subtitle">基于当前后端接口实时读取</div>
        </div>

        <InspectorSection title="技能查看">
          {inspector.loading && <div className="panel-hint">正在加载…</div>}
          {inspector.error && <div className="panel-hint error">{inspector.error}</div>}
          {!inspector.loading && !inspector.error && (
            <>
              <div className="metric-row">
                <span>技能数</span>
                <strong>{inspector.skills?.count ?? 0}</strong>
              </div>
              {(inspector.skills?.skills || []).slice(0, 4).map((skill) => (
                <div key={skill.skill_id} className="mini-card">
                  <div className="mini-card-title">{skill.name}</div>
                  <div className="mini-card-text">{skill.description || "暂无说明"}</div>
                  {!!skill.triggers?.length && <div className="mini-tags">触发词：{skill.triggers.join("、")}</div>}
                </div>
              ))}
              {!(inspector.skills?.skills || []).length && <div className="panel-hint">当前还没有自定义技能。</div>}
            </>
          )}
        </InspectorSection>

        <InspectorSection title="记忆">
          {inspector.loading && <div className="panel-hint">正在加载…</div>}
          {!inspector.loading && inspector.memory && (
            <>
              <div className="metric-grid">
                <div className="metric-box">
                  <span>条目</span>
                  <strong>{inspector.memory.entries}</strong>
                </div>
                <div className="metric-box">
                  <span>平均权重</span>
                  <strong>{inspector.memory.avg_weight}</strong>
                </div>
              </div>
              <div className="mini-tags">类型：{Object.keys(inspector.memory.by_type || {}).join("、") || "暂无"}</div>
              <div className="stack-list">
                {memoryItems.map((item) => (
                  <div key={item.memory_id} className="mini-card">
                    <div className="mini-card-title">{item.memory_type}</div>
                    <div className="mini-card-text"><RichMarkdownText content={item.content} /></div>
                  </div>
                ))}
              </div>
            </>
          )}
        </InspectorSection>

        <InspectorSection title="用户（USER.md）">
          <div className="context-block"><RichMarkdownText content={contextBody(inspector.context, "USER.md")} /></div>
        </InspectorSection>

        <InspectorSection title="OpenLong（SOUL.md）">
          <div className="context-block"><RichMarkdownText content={contextBody(inspector.context, "SOUL.md")} /></div>
        </InspectorSection>

        <InspectorSection title="其它（运行信息）">
          <div className="metric-row"><span>会话</span><strong>{sessions.length}</strong></div>
          <div className="metric-row"><span>当前会话</span><strong>{selectedSessionId ? selectedSessionId.slice(0, 8) : "未选择"}</strong></div>
          <div className="metric-row"><span>API Key</span><strong>{String(health.key_configured || false)}</strong></div>
          <div className="metric-row"><span>任务队列</span><strong>{inspector.system?.task_queue?.total ?? 0}</strong></div>
          <div className="metric-row"><span>待审批命令</span><strong>{inspector.system?.tool_approvals?.stats?.pending ?? 0}</strong></div>
          <div className="mini-card">
            <div className="mini-card-title">RULES.md</div>
            <div className="mini-card-text"><RichMarkdownText content={previewText(contextBody(inspector.context, "RULES.md"), 90)} /></div>
          </div>
          <div className="mini-card">
            <div className="mini-card-title">STYLE.md</div>
            <div className="mini-card-text"><RichMarkdownText content={previewText(contextBody(inspector.context, "STYLE.md"), 90)} /></div>
          </div>
        </InspectorSection>

        <InspectorSection title="Shell 审批与执行">
          {!!(inspector.system?.tool_approvals?.items || []).length && (
            <div className="stack-list">
              {(inspector.system?.tool_approvals?.items || []).map((item) => (
                <div key={item.approval_id} className="mini-card">
                  <div className="mini-card-title">{item.category} · {item.tool_name}</div>
                  <div className="mini-card-text">
                    <code>{item.command_preview}</code>
                    <div>cwd: {item.args?.cwd || item.args?.cwd_scope || "project root"}</div>
                  </div>
                  <div className="approval-action-row">
                    <button type="button" disabled={approvalBusyId === item.approval_id} onClick={() => handleApproveApproval(item.approval_id)}>
                      {approvalBusyId === item.approval_id ? "处理中" : "批准执行"}
                    </button>
                    <button type="button" disabled={approvalBusyId === item.approval_id} onClick={() => handleRejectApproval(item.approval_id)}>
                      拒绝
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
          {!(inspector.system?.tool_approvals?.items || []).length && <div className="panel-hint">当前没有待审批的命令。</div>}

          {!!liveShellLines.length && (
            <div className="mini-card">
              <div className="mini-card-title">实时输出</div>
              <div className="shell-live-output">
                {liveShellLines.map((line, index) => (
                  <div key={`${line}-${index}`}>{line}</div>
                ))}
              </div>
            </div>
          )}

          <div className="stack-list">
            {(inspector.system?.shell_logs?.items || []).slice(0, 5).map((item) => (
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
        </InspectorSection>
      </aside>
    </div>
  );
}


function ChatComposer({ sending, onSend, onUploadFiles, sessionId }) {
  const [text, setText] = useState("");
  const [attachments, setAttachments] = useState([]);
  const [uploadHint, setUploadHint] = useState("");
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const fileInputRef = useRef(null);

  useEffect(() => {
    setAttachments([]);
    setUploadHint("");
    setDragging(false);
  }, [sessionId]);

  const submit = async (event) => {
    event.preventDefault();
    const value = text.trim();
    if ((!value && attachments.length === 0) || sending || uploading) {
      return;
    }

    const currentAttachments = attachments;
    setText("");
    setAttachments([]);
    setUploadHint("");
    await onSend({ text: value, attachments: currentAttachments });
  };

  const onKeyDown = async (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      await submit(event);
    }
  };

  const openFilePicker = () => {
    fileInputRef.current?.click();
  };

  const uploadFiles = async (files) => {
    const fileList = Array.from(files || []);
    if (!fileList.length) {
      return;
    }

    setUploading(true);
    setUploadHint("正在上传附件…");
    try {
      const uploaded = await onUploadFiles(fileList);
      setAttachments((current) => {
        const existingIds = new Set(current.map((item) => item.id));
        const next = [...current];
        for (const item of uploaded) {
          if (!existingIds.has(item.id)) {
            next.push(item);
          }
        }
        return next;
      });
      setUploadHint(
        uploaded.length ? `已上传 ${uploaded.length} 个附件，发送时会把工作区路径一起发给后端。` : "未识别到可上传文件。"
      );
    } catch (error) {
      setUploadHint(`上传失败：${error.message}`);
    } finally {
      setUploading(false);
    }
  };

  const onFilesSelected = async (event) => {
    await uploadFiles(event.target.files || []);
    event.target.value = "";
  };

  const onDragOver = (event) => {
    event.preventDefault();
    setDragging(true);
  };

  const onDragLeave = (event) => {
    event.preventDefault();
    const nextTarget = event.relatedTarget;
    if (nextTarget && event.currentTarget.contains(nextTarget)) {
      return;
    }
    setDragging(false);
  };

  const onDrop = async (event) => {
    event.preventDefault();
    setDragging(false);
    await uploadFiles(event.dataTransfer?.files || []);
  };

  const removeAttachment = (attachmentId) => {
    setAttachments((current) => current.filter((item) => item.id !== attachmentId));
  };

  return (
    <form
      className={`composer-form ${dragging ? "dragging" : ""}`}
      onSubmit={submit}
      onDragOver={onDragOver}
      onDragEnter={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
    >
      {!!attachments.length && (
        <div className="attachment-list">
          {attachments.map((attachment) => (
            <div key={attachment.id} className="attachment-chip">
              {attachment.isImage && attachment.previewUrl && (
                <img
                  className="attachment-chip-preview"
                  src={attachment.previewUrl}
                  alt={attachment.name}
                  loading="lazy"
                />
              )}
              <div className="attachment-chip-main">
                <div className="attachment-chip-title">{attachment.name}</div>
                <div className="attachment-chip-meta">
                  {attachment.type || "unknown"} · {attachment.sizeLabel}
                </div>
              </div>
              <button
                className="attachment-remove"
                type="button"
                onClick={() => removeAttachment(attachment.id)}
                title="移除附件"
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}

      {!!uploadHint && <div className="upload-hint">{uploadHint}</div>}
      {dragging && <div className="upload-drop-hint">松开以上传文件到当前会话</div>}

      <div className="composer-shell">
        <input
          ref={fileInputRef}
          type="file"
          hidden
          multiple
          onChange={onFilesSelected}
          accept="image/*,video/*,audio/*,.txt,.md,.json,.csv,.log,.py,.js,.ts,.tsx,.jsx,.html,.css,.xml,.yaml,.yml,.toml,.ini,.sh,.ps1,.bat,.c,.cpp,.h,.hpp,.java,.go,.rs,.pdf"
        />
        <button className="composer-side-button" type="button" title="上传文件" onClick={openFilePicker}>
          ＋
        </button>
        <textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder="有问题，尽管问"
          rows={1}
        />
        <button className="composer-send" type="submit" disabled={sending || uploading}>
          {uploading ? "上传中" : sending ? "发送中" : "发送"}
        </button>
      </div>
    </form>
  );
}


function InspectorSection({ title, children }) {
  return (
    <section className="inspector-section">
      <div className="inspector-section-title">{title}</div>
      <div className="inspector-section-body">{children}</div>
    </section>
  );
}


function MarkdownMessage({ content }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        a: ({ node, ...props }) => <a {...props} target="_blank" rel="noreferrer" />,
        pre: ({ children }) => {
          const child = Children.toArray(children).find(isValidElement);
          const className = child?.props?.className;
          const value = String(child?.props?.children || "").replace(/\n$/, "");
          return <CodeBlock className={className} value={value} />;
        },
        code: ({ className, children, ...props }) => <code className={className} {...props}>{children}</code>,
      }}
    >
      {String(content || "")}
    </ReactMarkdown>
  );
}


function RichMarkdownText({ content }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        a: ({ node, ...props }) => <a {...props} target="_blank" rel="noreferrer" />,
      }}
    >
      {String(content || "")}
    </ReactMarkdown>
  );
}


function CodeBlock({ className, value }) {
  const [copied, setCopied] = useState(false);

  return (
    <div className="code-block-shell">
      <button
        className="code-copy-button"
        type="button"
        onClick={async () => {
          await copyText(value);
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1500);
        }}
      >
        {copied ? "已复制" : "复制代码"}
      </button>
      <pre>
        <code className={className}>{value}</code>
      </pre>
    </div>
  );
}


export default App;
