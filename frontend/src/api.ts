// Typed client for the Simulation API (S06B/S09/S13).
// Every panel polls through these helpers; polling at 1-2 Hz is the
// console's refresh until WebSocket push lands.

export type Health = {
  status: string;
  service: string;
  version: string;
  environment: string;
};

export type WorldSummary = {
  id: number;
  seed: string;
  tick: number;
  paused: boolean;
  agents: number;
  brains: string;
};

export type WorldState = {
  id: number;
  seed: string;
  width: number;
  height: number;
  tick: number;
  terrain: string[];
  objects: { id: number; type: string; position: { x: number; y: number } }[];
  entities: Record<string, { x: number; y: number }>;
  paused: boolean;
  agent_count: number;
  brains: string;
  provider: { provider: string; model: string } | null;
};

export type AgentSummary = {
  id: number;
  generation: number;
  parent_id: number | null;
  population_id: number | null;
  status: string;
  position: { x: number; y: number } | null;
  goal: string | null;
  policy: "model" | "scripted";
  knowledge: number;
};

export type WorldEvent = {
  id: number;
  tick: number;
  type: string;
  actor_id: number | null;
  target_id: number | null;
  payload: Record<string, unknown>;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    throw new Error(`HTTP ${response.status}${detail ? `: ${detail}` : ""}`);
  }
  return (await response.json()) as T;
}

function post(path: string, body?: unknown): Promise<never> {
  return request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  }) as Promise<never>;
}

export const api = {
  health: () => request<Health>("/api/health"),
  worlds: () => request<{ worlds: WorldSummary[] }>("/api/worlds"),
  createWorld: (body: {
    seed: string;
    width: number;
    height: number;
    agents: number;
    brains: string;
    autostart: boolean;
  }) => post("/api/worlds", body) as unknown as Promise<WorldState>,
  world: (id: number) => request<WorldState>(`/api/worlds/${id}`),
  agents: (id: number) =>
    request<{ world_id: number; agents: AgentSummary[] }>(`/api/worlds/${id}/agents`),
  events: (id: number, sinceId: number, limit = 100) =>
    request<{ world_id: number; events: WorldEvent[] }>(
      `/api/worlds/${id}/events?since_id=${sinceId}&limit=${limit}`,
    ),
  pause: (id: number) => post(`/api/worlds/${id}/pause`),
  resume: (id: number) => post(`/api/worlds/${id}/resume`),
  step: (id: number) => post(`/api/worlds/${id}/step`) as unknown as Promise<WorldState>,
  remove: (id: number) => request(`/api/worlds/${id}`, { method: "DELETE" }),
};
