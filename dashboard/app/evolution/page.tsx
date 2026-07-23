"use client";

import { useEffect, useState } from "react";
import { apiGet, apiPost, EvolutionEntry, FamilySnapshot } from "@/lib/api";

function Meter({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="metric-row">
        <span>{label}</span>
        <span>{value.toFixed(0)}</span>
      </div>
      <div className="score-bar-track">
        <div className="score-bar-fill" style={{ width: `${Math.max(2, value)}%` }} />
      </div>
    </div>
  );
}

function FamilyArena({ snapshot, onCompete, busy }: { snapshot: FamilySnapshot; onCompete: () => void; busy: boolean }) {
  const [a, b] = snapshot.variants;
  const leaderId = snapshot.variants.reduce(
    (best, v) => (v.score !== null && (best === null || v.score > (best.score ?? -1)) ? v : best),
    null as FamilySnapshot["variants"][number] | null,
  )?.id;

  return (
    <div className="card" style={{ marginBottom: 24 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h3 style={{ textTransform: "capitalize" }}>{snapshot.family}</h3>
        <button className="btn" disabled={busy} onClick={onCompete}>
          Run competition now
        </button>
      </div>

      {snapshot.variants.length === 0 && <p className="muted">No active agent in this role.</p>}

      {snapshot.variants.length === 1 && (
        <p className="muted">
          Only one variant ({a.name}) — {a.run_count}/{snapshot.min_runs_for_competition} runs.{" "}
          {a.runs_needed > 0
            ? `Needs ${a.runs_needed} more before a sibling can be bootstrapped to compete against.`
            : "Ready — the next competition cycle will bootstrap a sibling."}
        </p>
      )}

      {snapshot.variants.length >= 2 && (
        <div className="arena">
          {[a, b].map((v, i) => (
            <div key={v.id} className={`variant-card ${v.id === leaderId ? "leader" : ""}`}>
              <div className="variant-name">
                {v.name} {v.id === leaderId && "👑"}
              </div>
              <p className="muted" style={{ fontSize: 12 }}>
                Generation {v.generation} · {v.run_count} runs
              </p>
              {v.metrics ? (
                <>
                  <Meter label="Success rate" value={v.metrics.success_rate} />
                  <Meter label="Speed" value={v.metrics.speed} />
                  <Meter label="Cost efficiency" value={v.metrics.cost} />
                  <p style={{ marginTop: 8, fontSize: 13 }}>
                    <strong>Score: {v.score?.toFixed(1)}</strong>
                  </p>
                </>
              ) : (
                <p className="muted" style={{ fontSize: 12 }}>
                  {v.run_count}/{snapshot.min_runs_for_competition} runs — not enough data to score yet.
                </p>
              )}
              {i === 0 && <div className="arena-vs" style={{ position: "absolute", right: -29, top: "45%" }}>VS</div>}
            </div>
          ))}
        </div>
      )}
      {snapshot.variants.length > 2 && (
        <p className="muted" style={{ fontSize: 12 }}>
          +{snapshot.variants.length - 2} more variant(s) also active in this family.
        </p>
      )}
    </div>
  );
}

export default function EvolutionPage() {
  const [families, setFamilies] = useState<FamilySnapshot[] | null>(null);
  const [entries, setEntries] = useState<EvolutionEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busyFamily, setBusyFamily] = useState<string | null>(null);

  const load = () => {
    apiGet<FamilySnapshot[]>("/api/evolution/families").then(setFamilies).catch((e) => setError(String(e)));
    apiGet<EvolutionEntry[]>("/api/evolution/history").then(setEntries).catch((e) => setError(String(e)));
  };

  useEffect(load, []);

  async function compete(family: string) {
    setBusyFamily(family);
    try {
      await apiPost(`/api/evolution/compete/${family}`, {});
      load();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusyFamily(null);
    }
  }

  return (
    <main className="page">
      <h1>Evolution</h1>
      <p className="muted">
        Every role runs two competing variants at a time (a family, e.g. <code>scout</code> /{" "}
        <code>scout-g2</code>). They're judged purely on real agent-run data — success rate, speed,
        cost — never a guessed "quality" score. The loser is retired (soft-deleted, lineage kept),
        the winner is cloned into a slightly mutated sibling so the roster keeps evolving. Runs
        automatically once a day at 03:00 UTC, or trigger it below.
      </p>
      {error && <p className="muted">{error}</p>}

      {families && families.length === 0 && <div className="empty-state">No active agent families yet.</div>}
      {families?.map((f) => (
        <FamilyArena key={f.family} snapshot={f} busy={busyFamily === f.family} onCompete={() => compete(f.family)} />
      ))}

      <h2 style={{ marginTop: 32 }}>Lineage history</h2>
      {entries && entries.length === 0 && <div className="empty-state">No scoring history yet.</div>}
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
