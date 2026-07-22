"use client";

import { useEffect, useState } from "react";
import { apiGet, Overview } from "@/lib/api";
import { StatTile } from "@/components/StatTile";

export default function OverviewPage() {
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      apiGet<Overview>("/api/dashboard/overview")
        .then((d) => !cancelled && setData(d))
        .catch((e) => !cancelled && setError(String(e)));
    load();
    const id = setInterval(load, 15000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  return (
    <main className="page">
      <h1>Company Overview</h1>
      {error && <p className="muted">Backend not reachable yet: {error}</p>}
      {!data && !error && <p className="muted">Loading…</p>}
      {data && (
        <div className="stat-grid">
          <StatTile label="Active agents" value={data.active_agents} />
          <StatTile label="Opportunities (24h)" value={data.opportunities_last_24h} />
          <StatTile
            label="Model success rate"
            value={data.model_success_rate_pct !== null ? `${data.model_success_rate_pct}%` : "—"}
          />
          <StatTile label="Total model calls" value={data.total_model_calls} />
          <StatTile label="Spend" value={`$${data.spend_usd.toFixed(2)}`} />
        </div>
      )}
      <div className="card">
        <h3>Free-first, by design</h3>
        <p className="muted">
          Every agent call routes through free OpenRouter models (see model_registry.yaml). Spend
          should stay at $0 unless the registry is deliberately changed to include a paid model.
        </p>
      </div>
    </main>
  );
}
