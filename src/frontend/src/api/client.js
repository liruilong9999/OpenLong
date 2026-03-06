const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export async function checkHealth() {
  const response = await fetch(`${API_BASE}/health`);
  if (!response.ok) {
    throw new Error("health check failed");
  }
  return response.json();
}

export async function sendChatMessage(sessionId, message) {
  const response = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ session_id: sessionId || null, message }),
  });

  if (!response.ok) {
    throw new Error("chat request failed");
  }

  return response.json();
}
