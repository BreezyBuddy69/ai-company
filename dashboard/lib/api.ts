// All dashboard data fetching runs client-side (browser fetch), on purpose:
// it avoids the classic Docker SSR-vs-browser hostname mismatch (server
// would need `http://backend:8000`, browser needs a publicly reachable URL)
// and keeps the "no WebSocket, simple polling" resource-conscious design
// from ARCHITECTURE.md honest for the Logs/Overview pages too.
// NEXT_PUBLIC_API_URL is baked in at image build time — fine when you know
// the deploy target in advance (the Traefik path always sets it). The
// Hostinger Docker Manager path uses a prebuilt, target-agnostic image, so
// when it's unset this falls back to "whatever host served this page, on
// the backend's port" — works on any VPS IP without a rebuild.
function apiBase(): string {
  if (process.env.NEXT_PUBLIC_API_URL) return process.env.NEXT_PUBLIC_API_URL;
  if (typeof window !== "undefined") return `${window.location.protocol}//${window.location.hostname}:47832`;
  return "http://localhost:8000";
}
// Shared secret the backend checks via app.core.auth.require_api_key — not
// Traefik basicauth, which breaks cross-origin fetch() preflight. Anyone who
// can view this page's source (i.e. already passed the dashboard's own
// Traefik login, where applicable) can see this value; that's the intended
// trust boundary. Blank means the backend also has no API_KEY set — open,
// fine for a first "does it even boot" check, lock down after.
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
  const res = await fetch(`${apiBase()}${path}`, { cache: "no-store", headers: authHeaders });
  if (!res.ok) throw new ApiError(res.status, await res.text());
  return res.json();
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${apiBase()}${path}`, {
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
  total_runs: number;
  successful_runs: number;
  last_run_at: string | null;
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
  agent_runs_today: number;
  last_run_at: string | null;
  opportunities_by_status: Record<string, number>;
  evolution_clones_total: number;
  evolution_retirees_total: number;
  active_families: string[];
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

export interface VariantMetrics {
  success_rate: number;
  speed: number;
  cost: number;
  quality: number;
}

export interface FamilyVariant {
  id: string;
  name: string;
  generation: number;
  parent_agent_id: string | null;
  run_count: number;
  runs_needed: number;
  metrics: VariantMetrics | null;
  score: number | null;
}

export interface FamilySnapshot {
  family: string;
  variants: FamilyVariant[];
  min_runs_for_competition: number;
}
