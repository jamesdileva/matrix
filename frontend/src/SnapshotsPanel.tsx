// Snapshots panel (S38): save the world, list its saves, restore it.
// A civilization that can be put down and picked back up — the console
// face of autosave, recovery and world resume.

import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { WorldSnapshot } from "./api";
import { buttonStyle, colors, headingStyle, panelStyle } from "./theme";

type Props = {
  worldId: number;
  onRestored?: () => void;
};

export function SnapshotsPanel({ worldId, onRestored }: Props) {
  const [snapshots, setSnapshots] = useState<WorldSnapshot[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const body = await api.snapshots(worldId);
      setSnapshots(body.snapshots);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [worldId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function save(kind: "manual" | "archive") {
    setBusy(true);
    try {
      await api.saveSnapshot(worldId, kind);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function restore(snapshotId?: number) {
    setBusy(true);
    try {
      await api.restoreSnapshot(worldId, snapshotId);
      onRestored?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section style={panelStyle} aria-label="snapshots">
      <h2 style={headingStyle}>snapshots</h2>
      <div style={{ display: "flex", gap: "0.4rem" }}>
        <button style={buttonStyle} disabled={busy} onClick={() => void save("manual")}>
          save
        </button>
        <button style={buttonStyle} disabled={busy} onClick={() => void save("archive")}>
          archive
        </button>
        <button style={buttonStyle} disabled={busy} onClick={() => void restore()}>
          restore latest
        </button>
      </div>
      <ul
        style={{
          listStyle: "none",
          margin: 0,
          padding: 0,
          display: "flex",
          flexDirection: "column",
          gap: "0.2rem",
          maxHeight: 160,
          overflowY: "auto",
          fontSize: "0.68rem",
        }}
      >
        {snapshots.map((snapshot) => (
          <li
            key={snapshot.id}
            style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}
          >
            <span style={{ flex: 1, color: colors.dim }}>
              #{snapshot.id} · tick {snapshot.tick} · {snapshot.kind}
            </span>
            <button
              style={buttonStyle}
              disabled={busy}
              onClick={() => void restore(snapshot.id)}
            >
              restore
            </button>
          </li>
        ))}
        {snapshots.length === 0 && (
          <li style={{ color: colors.dim }}>no snapshots yet</li>
        )}
      </ul>
      {error && <p style={{ color: colors.error, fontSize: "0.7rem" }}>{error}</p>}
    </section>
  );
}
