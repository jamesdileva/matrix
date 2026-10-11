// The observer dashboard for one world (S13).
//
// Polls the Simulation API: state + agents at 1 Hz, events at 2 Hz
// (since_id tracking). Everything shown comes from real backend
// events — the same timeline the database persists.

import { useCallback, useEffect, useRef, useState } from "react";
import { AgentInspector } from "./AgentInspector";
import { api } from "./api";
import type { AgentSummary, WorldEvent, WorldState } from "./api";
import { Controls } from "./Controls";
import { EventStream } from "./EventStream";
import { ParticipantPanel } from "./ParticipantPanel";
import { PopulationStats } from "./PopulationStats";
import { PopulationsPanel } from "./PopulationsPanel";
import { WorldViewport } from "./WorldViewport";
import { buttonStyle, colors, headingStyle, panelStyle } from "./theme";

type Props = {
  worldId: number;
  onWorldsChanged: () => void;
};

export function WorldDashboard({ worldId, onWorldsChanged }: Props) {
  const [state, setState] = useState<WorldState | null>(null);
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [events, setEvents] = useState<WorldEvent[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const sinceId = useRef(0);
  const worldIdRef = useRef(worldId);

  const refreshState = useCallback(async () => {
    try {
      const [nextState, nextAgents] = await Promise.all([
        api.world(worldId),
        api.agents(worldId),
      ]);
      setState(nextState);
      setAgents(nextAgents.agents);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [worldId]);

  const refreshEvents = useCallback(async () => {
    try {
      const page = await api.events(worldId, sinceId.current, 200);
      if (page.events.length > 0) {
        sinceId.current = page.events[page.events.length - 1].id;
        setEvents((previous) => {
          const merged =
            previous.length && page.events[0].id <= previous[previous.length - 1].id + 1
              ? [...previous, ...page.events]
              : page.events;
          return merged.slice(-500); // the console shows a window, like the world
        });
      }
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [worldId]);

  useEffect(() => {
    if (worldIdRef.current !== worldId) {
      worldIdRef.current = worldId;
      sinceId.current = 0;
      setEvents([]);
      setSelectedAgent(null);
    }
    void refreshState();
    void refreshEvents();
    const stateTimer = window.setInterval(() => void refreshState(), 1000);
    const eventTimer = window.setInterval(() => void refreshEvents(), 500);
    return () => {
      window.clearInterval(stateTimer);
      window.clearInterval(eventTimer);
    };
  }, [worldId, refreshState, refreshEvents]);

  if (error && !state) {
    return (
      <p style={{ color: colors.error }}>
        world {worldId} unreachable: {error}
      </p>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem", minWidth: 0 }}>
      <header style={{ display: "flex", alignItems: "baseline", gap: "1rem", flexWrap: "wrap" }}>
        <h1 style={{ margin: 0, color: colors.accent, fontSize: "1rem", letterSpacing: "0.2em" }}>
          world {worldId}
        </h1>
        {state && (
          <span style={{ color: colors.dim, fontSize: "0.75rem" }}>
            seed {state.seed} · tick {state.tick} · {state.width}×{state.height} ·{" "}
            <span style={{ color: state.paused ? colors.warn : colors.accent }}>
              {state.paused ? "paused" : "running"}
            </span>{" "}
            · {state.brains} brains
            {state.provider ? ` (${state.provider.provider}/${state.provider.model})` : ""}
          </span>
        )}
        {error && <span style={{ color: colors.error, fontSize: "0.7rem" }}>{error}</span>}
      </header>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: selectedAgent === null
            ? "minmax(280px, 1fr) minmax(280px, 1fr)"
            : "minmax(260px, 1fr) minmax(240px, 320px) minmax(300px, 360px)",
          gap: "0.75rem",
        }}
      >
        <section style={panelStyle} aria-label="world viewport">
          <h2 style={headingStyle}>world viewport</h2>
          <WorldViewport
            state={state}
            selectedAgentId={selectedAgent}
            onSelectAgent={setSelectedAgent}
          />
        </section>
        <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem", minWidth: 0 }}>
          <PopulationStats agents={agents} />
          <PopulationsPanel worldId={worldId} />
          <ParticipantPanel worldId={worldId} />
          <Controls
            worldId={worldId}
            paused={Boolean(state?.paused)}
            onChanged={() => void refreshState()}
            onStopped={onWorldsChanged}
          />
          <section style={panelStyle} aria-label="roster">
            <h2 style={headingStyle}>roster — click to inspect</h2>
            <ul
              style={{
                listStyle: "none",
                margin: 0,
                padding: 0,
                display: "flex",
                flexDirection: "column",
                gap: "0.2rem",
                maxHeight: 220,
                overflowY: "auto",
              }}
            >
              {agents.map((agent) => (
                <li key={agent.id}>
                  <button
                    style={{
                      ...buttonStyle,
                      width: "100%",
                      textAlign: "left",
                      borderColor: selectedAgent === agent.id ? colors.accent : colors.borderBright,
                    }}
                    onClick={() =>
                      setSelectedAgent(selectedAgent === agent.id ? null : agent.id)
                    }
                  >
                    #{agent.id} gen {agent.generation} · {agent.policy}
                    {agent.goal ? ` · ${agent.goal}` : ""}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        </div>
        {selectedAgent !== null && (
          <AgentInspector
            worldId={worldId}
            agentId={selectedAgent}
            onClose={() => setSelectedAgent(null)}
            onSelectAgent={setSelectedAgent}
          />
        )}
      </div>

      <EventStream events={events} />
    </div>
  );
}
