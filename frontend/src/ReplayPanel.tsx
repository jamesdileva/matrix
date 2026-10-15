// Replay panel (S37): the time machine. Scrub the timeline jump by
// jump — the viewport, the events and the comparison all read the
// same reconstruction, so what you watch is the world as it stood,
// rebuilt from its own log.

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { WorldState } from "./api";
import { WorldViewport } from "./WorldViewport";
import { buttonStyle, colors, headingStyle, inputStyle, panelStyle } from "./theme";

type Props = {
  worldId: number;
};

type Timeline = {
  events: number;
  first_tick: number;
  last_tick: number;
  by_type: Record<string, number>;
  births: number;
  generations: number;
  entities_seen: number;
};

type Diff = {
  from_tick: number;
  to_tick: number;
  entities_moved: Record<string, { from: unknown; to: unknown }>;
  entities_added: number[];
  entities_removed: number[];
  objects_added: number[];
  objects_removed: number[];
  resources_changed: Record<string, Record<string, { from: number; to: number }>>;
  culture_changed: Record<string, { from: string[] | null; to: string[] | null }>;
};

export function ReplayPanel({ worldId }: Props) {
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [position, setPosition] = useState(0);  // the event id we are standing after
  const [state, setState] = useState<WorldState | null>(null);
  const [nearby, setNearby] = useState<{ id: number; tick: number; type: string; actor_id: number | null }[]>([]);
  const [compareTo, setCompareTo] = useState<number | null>(null);
  const [diff, setDiff] = useState<Diff | null>(null);
  const [error, setError] = useState<string | null>(null);
  const last = useRef(0);

  const load = useCallback(
    async (at: number) => {
      try {
        const [nextTimeline, nextState] = await Promise.all([
          timeline ? Promise.resolve({ world_id: worldId, timeline }) : api.replayTimeline(worldId),
          api.replayState(worldId, { event_id: at }),
        ]);
        setTimeline(nextTimeline.timeline);
        setState(nextState as unknown as WorldState);
        const page = await api.replayEvents(worldId, {
          from_tick: nextState.tick,
          to_tick: nextState.tick,
          limit: 12,
        });
        setNearby(
          page.events.map((event) => ({
            id: event.id,
            tick: event.tick,
            type: event.type,
            actor_id: event.actor_id,
          })),
        );
        setError(null);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [worldId, timeline],
  );

  useEffect(() => {
    void load(0);
  }, [load]);

  useEffect(() => {
    if (timeline) {
      last.current = timeline.events;
      if (position > timeline.events) {
        setPosition(timeline.events);
      }
    }
  }, [timeline, position]);

  async function jump(eventId: number) {
    setPosition(eventId);
    setDiff(null);
    await load(eventId);
  }

  async function compare() {
    if (compareTo === null || !state) return;
    try {
      const body = await api.replayDiff(worldId, { a: state.tick, b: compareTo });
      setDiff(body.diff as Diff);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  if (error && !timeline) {
    return (
      <section style={panelStyle}>
        <h2 style={headingStyle}>replay</h2>
        <p style={{ color: colors.error, fontSize: "0.7rem" }}>{error}</p>
      </section>
    );
  }

  return (
    <section style={{ ...panelStyle, flex: 1 }} aria-label="replay">
      <h2 style={headingStyle}>time machine</h2>
      {timeline && (
        <p style={{ margin: 0, fontSize: "0.7rem", color: colors.dim }}>
          {timeline.events} events · ticks {timeline.first_tick}–{timeline.last_tick} ·{" "}
          {timeline.births} births · generation {timeline.generations}
        </p>
      )}

      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
        <button
          style={buttonStyle}
          onClick={() => void jump(Math.max(0, position - 1))}
          aria-label="step back"
        >
          ◀
        </button>
        <input
          style={{ ...inputStyle, flex: 1 }}
          type="range"
          min={0}
          max={Math.max(1, timeline?.events ?? 1)}
          value={position}
          onChange={(e) => void jump(Number(e.target.value))}
          aria-label="timeline scrubber"
        />
        <button
          style={buttonStyle}
          onClick={() => void jump(Math.min(timeline?.events ?? 0, position + 1))}
          aria-label="step forward"
        >
          ▶
        </button>
      </div>
      <div style={{ display: "flex", gap: "0.4rem", alignItems: "center" }}>
        <span style={{ fontSize: "0.7rem", color: colors.dim }}>at event #{position}</span>
        <button
          style={buttonStyle}
          onClick={() => void jump(0)}
        >
          origin
        </button>
        <button
          style={buttonStyle}
          onClick={() => void jump(timeline?.events ?? 0)}
        >
          now
        </button>
      </div>

      {state && (
        <div style={{ maxWidth: 420 }}>
          <WorldViewport
            state={state}
            selectedAgentId={null}
            onSelectAgent={() => undefined}
          />
        </div>
      )}

      <div style={{ fontSize: "0.65rem", color: colors.dim }}>
        {nearby.length > 0
          ? nearby.map((event) => `#${event.id} t${event.tick} ${event.type}`).join(" · ")
          : "nothing happens at this moment"}
      </div>

      <div style={{ display: "flex", gap: "0.4rem", alignItems: "center" }}>
        <span style={{ fontSize: "0.7rem", color: colors.dim }}>compare with tick</span>
        <input
          style={{ ...inputStyle, width: 80 }}
          type="number"
          min={0}
          value={compareTo ?? ""}
          onChange={(e) => setCompareTo(e.target.value === "" ? null : Number(e.target.value))}
          aria-label="compare tick"
        />
        <button style={buttonStyle} onClick={() => void compare()}>
          compare
        </button>
      </div>
      {diff && (
        <div style={{ fontSize: "0.68rem", color: colors.text }}>
          <div>
            moved {Object.keys(diff.entities_moved).length} · added{" "}
            {diff.entities_added.length} · removed {diff.entities_removed.length}
          </div>
          <div>
            objects +{diff.objects_added.length}/−{diff.objects_removed.length} ·
            culture changed for {Object.keys(diff.culture_changed).length}
          </div>
        </div>
      )}

      {error && <p style={{ color: colors.error, fontSize: "0.7rem" }}>{error}</p>}
    </section>
  );
}
