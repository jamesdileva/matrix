// Games panel (S31): the tables in this world — proposed games, open
// seats, your turn, your legal moves. The rules are data: the panel
// proposes them as JSON, and the same panel is how the human takes a
// seat and plays a game the Flood invented.

import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { GameSession } from "./api";
import { buttonStyle, colors, headingStyle, inputStyle, panelStyle } from "./theme";
import type { Participant } from "./api";

type Props = {
  worldId: number;
  participant: Participant | null;
};

const A_SIMPLE_GAME = JSON.stringify(
  {
    name: "Stride Race",
    players: 2,
    setup: { track: 0 },
    description: "Stride down the track; first to eight wins.",
    moves: {
      stride: {
        description: "one step down the track",
        requires: { track: "<8" },
        effect: { add: { track: 1 } },
      },
    },
    win: { first_to: { track: 8 } },
  },
  null,
  2,
);

export function GamesPanel({ worldId, participant }: Props) {
  const [sessions, setSessions] = useState<GameSession[]>([]);
  const [games, setGames] = useState<{ id: number; name: string }[]>([]);
  const [draft, setDraft] = useState(A_SIMPLE_GAME);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [nextGames, nextSessions] = await Promise.all([
        api.games(worldId),
        api.gameSessions(worldId),
      ]);
      setGames(nextGames.games.map((game) => ({ id: game.id, name: game.name })));
      setSessions(nextSessions.sessions);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [worldId]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 1000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  async function run(action: () => Promise<unknown>) {
    try {
      await action();
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <section style={panelStyle} aria-label="games">
      <h2 style={headingStyle}>games ({games.length})</h2>

      <details>
        <summary style={{ cursor: "pointer", fontSize: "0.7rem", color: colors.dim }}>
          propose rules as data
        </summary>
        <textarea
          style={{ ...inputStyle, marginTop: "0.4rem", minHeight: 110, fontFamily: "monospace" }}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          aria-label="rules json"
        />
        <button
          style={{ ...buttonStyle, marginTop: "0.3rem" }}
          onClick={() =>
            run(async () => {
              const rules = JSON.parse(draft) as unknown;
              await api.proposeGame(worldId, rules);
            })
          }
        >
          propose game
        </button>
      </details>

      <ul style={{ listStyle: "none", margin: "0.4rem 0 0", padding: 0, fontSize: "0.7rem" }}>
        {games.map((game) => (
          <li key={game.id} style={{ display: "flex", justifyContent: "space-between" }}>
            <span style={{ color: colors.text }}>{game.name}</span>
            <button style={buttonStyle} onClick={() => run(() => api.openGame(worldId, game.id))}>
              open table
            </button>
          </li>
        ))}
      </ul>

      {sessions.map((session) => (
        <SessionRow
          key={session.id}
          worldId={worldId}
          session={session}
          seated={
            participant ? session.players.includes(participant.participant?.entity_id ?? -1) : false
          }
          onDone={refresh}
          onError={setError}
        />
      ))}
      {sessions.length === 0 && (
        <p style={{ margin: 0, color: colors.dim, fontSize: "0.75rem" }}>no tables yet</p>
      )}
      {error && (
        <p style={{ margin: "0.4rem 0 0", color: colors.error, fontSize: "0.7rem" }}>{error}</p>
      )}
    </section>
  );
}

function SessionRow({
  worldId,
  session,
  seated,
  onDone,
  onError,
}: {
  worldId: number;
  session: GameSession;
  seated: boolean;
  onDone: () => void;
  onError: (message: string) => void;
}) {
  const state = Object.entries(session.state)
    .map(([key, value]) => `${key} ${value}`)
    .join(", ");

  return (
    <div style={{ borderTop: `1px solid ${colors.border}`, paddingTop: "0.35rem", fontSize: "0.7rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <strong style={{ color: colors.accent }}>{session.name}</strong>
        <span style={{ color: colors.dim }}>
          #{session.id} · {session.status}
          {session.winner !== null && session.win_reason
            ? ` · won by ${session.winner} (${session.win_reason})`
            : ""}
        </span>
      </div>
      <div style={{ color: colors.dim, marginTop: "0.1rem" }}>
        seats {session.players.join(", ") || "empty"} · {state}
      </div>
      <div style={{ display: "flex", gap: "0.3rem", marginTop: "0.25rem", flexWrap: "wrap" }}>
        {session.legal_moves.map((move) => (
          <button
            key={move}
            style={{ ...buttonStyle, opacity: session.your_turn ? 1 : 0.45 }}
            disabled={!session.your_turn}
            onClick={() =>
              api
                .playMove(worldId, session.id, move)
                .then(onDone)
                .catch((e: unknown) => onError(e instanceof Error ? e.message : String(e)))
            }
          >
            {move}
          </button>
        ))}
        {seated && session.status === "finished" && (
          <span style={{ color: colors.dim }}>the table is closed</span>
        )}
      </div>
    </div>
  );
}
