// Settlements panel (S30): the communities standing in the world —
// names, people, homes, shared contents, held zones. What you see is
// the world's own registry, the same numbers the API's other
// consumers get.

import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { SettlementStats, Settlements as SettlementsPage } from "./api";
import { colors, headingStyle, panelStyle } from "./theme";

type Props = {
  worldId: number;
};

export function SettlementsPanel({ worldId }: Props) {
  const [page, setPage] = useState<SettlementsPage | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setPage(await api.settlements(worldId));
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

  return (
    <section style={panelStyle} aria-label="settlements">
      <h2 style={headingStyle}>settlements ({page?.settlements.length ?? 0})</h2>
      {page && page.settlements.length === 0 && (
        <p style={{ margin: 0, color: colors.dim, fontSize: "0.75rem" }}>
          no settlements in this world — a population that builds a home and names it founds one
        </p>
      )}
      {page?.settlements.map((settlement) => (
        <SettlementRow key={settlement.id} settlement={settlement} />
      ))}
      {error && (
        <p style={{ margin: "0.4rem 0 0", color: colors.error, fontSize: "0.7rem" }}>{error}</p>
      )}
    </section>
  );
}

function SettlementRow({ settlement }: { settlement: SettlementStats }) {
  const contents = Object.entries(settlement.contents);
  return (
    <div
      style={{
        padding: "0.35rem 0",
        borderBottom: `1px solid ${colors.border}`,
        fontSize: "0.7rem",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", gap: "0.5rem" }}>
        <strong style={{ color: colors.accent }}>{settlement.name}</strong>
        <span style={{ color: colors.dim }}>
          #{settlement.id} · founded t{settlement.founded_tick} by {settlement.founder_id}
        </span>
      </div>
      <div style={{ color: colors.dim, marginTop: "0.15rem" }}>
        {settlement.members_with_roles
          .map((member) => `${member.agent_id} (${member.role})`)
          .join(", ")}
      </div>
      <div style={{ color: colors.dim, marginTop: "0.1rem" }}>
        homes {settlement.homes} · storehouses {settlement.storage_structures} · roads{" "}
        {settlement.roads} ({settlement.road_cells.length} cells)
      </div>
      <div style={{ color: colors.dim, marginTop: "0.1rem" }}>
        shared:{" "}
        {contents.length > 0
          ? contents.map(([kind, amount]) => `${amount} ${kind}`).join(", ")
          : "empty"}
        {" · "}zones:{" "}
        {settlement.zones.length > 0
          ? settlement.zones.map((zone) => `${zone.resource} @${zone.object_id}`).join(", ")
          : "none"}
      </div>
    </div>
  );
}
