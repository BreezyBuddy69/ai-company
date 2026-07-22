// All dashboard data fetching runs client-side (browser fetch), on purpose:
// it avoids the classic Docker SSR-vs-browser hostname mismatch (server
// would need `http://backend:8000`, browser needs a publicly reachable URL)
// and keeps the "no WebSocket, simple polling" resource-conscious design
// from ARCHITECTURE.md honest for the Logs/Overview pages too.
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
// Shared secret the backend checks via app.core.auth.require_api_key — not
// Traefik basicauth, which breaks cross-origin fetch() preflight. Anyone who
// can view this page's source (i.e. already passed the dashboard's own
// Traefik login) can see this value; that's the intended trust boundary.
const API_KEY = process.env.NEXT_PUBLIC_API_KEY || "";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

const authHeaders: HeadersInit = API_KEY ? { "X-API-Key": API_KEY } : {};

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store", headers: authHeaders });
  if (!res.ok) throw new ApiError(res.status, await res.text());
  return res.json();
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new ApiError(res.status, await res.text());
  return res.json();
}

export interface Agent {
  id: string;
  name: string;
  role: string;
  status: string;
  generation: number;
  created_at: string;
}

export interface Opportunity {
  id: string;
  problem: string;
  target_customer: string | null;
  existing_solutions: string[];
  pain_level: number | null;
  possible_product: string | null;
  revenue_potential: string | null;
  source: string;
  source_url: string | null;
  research_score: number | null;
  research_notes: string | null;
  status: string;
  decision_rationale: string | null;
  created_at: string;
}

export interface LogEntry {
  id: string;
  agent: string;
  task_id: string | null;
  model_used: string | null;
  success: boolean;
  error: string | null;
  latency_ms: number | null;
  tokens_in: number;
  tokens_out: number;
  output: Record<string, unknown> | null;
  created_at: string;
}

export interface Overview {
  active_agents: number;
  opportunities_last_24h: number;
  model_success_rate_pct: number | null;
  total_model_calls: number;
  spend_usd: number;
}

export interface EvolutionEntry {
  id: string;
  entity_type: string;
  entity_id: string;
  generation: number;
  score: number | null;
  score_breakdown: Record<string, number>;
  parent_id: string | null;
  mutation_notes: string | null;
  created_at: string;
}
