"use client";

import { useEffect, useState } from "react";
import { apiGet, Agent } from "@/lib/api";
import { Badge } from "@/components/Badge";

export default function AgentsPage() {
  const [agents, setAgents] = useState<Agent[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiGet<Agent[]>("/api/agents")
      .then(setAgents)
      .catch((e) => setError(String(e)));
  }, []);

  return (
    <main className="page">
      <h1>Agents</h1>
      <p className="muted">
        Config-driven — new agents are added by dropping a YAML file in agents/configs/, no code
        change required.
      </p>
      {error && <p className="muted">Could not load agents: {error}</p>}
      {agents && (
        <table className="data-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Role</th>
              <th>Status</th>
              <th>Generation</th>
              <th>Registered</th>
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
                <td>{a.generation}</td>
                <td className="muted">{new Date(a.created_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
