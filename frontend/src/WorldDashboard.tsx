// The observer dashboard for one world (S13).
//
// Polls the Simulation API: state + agents at 1 Hz, events at 2 Hz
// (since_id tracking). Everything shown comes from real backend
// events — the same timeline the database persists.

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { AgentSummary, WorldEvent, WorldState } from "./api";
import { Controls } from "./Controls";
import { EventStream } from "./EventStream";
import { PopulationStats } from "./PopulationStats";
import { WorldViewport } from "./WorldViewport";
import { colors, headingStyle, panelStyle } from "./theme";

type Props = {
  worldId: number;
  onWorldsChanged: () => void;
};

export function WorldDashboard({ worldId, onWorldsChanged }: Props) {
  const [state, setState] = useState<WorldState | null>(null);
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [events, setEvents] = useState<WorldEvent[]>([]);
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

      <div style={{ display: "grid", gridTemplateColumns: "minmax(280px, 1fr) minmax(280px, 1fr)", gap: "0.75rem" }}>
        <section style={panelStyle} aria-label="world viewport">
          <h2 style={headingStyle}>world viewport</h2>
          <WorldViewport state={state} />
        </section>
        <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem", minWidth: 0 }}>
          <PopulationStats agents={agents} />
          <Controls
            worldId={worldId}
            paused={Boolean(state?.paused)}
            onChanged={() => void refreshState()}
            onStopped={onWorldsChanged}
          />
        </div>
      </div>

      <EventStream events={events} />
    </div>
  );
}
