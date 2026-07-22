"use client";

import { useEffect, useState } from "react";
import { apiGet, apiPost, Opportunity } from "@/lib/api";
import { Badge } from "@/components/Badge";

const DECISIONS: { value: string; label: string; className: string }[] = [
  { value: "approved", label: "Approve", className: "btn primary" },
  { value: "watch", label: "Watch", className: "btn" },
  { value: "rejected", label: "Reject", className: "btn danger" },
];

export default function OpportunitiesPage() {
  const [opportunities, setOpportunities] = useState<Opportunity[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = () =>
    apiGet<Opportunity[]>("/api/opportunities")
      .then(setOpportunities)
      .catch((e) => setError(String(e)));

  useEffect(() => {
    load();
  }, []);

  async function decide(id: string, decision: string) {
    const rationale = window.prompt(`Rationale for "${decision}"?`, "");
    if (rationale === null) return;
    setBusyId(id);
    try {
      await apiPost(`/api/opportunities/${id}/decision`, { decision, decision_rationale: rationale });
      await load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <main className="page">
      <h1>Opportunities</h1>
      <p className="muted">Found by the Scout agent, scored by Research. Human override available below.</p>
      {error && <p className="muted">{error}</p>}
      {opportunities && opportunities.length === 0 && (
        <div className="empty-state">
          No opportunities yet — the Scout agent hasn&apos;t run, or hasn&apos;t found anything credible.
        </div>
      )}
      {opportunities && opportunities.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {opportunities.map((o) => (
            <div key={o.id} className="card">
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                <div>
                  <strong>{o.problem}</strong>
                  <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
                    {o.target_customer || "target customer unspecified"} · via {o.source}
                    {o.source_url && (
                      <>
                        {" · "}
                        <a href={o.source_url} target="_blank" rel="noreferrer">
                          source
                        </a>
                      </>
                    )}
                  </div>
                </div>
                <Badge status={o.status} />
              </div>

              {o.possible_product && (
                <p style={{ marginTop: 8 }}>
                  <span className="muted">Idea: </span>
                  {o.possible_product}
                </p>
              )}
              {o.research_score !== null && (
                <p className="muted" style={{ fontSize: 13 }}>
                  Research score: {o.research_score}/100 — {o.research_notes}
                </p>
              )}
              {o.decision_rationale && (
                <p className="muted" style={{ fontSize: 13 }}>
                  Decision rationale: {o.decision_rationale}
                </p>
              )}

              <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
                {DECISIONS.map((d) => (
                  <button
                    key={d.value}
                    className={d.className}
                    disabled={busyId === o.id}
                    onClick={() => decide(o.id, d.value)}
                  >
                    {d.label}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </main>
  );
}
