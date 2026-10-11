// Populations panel (S27): every group in the world, with its spawn
// rule and live statistics — and a form to found a new one into a
// running world. What you see is the manager's own statistics, the
// same numbers the API's other consumers get.

import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { PopulationStats, Populations as PopulationsPage } from "./api";
import { buttonStyle, colors, headingStyle, inputStyle, panelStyle } from "./theme";

type Props = {
  worldId: number;
};

const POLICY_OPTIONS = ["wander", "forage", "gather"];

export function PopulationsPanel({ worldId }: Props) {
  const [page, setPage] = useState<PopulationsPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({
    name: "newcomers",
    members: 2,
    policy: "wander",
    max_members: "",
    top_up: false,
    stipend: "0",
  });

  const refresh = useCallback(async () => {
    try {
      setPage(await api.populations(worldId));
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

  async function addPopulation() {
    try {
      await api.addPopulation(worldId, {
        name: form.name,
        members: form.members,
        policies: [form.policy],
        max_members: form.max_members === "" ? null : Number(form.max_members),
        top_up: form.top_up,
        stipend: { wood: Number(form.stipend) || 0 },
      });
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <section style={panelStyle} aria-label="populations">
      <h2 style={headingStyle}>populations ({page?.totals.populations ?? 0})</h2>
      {page && page.populations.length === 0 && (
        <p style={{ margin: 0, color: colors.dim, fontSize: "0.75rem" }}>
          no populations in this world
        </p>
      )}
      {page?.populations.map((population) => (
        <PopulationRow key={population.population_id} population={population} />
      ))}
      <div style={{ display: "flex", flexDirection: "column", gap: "0.35rem", marginTop: "0.5rem" }}>
        <div style={{ display: "flex", gap: "0.4rem" }}>
          <input
            style={{ ...inputStyle, flex: 2 }}
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            aria-label="new population name"
          />
          <input
            style={{ ...inputStyle, flex: 1 }}
            type="number"
            min={0}
            max={16}
            value={form.members}
            onChange={(e) => setForm({ ...form, members: Number(e.target.value) })}
            aria-label="members"
          />
        </div>
        <div style={{ display: "flex", gap: "0.4rem" }}>
          <select
            style={{ ...inputStyle, flex: 1 }}
            value={form.policy}
            onChange={(e) => setForm({ ...form, policy: e.target.value })}
            aria-label="founding policy"
          >
            {POLICY_OPTIONS.map((policy) => (
              <option key={policy} value={policy}>
                {policy}
              </option>
            ))}
          </select>
          <input
            style={{ ...inputStyle, flex: 1 }}
            type="number"
            min={0}
            value={form.stipend}
            onChange={(e) => setForm({ ...form, stipend: e.target.value })}
            aria-label="wood stipend"
          />
        </div>
        <div style={{ display: "flex", gap: "0.4rem", alignItems: "center" }}>
          <input
            style={{ ...inputStyle, flex: 1 }}
            type="number"
            min={0}
            placeholder="cap"
            value={form.max_members}
            onChange={(e) => setForm({ ...form, max_members: e.target.value })}
            aria-label="member cap"
          />
          <label style={{ display: "flex", alignItems: "center", gap: "0.3rem", fontSize: "0.7rem", color: colors.dim }}>
            <input
              type="checkbox"
              checked={form.top_up}
              onChange={(e) => setForm({ ...form, top_up: e.target.checked })}
            />
            top up
          </label>
        </div>
        <button style={buttonStyle} onClick={addPopulation}>
          found population
        </button>
      </div>
      {error && (
        <p style={{ margin: "0.4rem 0 0", color: colors.error, fontSize: "0.7rem" }}>{error}</p>
      )}
    </section>
  );
}

function PopulationRow({ population }: { population: PopulationStats }) {
  const cap = population.max_members ?? "∞";
  const wood = population.resources.wood ?? 0;
  return (
    <div
      style={{
        padding: "0.35rem 0",
        borderBottom: `1px solid ${colors.border}`,
        fontSize: "0.7rem",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", gap: "0.5rem" }}>
        <strong style={{ color: colors.accent }}>{population.name}</strong>
        <span style={{ color: colors.dim }}>
          #{population.population_id} · {population.size}/{cap} members
          {population.top_up ? " · top-up" : ""}
        </span>
      </div>
      <div style={{ color: colors.dim, marginTop: "0.15rem" }}>
        gen {population.generation.min}–{population.generation.max} (avg{" "}
        {population.generation.average}) · births {population.births} · arrivals{" "}
        {population.arrivals} · wood {wood} · age {population.age_ticks}t
      </div>
      <div style={{ color: colors.dim, marginTop: "0.1rem", opacity: 0.7 }}>
        rule: {population.rule.members} founding, {population.rule.policies.join("/")}
        {population.rule.spawn_zone
          ? `, zone (${population.rule.spawn_zone.join(", ")})`
          : ""}
        {population.rule.stipend.wood ? `, +${population.rule.stipend.wood} wood each` : ""}
      </div>
    </div>
  );
}
