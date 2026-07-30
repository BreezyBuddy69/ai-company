"use client";

import { useEffect, useState } from "react";
import { apiGet, apiPost, HumanQuestion } from "@/lib/api";

export default function QuestionsPage() {
  const [questions, setQuestions] = useState<HumanQuestion[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = () =>
    apiGet<HumanQuestion[]>("/api/questions?status=open")
      .then(setQuestions)
      .catch((e) => setError(String(e)));

  useEffect(() => {
    load();
    // Agents file questions on their own schedule, so poll rather than making
    // the operator reload to find out something is waiting.
    const t = setInterval(load, 20000);
    return () => clearInterval(t);
  }, []);

  async function send(id: string) {
    const answer = (drafts[id] || "").trim();
    if (!answer) return;
    setBusyId(id);
    try {
      await apiPost(`/api/questions/${id}/answer`, { answer });
      // Drop the draft immediately — for a secret this is the only copy left
      // in the browser once the row stops coming back from the API.
      setDrafts((d) => {
        const next = { ...d };
        delete next[id];
        return next;
      });
      await load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusyId(null);
    }
  }

  async function dismiss(id: string) {
    setBusyId(id);
    try {
      await apiPost(`/api/questions/${id}/dismiss`, {});
      await load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <main className="page">
      <h1>Questions</h1>
      <p className="muted">
        Agents ask here when they hit something they can&apos;t work out alone — an address to use, a
        login, a choice between two paths. Nothing blocks waiting for you; an unanswered question
        just means that agent skips that branch until you reply.
      </p>
      {error && <p className="muted">{error}</p>}
      {questions && questions.length === 0 && (
        <div className="empty-state">Nothing waiting on you.</div>
      )}
      {questions && questions.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {questions.map((q) => (
            <div key={q.id} className="card">
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                <strong>{q.question}</strong>
                <span className="muted" style={{ fontSize: 12, whiteSpace: "nowrap" }}>
                  {q.agent}
                </span>
              </div>
              {q.context && (
                <div className="muted" style={{ fontSize: 13, marginTop: 6 }}>
                  {q.context}
                </div>
              )}
              {q.kind === "secret" && (
                <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
                  Stored as plain text in the database and readable by any agent that asks for it.
                  Use a scoped, revocable credential here — never a primary password.
                </div>
              )}
              <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
                <input
                  className="input"
                  style={{ flex: 1 }}
                  type={q.kind === "secret" ? "password" : "text"}
                  autoComplete={q.kind === "secret" ? "new-password" : "off"}
                  placeholder={q.kind === "secret" ? "Value (hidden)" : "Your answer"}
                  value={drafts[q.id] || ""}
                  onChange={(e) => setDrafts((d) => ({ ...d, [q.id]: e.target.value }))}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") send(q.id);
                  }}
                />
                <button
                  className="btn primary"
                  disabled={busyId === q.id || !(drafts[q.id] || "").trim()}
                  onClick={() => send(q.id)}
                >
                  {busyId === q.id ? "…" : "Answer"}
                </button>
                <button className="btn" disabled={busyId === q.id} onClick={() => dismiss(q.id)}>
                  Skip
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </main>
  );
}
