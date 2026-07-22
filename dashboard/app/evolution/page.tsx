"use client";

import { useEffect, useState } from "react";
import { apiGet, EvolutionEntry } from "@/lib/api";

export default function EvolutionPage() {
  const [entries, setEntries] = useState<EvolutionEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiGet<EvolutionEntry[]>("/api/evolution/history")
      .then(setEntries)
      .catch((e) => setError(String(e)));
  }, []);

  return (
    <main className="page">
      <h1>Evolution</h1>
      <p className="muted">
        Scoring formulas are live (40% revenue / 20% growth / 15% conversion / 10% speed / 10%
        satisfaction / 5% cost-efficiency for products). Automatic clone/mutate cycles are a
        follow-up once products have real operating data — see ARCHITECTURE.md.
      </p>
      {error && <p className="muted">{error}</p>}
      {entries && entries.length === 0 && (
        <div className="empty-state">No scoring history yet.</div>
      )}
      {entries && entries.length > 0 && (
        <table className="data-table">
          <thead>
            <tr>
              <th>Entity</th>
              <th>Generation</th>
              <th>Score</th>
              <th>Parent</th>
              <th>Notes</th>
              <th>When</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e) => (
              <tr key={e.id}>
                <td>
                  {e.entity_type} <span className="muted">{e.entity_id.slice(0, 8)}</span>
                </td>
                <td>{e.generation}</td>
                <td>{e.score ?? "—"}</td>
                <td className="muted">{e.parent_id ? e.parent_id.slice(0, 8) : "—"}</td>
                <td className="muted">{e.mutation_notes ?? "—"}</td>
                <td className="muted">{new Date(e.created_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
