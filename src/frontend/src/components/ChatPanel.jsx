import { useState } from "react";

function ChatPanel({ messages, onSend }) {
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);

  const submit = async (event) => {
    event.preventDefault();
    const content = text.trim();
    if (!content) {
      return;
    }

    setText("");
    setSending(true);
    try {
      await onSend(content);
    } finally {
      setSending(false);
    }
  };

  return (
    <section className="card">
      <h2>Chat</h2>
      <div className="chat-log">
        {messages.length === 0 && <p className="hint">No messages yet.</p>}
        {messages.map((item, index) => (
          <p key={`${item.role}-${index}`} className={`message ${item.role}`}>
            <strong>{item.role}:</strong> {item.content}
          </p>
        ))}
      </div>

      <form className="chat-form" onSubmit={submit}>
        <textarea
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder="Type a message"
          rows={4}
        />
        <button type="submit" disabled={sending}>
          {sending ? "Sending..." : "Send"}
        </button>
      </form>
    </section>
  );
}

export default ChatPanel;
