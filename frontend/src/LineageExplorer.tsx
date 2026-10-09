// The lineage explorer (S15): this agent's ancestry, founder first.
//
// The chain rail is both the view and the navigation — clicking any
// ancestor inspects that agent instead (the roadmap's check: select
// the deepest agent, navigate to the founder and every generation
// between). Each member carries drift indicators against the lineage's
// originals, and the inspected generation gets an inherited-
// information comparison.

import { useEffect, useState } from "react";
import { api } from "./api";
import type { Lineage, LineageMember } from "./api";
import { colors, font, headingStyle } from "./theme";

type Props = {
  worldId: number;
  agentId: number;
  onSelectAgent: (agentId: number) => void;
};

export function LineageExplorer({ worldId, agentId, onSelectAgent }: Props) {
  const [lineage, setLineage] = useState<Lineage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const next = await api.agentLineage(worldId, agentId);
        if (!cancelled) {
          setLineage(next);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    }
    void load();
    const timer = window.setInterval(() => void load(), 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [worldId, agentId]);

  if (error && !lineage) {
    return <p style={{ color: colors.error, margin: 0, fontSize: "0.7rem" }}>lineage: {error}</p>;
  }
  if (!lineage) {
    return <p style={{ color: colors.dim, margin: 0, fontSize: "0.7rem" }}>lineage: loading…</p>;
  }

  const selected = lineage.chain[lineage.chain.length - 1];

  return (
    <div data-testid="lineage-explorer">
      <h2 style={headingStyle}>lineage — {lineage.chain.length} generations</h2>

      {/* The rail: founder at the top, the selected agent at the bottom. */}
      <ol
        style={{
          listStyle: "none",
          margin: 0,
          padding: 0,
          display: "flex",
          flexDirection: "column",
          fontSize: "0.68rem",
          maxHeight: 240,
          overflowY: "auto",
        }}
      >
        {lineage.chain.map((member, index) => (
          <li key={member.id}>
            <RailNode
              member={member}
              isFirst={index === 0}
              isLast={index === lineage.chain.length - 1}
              isSelected={member.id === agentId}
              previous={index > 0 ? lineage.chain[index - 1] : null}
              onSelectAgent={onSelectAgent}
            />
          </li>
        ))}
      </ol>

      {selected && <Comparison member={selected} />}
    </div>
  );
}

function RailNode({
  member,
  isFirst,
  isLast,
  isSelected,
  previous,
  onSelectAgent,
}: {
  member: LineageMember;
  isFirst: boolean;
  isLast: boolean;
  isSelected: boolean;
  previous: LineageMember | null;
  onSelectAgent: (agentId: number) => void;
}) {
  const drift = member.drift;
  return (
    <button
      onClick={() => onSelectAgent(member.id)}
      style={{
        background: "none",
        border: "none",
        borderLeft: `2px solid ${isSelected ? colors.accent : colors.border}`,
        width: "100%",
        textAlign: "left",
        padding: "0.25rem 0 0.25rem 0.6rem",
        cursor: "pointer",
        fontFamily: font,
        color: isSelected ? colors.accent : colors.text,
        display: "flex",
        flexDirection: "column",
        gap: "0.1rem",
      }}
    >
      <span style={{ display: "flex", gap: "0.4rem", alignItems: "baseline", flexWrap: "wrap" }}>
        <span style={{ color: colors.dim }}>gen {member.generation}</span>
        <span>
          #{member.id}
          {member.policy === "model" ? " · model" : ""}
        </span>
        <span style={{ color: colors.dim }}>
          {member.knowledge_count} facts · {member.artifacts_count} artifacts
        </span>
        {member.children.length > 0 && (
          <span style={{ color: colors.lineage }}>
            → {member.children.length} child{member.children.length === 1 ? "" : "ren"}
          </span>
        )}
      </span>
      {!isFirst && previous && (
        <span style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap", fontSize: "0.62rem" }}>
          <DriftChip kind="retained" count={drift.retained.length} />
          <DriftChip kind="lost" count={drift.lost.length} />
          <DriftChip kind="altered" count={drift.altered.length + drift.contradicted.length} />
          <DriftChip kind="new" count={drift.new.length} />
          <span style={{ color: colors.dim }}>similarity {drift.avg_similarity}</span>
        </span>
      )}
      {isFirst && (
        <span style={{ fontSize: "0.62rem", color: colors.dim }}>
          founder{member.inheritance_message ? ` · "${member.inheritance_message}"` : ""}
        </span>
      )}
      {!isLast && member.inheritance_message && (
        <span style={{ fontSize: "0.62rem", color: colors.message }}>
          passed on: "{member.inheritance_message}"
        </span>
      )}
    </button>
  );
}

function DriftChip({ kind, count }: { kind: "retained" | "lost" | "altered" | "new"; count: number }) {
  const color =
    kind === "retained"
      ? colors.accent
      : kind === "lost"
        ? colors.error
        : kind === "altered"
          ? colors.warn
          : colors.decision;
  const label = kind === "altered" ? "altered" : kind;
  return (
    <span style={{ color: count > 0 ? color : colors.dim }}>
      {count > 0 ? `${count} ${label}` : `no ${label}`}
    </span>
  );
}

function Comparison({ member }: { member: LineageMember }) {
  const drift = member.drift;
  const hasCulture =
    drift.retained.length + drift.altered.length + drift.new.length + drift.lost.length > 0;

  return (
    <div style={{ borderTop: `1px solid ${colors.border}`, paddingTop: "0.4rem", marginTop: "0.4rem" }}>
      <h2 style={headingStyle}>inherited information — generation {member.generation}</h2>
      {!hasCulture ? (
        <p style={{ margin: 0, fontSize: "0.7rem", color: colors.dim }}>
          this lineage carries no facts to compare
        </p>
      ) : (
        <div style={{ fontSize: "0.68rem", display: "flex", flexDirection: "column", gap: "0.3rem" }}>
          <FactList title="retained" facts={drift.retained} color={colors.accent} />
          <FactList title="lost" facts={drift.lost} color={colors.error} />
          <FactList title="altered" facts={drift.altered} color={colors.warn} />
          <FactList title="contradicted" facts={drift.contradicted} color={colors.error} />
          <FactList title="new" facts={drift.new} color={colors.decision} />
          <span style={{ color: colors.dim }}>
            avg similarity to the lineage's originals: {drift.avg_similarity}
          </span>
        </div>
      )}
    </div>
  );
}

function FactList({ title, facts, color }: { title: string; facts: string[]; color: string }) {
  if (facts.length === 0) return null;
  return (
    <div>
      <span style={{ color }}>{title}: </span>
      <span style={{ color: colors.text }}>{facts.join(" · ")}</span>
    </div>
  );
}
