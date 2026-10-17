// Experiments panel (S40): the research console's laboratory.
//
// List every study that has run, run a new one from the scenario catalog
// — no source edits, just a form — then inspect its cross-world
// comparison and export the whole study as JSON.

import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type {
  ExperimentDetail,
  ExperimentSummary,
  ScalarSummary,
  Scenario,
  ScenarioParam,
} from "./api";
import { buttonStyle, colors, headingStyle, inputStyle, panelStyle } from "./theme";

const labelStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: "0.2rem",
  fontSize: "0.7rem",
  color: colors.dim,
};

function defaultParams(scenario: Scenario): Record<string, unknown> {
  const values: Record<string, unknown> = {};
  for (const param of scenario.params) values[param.name] = param.default ?? "";
  return values;
}

function isScalarSummary(value: unknown): value is ScalarSummary {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as ScalarSummary).mean === "number" &&
    typeof (value as ScalarSummary).n === "number"
  );
}

export function ExperimentsPanel() {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [experiments, setExperiments] = useState<ExperimentSummary[]>([]);
  const [selected, setSelected] = useState<ExperimentDetail | null>(null);
  const [scenarioName, setScenarioName] = useState<string>("");
  const [name, setName] = useState("");
  const [params, setParams] = useState<Record<string, unknown>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const scenario = scenarios.find((item) => item.name === scenarioName) ?? null;

  const loadExperiments = useCallback(async () => {
    try {
      const body = await api.experiments();
      setExperiments(body.experiments);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    api
      .scenarios()
      .then((body) => {
        setScenarios(body.scenarios);
        if (body.scenarios.length > 0) {
          setScenarioName(body.scenarios[0].name);
          setParams(defaultParams(body.scenarios[0]));
        }
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
    void loadExperiments();
    const timer = window.setInterval(() => void loadExperiments(), 3000);
    return () => window.clearInterval(timer);
  }, [loadExperiments]);

  function chooseScenario(next: string) {
    setScenarioName(next);
    const found = scenarios.find((item) => item.name === next);
    setParams(found ? defaultParams(found) : {});
  }

  async function inspect(id: number) {
    try {
      setSelected(await api.experiment(id));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  function coerce(param: ScenarioParam, raw: unknown): unknown {
    if (param.type === "int") {
      if (raw === "" || raw === null || raw === undefined) return null;
      return Number(raw);
    }
    if (param.type === "bool") return Boolean(raw);
    return raw;
  }

  async function run() {
    if (!scenario) return;
    setBusy(true);
    try {
      const clean: Record<string, unknown> = {};
      for (const param of scenario.params) {
        const value = coerce(param, params[param.name]);
        if (value !== null && value !== "") clean[param.name] = value;
      }
      const result = await api.runExperiment({
        scenario: scenario.name,
        name: name || undefined,
        params: clean,
      });
      await loadExperiments();
      await inspect(result.study.experiment_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const comparison = selected?.result?.comparison;
  const measures =
    comparison && typeof comparison.measures === "object"
      ? (comparison.measures as Record<string, unknown>)
      : null;

  return (
    <div style={{ display: "grid", gridTemplateColumns: "minmax(280px, 360px) 1fr", gap: "0.75rem" }}>
      <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem", minWidth: 0 }}>
        <section style={panelStyle} aria-label="run experiment">
          <h2 style={headingStyle}>run experiment</h2>
          {scenario === null ? (
            <p style={{ margin: 0, color: colors.dim, fontSize: "0.7rem" }}>
              loading scenarios…
            </p>
          ) : (
            <>
              <label style={labelStyle}>
                scenario
                <select
                  style={inputStyle}
                  value={scenarioName}
                  onChange={(e) => chooseScenario(e.target.value)}
                >
                  {scenarios.map((item) => (
                    <option key={item.name} value={item.name}>
                      {item.title}
                    </option>
                  ))}
                </select>
              </label>
              <p style={{ margin: 0, color: colors.dim, fontSize: "0.68rem" }}>
                {scenario.description}
              </p>
              <label style={labelStyle}>
                name (optional)
                <input
                  style={inputStyle}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </label>
              {scenario.params.map((param) => (
                <label key={param.name} style={labelStyle}>
                  {param.label}
                  {param.type === "choice" && param.choices ? (
                    <select
                      style={inputStyle}
                      value={String(params[param.name] ?? "")}
                      onChange={(e) =>
                        setParams({ ...params, [param.name]: e.target.value })
                      }
                    >
                      {param.choices.map((choice) => (
                        <option key={choice} value={choice}>
                          {choice}
                        </option>
                      ))}
                    </select>
                  ) : param.type === "bool" ? (
                    <input
                      type="checkbox"
                      checked={Boolean(params[param.name])}
                      onChange={(e) =>
                        setParams({ ...params, [param.name]: e.target.checked })
                      }
                    />
                  ) : (
                    <input
                      style={inputStyle}
                      type={param.type === "int" ? "number" : "text"}
                      min={param.min}
                      max={param.max}
                      value={String(params[param.name] ?? "")}
                      onChange={(e) =>
                        setParams({ ...params, [param.name]: e.target.value })
                      }
                    />
                  )}
                  {param.help && (
                    <span style={{ color: colors.dim, fontSize: "0.62rem" }}>
                      {param.help}
                    </span>
                  )}
                </label>
              ))}
              <button style={buttonStyle} disabled={busy} onClick={() => void run()}>
                {busy ? "running…" : "run"}
              </button>
            </>
          )}
          {error && <p style={{ margin: 0, color: colors.error, fontSize: "0.7rem" }}>{error}</p>}
        </section>

        <section style={panelStyle} aria-label="experiments">
          <h2 style={headingStyle}>experiments ({experiments.length})</h2>
          <ul
            style={{
              listStyle: "none",
              margin: 0,
              padding: 0,
              display: "flex",
              flexDirection: "column",
              gap: "0.2rem",
              maxHeight: 360,
              overflowY: "auto",
            }}
          >
            {experiments.map((experiment) => (
              <li key={experiment.id}>
                <button
                  style={{
                    ...buttonStyle,
                    width: "100%",
                    textAlign: "left",
                    borderColor:
                      selected?.id === experiment.id ? colors.accent : colors.borderBright,
                    color: selected?.id === experiment.id ? colors.accent : colors.text,
                  }}
                  onClick={() => void inspect(experiment.id)}
                >
                  #{experiment.id} {experiment.name}
                  <span style={{ color: colors.dim }}> · {experiment.scenario}</span>
                  {experiment.has_result ? "" : " · no result"}
                </button>
              </li>
            ))}
            {experiments.length === 0 && (
              <li style={{ color: colors.dim, fontSize: "0.72rem" }}>
                no experiments yet — run one above
              </li>
            )}
          </ul>
        </section>
      </div>

      <section style={panelStyle} aria-label="experiment detail">
        {selected === null ? (
          <p style={{ margin: 0, color: colors.dim }}>
            run or select an experiment to inspect it.
          </p>
        ) : (
          <>
            <h2 style={headingStyle}>experiment #{selected.id}</h2>
            <p style={{ margin: 0, fontSize: "0.78rem" }}>
              <strong style={{ color: colors.accent }}>{selected.name}</strong>{" "}
              <span style={{ color: colors.dim }}>
                · {selected.scenario} · seed {selected.seed} · {selected.status}
              </span>
            </p>
            <div style={{ display: "flex", gap: "0.4rem" }}>
              <a
                style={{ ...buttonStyle, textDecoration: "none" }}
                href={api.exportExperimentUrl(selected.id)}
                download
              >
                export JSON
              </a>
            </div>

            {measures ? (
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.72rem" }}>
                <thead>
                  <tr style={{ color: colors.dim, textAlign: "left" }}>
                    <th style={cellStyle}>measure</th>
                    <th style={cellStyle}>mean</th>
                    <th style={cellStyle}>stdev</th>
                    <th style={cellStyle}>min</th>
                    <th style={cellStyle}>max</th>
                    <th style={cellStyle}>n</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(measures).map(([key, value]) => (
                    <tr key={key}>
                      <td style={cellStyle}>{key}</td>
                      {isScalarSummary(value) ? (
                        <>
                          <td style={cellStyle}>{value.mean}</td>
                          <td style={cellStyle}>{value.stdev}</td>
                          <td style={cellStyle}>{value.min}</td>
                          <td style={cellStyle}>{value.max}</td>
                          <td style={cellStyle}>{value.n}</td>
                        </>
                      ) : (
                        <td style={cellStyle} colSpan={5}>
                          {JSON.stringify(value)}
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p style={{ margin: 0, color: colors.dim, fontSize: "0.72rem" }}>
                no flat cross-world measures — see the comparison below.
              </p>
            )}

            <details>
              <summary style={{ cursor: "pointer", color: colors.dim, fontSize: "0.72rem" }}>
                comparison
              </summary>
              <pre style={preStyle}>{JSON.stringify(comparison, null, 2)}</pre>
            </details>
            <details>
              <summary style={{ cursor: "pointer", color: colors.dim, fontSize: "0.72rem" }}>
                runs ({selected.result?.runs?.length ?? 0})
              </summary>
              <pre style={preStyle}>{JSON.stringify(selected.result?.runs, null, 2)}</pre>
            </details>
          </>
        )}
      </section>
    </div>
  );
}

const cellStyle: React.CSSProperties = {
  borderBottom: `1px solid ${colors.border}`,
  padding: "0.2rem 0.4rem",
  color: colors.text,
};

const preStyle: React.CSSProperties = {
  margin: 0,
  maxHeight: 320,
  overflow: "auto",
  fontSize: "0.68rem",
  color: colors.text,
  backgroundColor: colors.panelAlt,
  border: `1px solid ${colors.border}`,
  borderRadius: 3,
  padding: "0.5rem",
};
