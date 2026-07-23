"use client";

import { useEffect, useState } from "react";
import { apiGet, apiPatch, apiPost, Agent } from "@/lib/api";
import { Badge } from "@/components/Badge";

function family(name: string): string {
  return name.replace(/-g\d+$/, "");
}

function timeAgo(iso: string | null): string {
  if (!iso) return "never";
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

const DEFAULT_GOALS: Record<string, string> = {
  research:
    "Use read_opportunities with status='new' to see opportunities needing research. Pick up to 3, assess " +
    "demand, existing competition, and realistic pricing for each, then call score_opportunity with a 0-100 " +
    "research_score and concise research_notes for each.",
  ceo:
    "Use read_opportunities with status='researched' to see recently scored opportunities. For each one worth " +
    "a decision, call decide_opportunity with approved, watch, or rejected and a short rationale grounded in " +
    "its research_score and research_notes.",
  product:
    "Use read_opportunities with status='approved' to see approved opportunities needing a spec. Pick one, " +
    "define an MVP (core features, rough roadmap, pricing approach, validation plan), then call write_memory " +
    "with memory_type='decision' to record it.",
};

function goalFor(agentFamily: string): string | null {
  if (agentFamily === "scout") {
    const keyword = window.prompt("Search keyword for Scout?", "expensive manual spreadsheet");
    if (!keyword) return null;
    return (
      `Search Hacker News, GitHub issues, and Reddit for the keyword '${keyword}' to find one real, ` +
      "underserved customer pain point that could become a product. If you find a credible one, call " +
      "create_opportunity with what you found, citing the source URL. If nothing credible turns up, just finish."
    );
  }
  return DEFAULT_GOALS[agentFamily] ?? "You are still a v1 stub with limited tools. Check what's available, do what you usefully can, then finish.";
}

export default function AgentsPage() {
  const [agents, setAgents] = useState<Agent[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [result, setResult] = useState<string | null>(null);

  const load = () => apiGet<Agent[]>("/api/agents").then(setAgents).catch((e) => setError(String(e)));

  useEffect(() => {
    load();
  }, []);

  async function toggleStatus(name: string, current: string) {
    const next = current === "active" ? "paused" : "active";
    setBusy(name);
    try {
      await apiPatch(`/api/agents/${name}/status`, { status: next });
      await load();
    } catch (e) {
      setResult(`${name} status change failed: ${String(e)}`);
    } finally {
      setBusy(null);
    }
  }

  async function runNow(name: string) {
    const goal = goalFor(family(name));
    if (goal === null) return;
    setBusy(name);
    setResult(null);
    try {
      const res = await apiPost<{ result: unknown }>(`/api/agents/${name}/run`, { goal });
      setResult(`${name} finished: ${JSON.stringify(res.result).slice(0, 300)}`);
      await load();
    } catch (e) {
      setResult(`${name} failed: ${String(e)}`);
    } finally {
      setBusy(null);
    }
  }

  return (
    <main className="page">
      <h1>Agents</h1>
      <p className="muted">
        Config-driven — new agents are added by dropping a YAML file in agents/configs/, no code
        change required. &ldquo;Run now&rdquo; calls the same code path as the scheduled cycle, synchronously,
        so you can watch it actually work instead of waiting for the hourly schedule. &ldquo;Activate&rdquo;
        turns a paused role on for the automatic pipeline going forward.
      </p>
      {error && <p className="muted">Could not load agents: {error}</p>}
      {result && (
        <div className="card" style={{ marginBottom: 17, fontSize: 13 }}>
          {result}
        </div>
      )}
      {agents && (
        <table className="data-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Role</th>
              <th>Status</th>
              <th>Runs</th>
              <th>Last run</th>
              <th>Generation</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {agents.map((a) => (
              <tr key={a.id}>
                <td>{a.name}</td>
                <td className="muted">{a.role}</td>
                <td>
                  <Badge status={a.status} />
                </td>
                <td className="muted">
                  {a.total_runs > 0 ? `${a.successful_runs}/${a.total_runs} ok` : "0"}
                </td>
                <td className="muted">
                  <span className={`live-dot ${a.last_run_at ? "" : "idle"}`} style={{ marginRight: 6 }} />
                  {timeAgo(a.last_run_at)}
                </td>
                <td>{a.generation}</td>
                <td style={{ display: "flex", gap: 6 }}>
                  {a.status === "active" && (
                    <button className="btn primary" disabled={busy === a.name} onClick={() => runNow(a.name)}>
                      {busy === a.name ? "Running…" : "Run now"}
                    </button>
                  )}
                  {(a.status === "active" || a.status === "paused") && (
                    <button className="btn" disabled={busy === a.name} onClick={() => toggleStatus(a.name, a.status)}>
                      {a.status === "active" ? "Pause" : "Activate"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
