"use client";

import { useEffect, useState } from "react";
import { apiGet, LogEntry, Overview } from "@/lib/api";
import { StatTile } from "@/components/StatTile";
import { Badge } from "@/components/Badge";

function timeAgo(iso: string): string {
  const seconds = Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

export default function OverviewPage() {
  const [data, setData] = useState<Overview | null>(null);
  const [activity, setActivity] = useState<LogEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      apiGet<Overview>("/api/dashboard/overview")
        .then((d) => !cancelled && setData(d))
        .catch((e) => !cancelled && setError(String(e)));
      apiGet<LogEntry[]>("/api/logs?limit=20")
        .then((d) => !cancelled && setActivity(d))
        .catch(() => {});
    };
    load();
    const id = setInterval(load, 5000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const isLive = data?.last_run_at ? Date.now() - new Date(data.last_run_at).getTime() < 15 * 60 * 1000 : false;

  return (
    <main className="page">
      <h1>Company Overview</h1>
      {error && <p className="muted">Backend not reachable yet: {error}</p>}
      {!data && !error && <p className="muted">Loading…</p>}
      {data && (
        <>
          <div className="stat-grid">
            <StatTile label="Active agents" value={data.active_agents} />
            <StatTile label="Agent runs today" value={data.agent_runs_today} />
            <StatTile label="Opportunities (24h)" value={data.opportunities_last_24h} />
            <StatTile
              label="Model success rate"
              value={data.model_success_rate_pct !== null ? `${data.model_success_rate_pct}%` : "—"}
            />
            <StatTile label="Total model calls" value={data.total_model_calls} />
            <StatTile label="Spend" value={`$${data.spend_usd.toFixed(2)}`} />
            <StatTile label="Evolution clones" value={data.evolution_clones_total} />
            <StatTile label="Evolution retirees" value={data.evolution_retirees_total} />
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1.3fr 1fr", gap: 17, alignItems: "start" }}>
            <div className="card">
              <div className="section-title">
                <span className={`live-dot ${isLive ? "" : "idle"}`} />
                Live activity
              </div>
              <p className="muted" style={{ marginTop: -8, marginBottom: 12, fontSize: 12 }}>
                Every agent run as it happens, polled every 5s.{" "}
                {!isLive && "No run in the last 15 minutes — the stack is likely not deployed/running right now."}
              </p>
              {activity && activity.length === 0 && (
                <div className="empty-state">No agent runs yet — nothing has executed.</div>
              )}
              {activity && activity.length > 0 && (
                <div className="activity-feed">
                  {activity.map((a) => (
                    <div className="activity-row" key={a.id}>
                      <span className="who">{a.agent}</span>
                      <span className="what">
                        {a.model_used ?? "no model"} · {a.tokens_in + a.tokens_out} tok
                        {a.error && ` · ${a.error}`}
                      </span>
                      <Badge status={a.success ? "success" : "error"} />
                      <span className="when">{timeAgo(a.created_at)}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: 17 }}>
              <div className="card">
                <h3 style={{ fontSize: 15 }}>Opportunity pipeline</h3>
                {Object.keys(data.opportunities_by_status).length === 0 && (
                  <p className="muted" style={{ fontSize: 13 }}>Nothing found yet.</p>
                )}
                {Object.entries(data.opportunities_by_status).map(([status, count]) => (
                  <div className="metric-row" key={status}>
                    <Badge status={status} />
                    <span>{count}</span>
                  </div>
                ))}
              </div>
              <div className="card">
                <h3 style={{ fontSize: 15 }}>Active roles evolving</h3>
                <p className="muted" style={{ fontSize: 13 }}>
                  {data.active_families.length > 0 ? data.active_families.join(", ") : "none yet"}
                </p>
                <a href="/evolution" style={{ fontSize: 13 }}>
                  View the arena →
                </a>
              </div>
              <div className="card">
                <h3 style={{ fontSize: 15 }}>Free-first, by design</h3>
                <p className="muted" style={{ fontSize: 13 }}>
                  Every agent call routes through free OpenRouter models (model_registry.yaml).
                  Spend stays $0 unless that registry is deliberately changed.
                </p>
              </div>
            </div>
          </div>
        </>
      )}
    </main>
  );
}
