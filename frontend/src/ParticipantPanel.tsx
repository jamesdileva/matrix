// The participant panel (S20): the Observer/Participant mode switch.
//
// Joining places a real entity in the world (id 1001) that moves
// through the same validated actions as agents; the simulation keeps
// ticking while you walk. The 3D view of the avatar lives in the
// Godot client (P to join there too) — this is the web-side control.

import { useEffect, useState } from "react";
import { api } from "./api";
import type { Participant } from "./api";
import { buttonStyle, colors, headingStyle, panelStyle } from "./theme";

const DIRECTIONS = ["north", "west", "east", "south"] as const;

type Props = {
  worldId: number;
};

export function ParticipantPanel({ worldId }: Props) {
  const [participant, setParticipant] = useState<Participant["participant"]>(null);
  const [joined, setJoined] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const next = await api.participant(worldId);
        if (!cancelled) {
          setParticipant(next.participant);
          setJoined(next.participant !== null);
          setMessage(null);
        }
      } catch (e) {
        if (!cancelled) setMessage(e instanceof Error ? e.message : String(e));
      }
    }
    void load();
    const timer = window.setInterval(() => void load(), 1000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [worldId]);

  async function join() {
    const result = await api.participantJoin(worldId);
    setParticipant(result.participant);
    setJoined(true);
  }

  async function leave() {
    await api.participantLeave(worldId);
    setParticipant(null);
    setJoined(false);
  }

  async function move(direction: string) {
    const result = await api.participantMove(worldId, direction);
    if (result.position) setParticipant({ entity_id: 1001, position: result.position });
    if (!result.ok) setMessage(result.reason ?? "rejected");
  }

  return (
    <section style={panelStyle} aria-label="participant">
      <h2 style={headingStyle}>participant mode</h2>
      {joined ? (
        <>
          <p style={{ margin: 0, fontSize: "0.72rem", color: colors.text }}>
            in the world at{" "}
            <span style={{ color: colors.accent }}>
              ({participant?.position.x ?? "?"}, {participant?.position.y ?? "?"})
            </span>
          </p>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(3, 1fr)",
              gap: "0.25rem",
              maxWidth: 150,
            }}
          >
            {DIRECTIONS.map((direction, index) => (
              <button
                key={direction}
                style={{
                  ...buttonStyle,
                  gridColumn: index === 1 ? 2 : index === 0 ? 1 : index === 2 ? 3 : 2,
                  gridRow: index === 0 ? 1 : index === 3 ? 3 : 2,
                }}
                onClick={() => void move(direction)}
              >
                {direction[0].toUpperCase()}
              </button>
            ))}
          </div>
          <button style={buttonStyle} onClick={() => void leave()}>
            leave the world
          </button>
        </>
      ) : (
        <>
          <p style={{ margin: 0, fontSize: "0.7rem", color: colors.dim }}>
            watching as an observer. Join to walk the Void yourself — the world keeps
            ticking while you're in it.
          </p>
          <button style={buttonStyle} onClick={() => void join()}>
            join as participant
          </button>
        </>
      )}
      {message && <p style={{ margin: 0, fontSize: "0.68rem", color: colors.error }}>{message}</p>}
    </section>
  );
}
