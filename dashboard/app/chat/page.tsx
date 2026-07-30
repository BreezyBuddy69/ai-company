"use client";

import { useEffect, useRef, useState } from "react";
import { apiGet, apiPost } from "@/lib/api";

interface Msg {
  role: "user" | "assistant";
  content: string;
  model?: string;
}

interface ModelInfo {
  name: string;
  display_name: string;
  capability: string;
}

export default function ChatPage() {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [capability, setCapability] = useState("");
  const [fanout, setFanout] = useState(1);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    apiGet<ModelInfo[]>("/api/chat/models").then(setModels).catch(() => {});
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function send() {
    const text = draft.trim();
    if (!text || busy) return;
    const history: Msg[] = [...messages, { role: "user", content: text }];
    setMessages(history);
    setDraft("");
    setBusy(true);
    setError(null);
    try {
      const res = await apiPost<{ replies: { model: string; content: string }[] }>("/api/chat", {
        // Only role+content go over the wire; `model` is a local display tag.
        messages: history.map((m) => ({ role: m.role, content: m.content })),
        capability: capability || null,
        fanout,
      });
      setMessages([
        ...history,
        ...res.replies.map((r) => ({ role: "assistant" as const, content: r.content, model: r.model })),
      ]);
    } catch (e) {
      setError(String(e));
      // Put the text back rather than losing what they typed on a 503.
      setDraft(text);
      setMessages(messages);
    } finally {
      setBusy(false);
    }
  }

  async function saveIdea(content: string) {
    const problem = window.prompt("Save as an opportunity — what's the problem?", content.slice(0, 200));
    if (!problem) return;
    try {
      await apiPost("/api/chat/idea", { problem });
      setMessages((m) => [
        ...m,
        { role: "assistant", content: "Saved to Opportunities — Research will score it.", model: "system" },
      ]);
    } catch (e) {
      setError(String(e));
    }
  }

  const capabilities = Array.from(new Set(models.map((m) => m.capability)));

  return (
    <main className="page">
      <h1>Chat</h1>
      <p className="muted">
        Same free models the agents run on. Anything worth keeping goes to Opportunities, where
        Research scores it and the CEO decides — the agents don&apos;t read this conversation.
      </p>

      <div style={{ display: "flex", gap: 8, alignItems: "center", margin: "12px 0" }}>
        <select className="input" value={capability} onChange={(e) => setCapability(e.target.value)}>
          <option value="">Best available</option>
          {capabilities.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <select className="input" value={fanout} onChange={(e) => setFanout(Number(e.target.value))}>
          <option value={1}>1 model</option>
          <option value={2}>2 models</option>
          <option value={3}>3 models</option>
          <option value={4}>4 models</option>
        </select>
        <span className="muted" style={{ fontSize: 12 }}>
          {fanout > 1 ? "asks different models the same thing" : `${models.length} models available`}
        </span>
      </div>

      {error && <p className="muted">{error}</p>}

      <div style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: 14 }}>
        {messages.length === 0 && (
          <div className="empty-state">
            Describe a problem you&apos;ve actually seen someone have. That&apos;s worth more than
            anything Scout finds by scraping.
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className="card" style={{ background: m.role === "user" ? "var(--beige)" : undefined }}>
            <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>
              {m.role === "user" ? "You" : m.model || "assistant"}
            </div>
            <div style={{ whiteSpace: "pre-wrap" }}>{m.content}</div>
            {m.role === "assistant" && m.model !== "system" && (
              <button className="btn" style={{ marginTop: 8 }} onClick={() => saveIdea(m.content)}>
                Save as opportunity
              </button>
            )}
          </div>
        ))}
        <div ref={endRef} />
      </div>

      <div style={{ display: "flex", gap: 8 }}>
        <input
          className="input"
          style={{ flex: 1 }}
          placeholder={busy ? "Thinking…" : "Your idea, or a question"}
          value={draft}
          disabled={busy}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
        />
        <button className="btn primary" onClick={send} disabled={busy || !draft.trim()}>
          Send
        </button>
      </div>
    </main>
  );
}
