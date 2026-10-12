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

export type AgentDetail = {
  id: number;
  status: string;
  position: { x: number; y: number } | null;
  goal: string | null;
  generation: number;
  parent_id: number | null;
  children: number[];
  population_id: number | null;
  policy: "model" | "scripted";
  provider: { provider: string | null; model: string | null };
  compute: {
    model_calls: number;
    envelope: { temperature: number; max_tokens: number | null; timeout_seconds: number };
  };
  last_action: {
    tick: number;
    action: Record<string, unknown>;
    ok: boolean;
    reason: string | null;
  } | null;
  memory: {
    tick: number;
    action: Record<string, unknown>;
    ok: boolean;
    reason: string | null;
    goal: string | null;
  }[];
  inheritance: {
    traits: Record<string, unknown>;
    knowledge: string[];
    cultural_artifacts: unknown[];
  };
  // S29: what this agent knows how to make, and what it carries.
  technology: {
    recipes: string[];
    patterns: string[];
    carried: { id: number; type: string; properties: Record<string, unknown> }[];
  };
  // S30: the community this agent belongs to, or null.
  settlement: AgentSettlement;
};

export type Drift = {
  generation: number;
  facts_received: number;
  retained: string[];
  altered: string[];
  contradicted: string[];
  new: string[];
  lost: string[];
  message: string | null;
  message_length: number;
  avg_similarity: number;
};

export type LineageMember = {
  id: number;
  generation: number;
  parent_id: number | null;
  children: number[];
  position: { x: number; y: number } | null;
  policy: "model" | "scripted";
  goal: string | null;
  status: string;
  knowledge_count: number;
  knowledge: string[];
  traits: Record<string, unknown>;
  artifacts_count: number;
  inheritance_message: string | null;
  drift: Drift;
};

export type Lineage = {
  world_id: number;
  agent_id: number;
  chain: LineageMember[];
};

export type PopulationStats = {
  population_id: number;
  name: string;
  size: number;
  max_members: number | null;
  top_up: boolean;
  generation: { min: number; max: number; average: number };
  brains: { model: number; scripted: number };
  resources: Record<string, number>;
  births: number;
  arrivals: number;
  founded_tick: number;
  age_ticks: number;
  rule: {
    name: string;
    members: number;
    policies: string[];
    spawn_zone: number[] | null;
    max_members: number | null;
    top_up: boolean;
    stipend: Record<string, number>;
  };
};

export type Populations = {
  world_id: number;
  populations: PopulationStats[];
  totals: {
    populations: number;
    agents: number;
    births: number;
    arrivals: number;
    resources: Record<string, number>;
  };
};

export type Relationship = {
  agent_id: number;
  kind: string;
  population_id: number | null;
  generation: number;
  position: { x: number; y: number } | null;
  distance: number | null;
};

export type Relationships = {
  world_id: number;
  agent_id: number;
  relationships: Relationship[];
};

export type SettlementStats = {
  id: number;
  name: string;
  founder_id: number;
  population_id: number | null;
  founded_tick: number;
  center: { x: number; y: number };
  members: number[];
  home_ids: number[];
  storage_ids: number[];
  road_ids: number[];
  zones: { object_id: number; resource: string; position: { x: number; y: number } | null }[];
  storage: Record<string, number>;
  homes: number;
  storage_structures: number;
  roads: number;
  road_cells: { x: number; y: number }[];
  members_with_roles: { agent_id: number; role: string }[];
  contents: Record<string, number>;
  age_ticks: number;
};

export type Settlements = {
  world_id: number;
  settlements: SettlementStats[];
};

export type AgentSettlement = {
  id: number;
  name: string;
  role: string;
  population_id: number | null;
  members: number[];
  homes: number;
  storage: number;
  roads: number;
  contents: Record<string, number>;
  zones: { object_id: number; resource: string; position: { x: number; y: number } | null }[];
} | null;

export type Participant = {
  world_id: number;
  participant: { entity_id: number; position: { x: number; y: number } } | null;
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
  agentDetail: (id: number, agentId: number) =>
    request<AgentDetail>(`/api/worlds/${id}/agents/${agentId}`),
  agentLineage: (id: number, agentId: number) =>
    request<Lineage>(`/api/worlds/${id}/agents/${agentId}/lineage`),
  populations: (id: number) => request<Populations>(`/api/worlds/${id}/populations`),
  addPopulation: (id: number, rule: {
    name: string;
    members: number;
    policies: string[];
    spawn_zone?: number[] | null;
    max_members?: number | null;
    top_up?: boolean;
    stipend?: Record<string, number>;
  }) =>
    post(`/api/worlds/${id}/populations`, rule) as unknown as Promise<{
      world_id: number;
      population: PopulationStats;
    }>,
  relationships: (id: number, agentId: number) =>
    request<Relationships>(`/api/worlds/${id}/agents/${agentId}/relationships`),
  settlements: (id: number) => request<Settlements>(`/api/worlds/${id}/settlements`),
  settlement: (id: number, settlementId: number) =>
    request<{ world_id: number; settlement: SettlementStats }>(
      `/api/worlds/${id}/settlements/${settlementId}`,
    ),
  participant: (id: number) => request<Participant>(`/api/worlds/${id}/participant`),
  participantJoin: (id: number) =>
    post(`/api/worlds/${id}/participant/join`) as unknown as Promise<Participant & { joined: boolean }>,
  participantLeave: (id: number) =>
    post(`/api/worlds/${id}/participant/leave`) as unknown as Promise<Participant & { left: boolean }>,
  participantMove: (id: number, direction: string) =>
    post(`/api/worlds/${id}/participant/move`, { direction }) as unknown as Promise<{
      ok: boolean;
      reason: string | null;
      position: { x: number; y: number } | null;
    }>,
  chat: (id: number, agentId: number, message: string) =>
    post(`/api/worlds/${id}/chat`, { agent_id: agentId, message }) as unknown as Promise<{
      heard: boolean;
      reply: string | null;
      distance: number;
      speech_event_id: number;
    }>,
  events: (id: number, sinceId: number, limit = 100) =>
    request<{ world_id: number; events: WorldEvent[] }>(
      `/api/worlds/${id}/events?since_id=${sinceId}&limit=${limit}`,
    ),
  pause: (id: number) => post(`/api/worlds/${id}/pause`),
  resume: (id: number) => post(`/api/worlds/${id}/resume`),
  step: (id: number) => post(`/api/worlds/${id}/step`) as unknown as Promise<WorldState>,
  remove: (id: number) => request(`/api/worlds/${id}`, { method: "DELETE" }),
};
