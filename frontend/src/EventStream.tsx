// The event stream: real backend events, newest first, color-coded by
// family (S13). The dashboard appends from since_id — the same
// timeline the database persists, so what you watch is what replay
// would rebuild.

import { useEffect, useRef } from "react";
import type { WorldEvent } from "./api";
import { colors, font, headingStyle, panelStyle } from "./theme";

const EVENT_COLORS: Record<string, string> = {
  WORLD_SEEDED: colors.dim,
  OBJECT_CREATED: colors.dim,
  ENTITY_ADDED: colors.dim,
  ENTITY_REMOVED: colors.dim,
  ACTION_EXECUTED: colors.text,
  ACTION_REJECTED: colors.warn,
  MODEL_DECISION: colors.decision,
  MODEL_ERROR: colors.error,
  AGENT_MESSAGE: colors.message,
  AGENT_BORN: colors.lineage,
  // S28: the network's letters ride the same timeline in the same
  // voice as spoken words.
  SPEECH: colors.message,
  DIRECT: colors.message,
  ANNOUNCE: colors.message,
  BROADCAST: colors.message,
  // S29: culture's events — a discovery, a crafting, an invention.
  INVENTION: colors.lineage,
  CRAFT: colors.lineage,
  // S30: the settlement's events — founded, joined, grown, banked,
  // paved, claimed.
  SETTLEMENT_FOUNDED: colors.lineage,
  SETTLEMENT_JOINED: colors.lineage,
  SETTLEMENT_GROWN: colors.lineage,
  SETTLEMENT_STORAGE: colors.lineage,
  ROAD_LAID: colors.dim,
  ZONE_CLAIMED: colors.lineage,
  // S31: games — proposed, played, finished.
  GAME_PROPOSED: colors.decision,
  GAME_STARTED: colors.decision,
  GAME_MOVE: colors.decision,
  GAME_OVER: colors.accent,
};

function summarize(event: WorldEvent): string {
  const payload = event.payload ?? {};
  const type = event.type;
  if (type === "ACTION_EXECUTED" || type === "ACTION_REJECTED") {
    const action = payload.action as { action?: string; direction?: string } | undefined;
    const verb = action?.action ?? "?";
    const direction = action?.direction ? ` ${action.direction}` : "";
    const reason = payload.reason ? ` — ${payload.reason}` : "";
    return `${verb}${direction}${reason}`;
  }
  if (type === "MODEL_DECISION") {
    const decision = payload.decision as { action?: { action?: string } } | undefined;
    return `decision: ${decision?.action?.action ?? "?"} (${String(payload.provider ?? "?")})`;
  }
  if (type === "MODEL_ERROR") return `no decision: ${String(payload.reason ?? "?").slice(0, 60)}`;
  if (type === "AGENT_MESSAGE") return `"${String(payload.message ?? "").slice(0, 60)}"`;
  // S28: letters, announcements and broadcasts read like speech, with
  // their address attached.
  if (type === "SPEECH") return `"${String(payload.message ?? "").slice(0, 60)}"`;
  if (type === "DIRECT")
    return `to ${String(event.target_id ?? "?")}: "${String(payload.message ?? "").slice(0, 60)}"`;
  if (type === "ANNOUNCE")
    return `to ${String(payload.scope ?? "?")}: "${String(payload.message ?? "").slice(0, 60)}"`;
  if (type === "BROADCAST") return `to all: "${String(payload.message ?? "").slice(0, 60)}"`;
  // S29: the discovery, the crafting, the invention.
  if (type === "INVENTION")
    return payload.kind === "discovery"
      ? `discovered ${String(payload.name ?? "?")}`
      : `invented ${String(payload.result ?? "?")} from ${String(payload.from ?? "")}`;
  if (type === "CRAFT") return `crafted ${String(payload.object_type ?? "?")} (${String(payload.recipe ?? "?")})`;
  // S30: the settlement named, joined, grown, banked, paved, claimed.
  if (type === "SETTLEMENT_FOUNDED")
    return `founded ${String(payload.name ?? "?")} on structure ${String(payload.structure_id ?? "?")}`;
  if (type === "SETTLEMENT_JOINED") return `joined ${String(payload.name ?? "?")}`;
  if (type === "SETTLEMENT_GROWN")
    return `${String(payload.kind ?? "?")} structure ${String(payload.structure_id ?? "?")} adopted`;
  if (type === "SETTLEMENT_STORAGE")
    return `${String(payload.kind ?? "?")} ${String(payload.amount ?? "?")} ${String(payload.resource ?? "?")}`;
  if (type === "ROAD_LAID") return `${String((payload.cells as unknown[] | undefined)?.length ?? "?")} cells paved`;
  if (type === "ZONE_CLAIMED")
    return payload.released
      ? `released object ${String(payload.object_id ?? "?")}`
      : `claimed ${String(payload.resource ?? "?")} @${String(payload.object_id ?? "?")}`;
  // S31: the game proposed, the move played, the game won.
  if (type === "GAME_PROPOSED")
    return `proposed ${String(payload.name ?? "?")} for ${String(payload.players ?? "?")} players`;
  if (type === "GAME_STARTED")
    return `players ${(payload.players as number[] | undefined)?.join(", ") ?? "?"} seated`;
  if (type === "GAME_MOVE")
    return `played ${String(payload.move ?? "?")} — ${JSON.stringify(payload.state ?? {})}`;
  if (type === "GAME_OVER")
    return `${String(payload.winner ?? "?")} wins (${String(payload.win_reason ?? "?")})`;
  if (type === "AGENT_BORN") {
    return `gen ${String(payload.generation)} child of ${String(payload.parent_id)}`;
  }
  return "";
}

type Props = {
  events: WorldEvent[];
};

export function EventStream({ events }: Props) {
  const listRef = useRef<HTMLOListElement>(null);
  const previousCount = useRef(0);
  const pinned = useRef(true);

  useEffect(() => {
    const list = listRef.current;
    if (!list) return;
    const atBottom =
      list.scrollHeight - list.scrollTop - list.clientHeight < 40;
    if (events.length < previousCount.current) {
      pinned.current = true; // a different world was selected — jump to newest
    } else if (!atBottom) {
      pinned.current = false; // the human scrolled up — hold position
    }
    if (pinned.current) list.scrollTop = list.scrollHeight;
    previousCount.current = events.length;
  }, [events]);

  return (
    <section style={{ ...panelStyle, flex: 1, minHeight: 200 }} aria-label="event stream">
      <h2 style={headingStyle}>event stream ({events.length})</h2>
      <ol
        ref={listRef}
        data-testid="event-stream"
        style={{
          listStyle: "none",
          margin: 0,
          padding: 0,
          overflowY: "auto",
          flex: 1,
          fontFamily: font,
          fontSize: "0.7rem",
          display: "flex",
          flexDirection: "column",
          gap: "0.15rem",
        }}
      >
        {events.map((event) => (
          <li key={event.id} style={{ display: "flex", gap: "0.5rem", whiteSpace: "nowrap" }}>
            <span style={{ color: colors.dim, minWidth: "3.5rem" }}>#{event.id}</span>
            <span style={{ color: colors.dim, minWidth: "3rem" }}>t{event.tick}</span>
            <span style={{ color: EVENT_COLORS[event.type] ?? colors.text, minWidth: "9.5rem" }}>
              {event.type}
            </span>
            {event.actor_id !== null && (
              <span style={{ color: colors.dim, minWidth: "2.5rem" }}>a{event.actor_id}</span>
            )}
            <span style={{ color: colors.text, overflow: "hidden", textOverflow: "ellipsis" }}>
              {summarize(event)}
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}
