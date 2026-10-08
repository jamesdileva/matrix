// Flood research console — the observer dashboard (S01's health console,
// grown into S13's watch-the-world dashboard).
//
// Left: world list + create form. Main: the selected world's viewport,
// population stats, controls and event stream — all polled from the
// Simulation API, so what you watch is the real backend timeline.

import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { Health, WorldState, WorldSummary } from "./api";
import { WorldDashboard } from "./WorldDashboard";
import { buttonStyle, colors, font, headingStyle, inputStyle, panelStyle } from "./theme";

const pageStyle: React.CSSProperties = {
  minHeight: "100vh",
  margin: 0,
  padding: "1rem",
  display: "grid",
  gridTemplateColumns: "minmax(220px, 260px) 1fr",
  gap: "1rem",
  alignItems: "start",
  backgroundColor: colors.bg,
  color: colors.text,
  fontFamily: font,
  boxSizing: "border-box",
};

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [worlds, setWorlds] = useState<WorldSummary[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [form, setForm] = useState({
    seed: "matrix",
    width: 32,
    height: 32,
    agents: 3,
    brains: "scripted",
    autostart: true,
  });
  const [error, setError] = useState<string | null>(null);

  const refreshWorlds = useCallback(async () => {
    try {
      const page = await api.worlds();
      setWorlds(page.worlds);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    api
      .health()
      .then(setHealth)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
    void refreshWorlds();
    const timer = window.setInterval(() => void refreshWorlds(), 2000);
    return () => window.clearInterval(timer);
  }, [refreshWorlds]);

  useEffect(() => {
    if (selected !== null && !worlds.some((w) => w.id === selected)) {
      setSelected(null); // the selected world was stopped
    }
  }, [worlds, selected]);

  async function createWorld() {
    try {
      const created: WorldState = await api.createWorld(form);
      setSelected(created.id);
      await refreshWorlds();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <main style={pageStyle}>
      <aside style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
        <header>
          <h1 style={{ margin: 0, color: colors.accent, letterSpacing: "0.5em" }}>FLOOD</h1>
          <p style={{ margin: 0, opacity: 0.7, fontSize: "0.75rem" }}>
            observer console
            {health ? ` · backend ${health.status}` : " · backend unreachable"}
          </p>
        </header>

        <section style={panelStyle} aria-label="create world">
          <h2 style={headingStyle}>new world</h2>
          <label style={labelStyle}>
            seed
            <input
              style={inputStyle}
              value={form.seed}
              onChange={(e) => setForm({ ...form, seed: e.target.value })}
            />
          </label>
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <label style={{ ...labelStyle, flex: 1 }}>
              agents
              <input
                style={inputStyle}
                type="number"
                min={0}
                max={64}
                value={form.agents}
                onChange={(e) => setForm({ ...form, agents: Number(e.target.value) })}
              />
            </label>
            <label style={{ ...labelStyle, flex: 1 }}>
              brains
              <select
                style={inputStyle}
                value={form.brains}
                onChange={(e) => setForm({ ...form, brains: e.target.value })}
              >
                <option value="scripted">scripted</option>
                <option value="model">model</option>
              </select>
            </label>
          </div>
          <label style={{ ...labelStyle, flexDirection: "row", alignItems: "center", gap: "0.5rem" }}>
            <input
              type="checkbox"
              checked={form.autostart}
              onChange={(e) => setForm({ ...form, autostart: e.target.checked })}
            />
            auto-start
          </label>
          <button style={buttonStyle} onClick={createWorld}>
            create world
          </button>
        </section>

        <section style={panelStyle} aria-label="worlds">
          <h2 style={headingStyle}>live worlds ({worlds.length})</h2>
          <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: "0.25rem" }}>
            {worlds.map((world) => (
              <li key={world.id}>
                <button
                  style={{
                    ...buttonStyle,
                    width: "100%",
                    textAlign: "left",
                    borderColor: selected === world.id ? colors.accent : colors.borderBright,
                    color: selected === world.id ? colors.accent : colors.text,
                  }}
                  onClick={() => setSelected(world.id)}
                >
                  #{world.id} {world.seed} · t{world.tick} · {world.agents}a · {world.brains}
                  {world.paused ? " · paused" : ""}
                </button>
              </li>
            ))}
            {worlds.length === 0 && (
              <li style={{ color: colors.dim, fontSize: "0.75rem" }}>no live worlds</li>
            )}
          </ul>
        </section>

        {error && (
          <p style={{ margin: 0, color: colors.error, fontSize: "0.75rem" }}>{error}</p>
        )}
      </aside>

      <section style={{ minWidth: 0 }}>
        {selected === null ? (
          <p style={{ color: colors.dim }}>select or create a world to watch it.</p>
        ) : (
          <WorldDashboard worldId={selected} onWorldsChanged={() => void refreshWorlds()} />
        )}
      </section>
    </main>
  );
}

const labelStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: "0.2rem",
  fontSize: "0.7rem",
  color: colors.dim,
};
