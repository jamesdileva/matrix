// World controls: pause / resume / step / stop (S13). Each maps to an
// existing Simulation API route; the dashboard only orchestrates.

import { useState } from "react";
import { api } from "./api";
import { buttonStyle, headingStyle, panelStyle } from "./theme";

type Props = {
  worldId: number;
  paused: boolean;
  onChanged: () => void;
  onStopped: () => void;
};

export function Controls({ worldId, paused, onChanged, onStopped }: Props) {
  const [busy, setBusy] = useState(false);

  async function act(action: () => Promise<unknown>) {
    setBusy(true);
    try {
      await action();
      onChanged();
    } catch (error) {
      console.error(error);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section style={panelStyle} aria-label="controls">
      <h2 style={headingStyle}>controls</h2>
      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
        <button
          style={buttonStyle}
          disabled={busy}
          onClick={() => act(() => (paused ? api.resume(worldId) : api.pause(worldId)))}
        >
          {paused ? "resume" : "pause"}
        </button>
        <button
          style={buttonStyle}
          disabled={busy}
          onClick={() => act(() => api.step(worldId))}
        >
          step
        </button>
        <button
          style={{ ...buttonStyle, color: "#ff9b9b", borderColor: "#5a2626" }}
          disabled={busy}
          onClick={async () => {
            await act(() => api.remove(worldId));
            onStopped();
          }}
        >
          stop
        </button>
      </div>
    </section>
  );
}
