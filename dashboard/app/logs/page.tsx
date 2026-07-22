"use client";

import { useEffect, useState } from "react";
import { apiGet, LogEntry } from "@/lib/api";
import { Badge } from "@/components/Badge";

export default function LogsPage() {
  const [logs, setLogs] = useState<LogEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      apiGet<LogEntry[]>("/api/logs")
        .then((d) => !cancelled && setLogs(d))
        .catch((e) => !cancelled && setError(String(e)));
    load();
    const id = setInterval(load, 5000); // simple polling, no WebSocket — see ARCHITECTURE.md
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  return (
    <main className="page">
      <h1>Logs</h1>
      <p className="muted">Most recent agent runs, polled every 5s.</p>
      {error && <p className="muted">{error}</p>}
      {logs && logs.length === 0 && <div className="empty-state">No agent runs yet.</div>}
      {logs && logs.length > 0 && (
        <table className="data-table">
          <thead>
            <tr>
              <th>Agent</th>
              <th>Model</th>
              <th>Status</th>
              <th>Latency</th>
              <th>Tokens</th>
              <th>When</th>
            </tr>
          </thead>
          <tbody>
            {logs.map((l) => (
              <tr key={l.id}>
                <td>{l.agent}</td>
                <td className="muted">{l.model_used ?? "—"}</td>
                <td>
                  <Badge status={l.success ? "success" : "error"} />
                  {l.error && <div className="muted" style={{ fontSize: 11 }}>{l.error}</div>}
                </td>
                <td className="muted">{l.latency_ms ? `${l.latency_ms}ms` : "—"}</td>
                <td className="muted">
                  {l.tokens_in}/{l.tokens_out}
                </td>
                <td className="muted">{new Date(l.created_at).toLocaleTimeString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
