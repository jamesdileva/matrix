// Population stats: generation spread, active agents, policy mix (S13).

import type { AgentSummary } from "./api";
import { colors, headingStyle, panelStyle } from "./theme";

type Props = {
  agents: AgentSummary[];
};

export function PopulationStats({ agents }: Props) {
  const generations = agents.map((a) => a.generation);
  const min = generations.length ? Math.min(...generations) : 0;
  const max = generations.length ? Math.max(...generations) : 0;
  const model = agents.filter((a) => a.policy === "model").length;
  const scripted = agents.length - model;
  const newest = agents.length
    ? agents.reduce((a, b) => (b.generation > a.generation ? b : a))
    : null;

  return (
    <section style={panelStyle} aria-label="population stats">
      <h2 style={headingStyle}>population</h2>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.5rem 1rem" }}>
        <Stat label="active agents" value={String(agents.length)} accent />
        <Stat label="generations" value={`${min} .. ${max}`} />
        <Stat label="model minds" value={String(model)} />
        <Stat label="scripted minds" value={String(scripted)} />
      </div>
      {newest && (
        <p style={{ margin: 0, fontSize: "0.7rem", color: colors.dim }}>
          deepest lineage: agent {newest.id} — generation {newest.generation}
          {newest.parent_id !== null ? `, child of ${newest.parent_id}` : " (founder)"}
        </p>
      )}
    </section>
  );
}

function Stat({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div>
      <div style={{ fontSize: "0.65rem", color: colors.dim, letterSpacing: "0.1em" }}>{label}</div>
      <div style={{ fontSize: "1.1rem", color: accent ? colors.accent : colors.text }}>{value}</div>
    </div>
  );
}
