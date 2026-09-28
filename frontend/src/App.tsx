import { useEffect, useState } from "react";

type Health = {
  status: string;
  service: string;
  version: string;
};

const pageStyle: React.CSSProperties = {
  minHeight: "100vh",
  margin: 0,
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  justifyContent: "center",
  gap: "0.75rem",
  backgroundColor: "#060a06",
  color: "#9fd8a5",
  fontFamily: "'Cascadia Code', 'Fira Code', Consolas, monospace",
};

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/health")
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(setHealth)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  return (
    <main style={pageStyle}>
      <h1 style={{ color: "#3dff7a", letterSpacing: "0.5em", margin: 0 }}>
        FLOOD
      </h1>
      <p style={{ margin: 0, opacity: 0.7 }}>research console</p>
      {health && (
        <p style={{ margin: 0 }}>
          backend: <span style={{ color: "#3dff7a" }}>{health.status}</span> (
          {health.service} v{health.version})
        </p>
      )}
      {error && (
        <p style={{ margin: 0, color: "#ff6b6b" }}>backend unreachable: {error}</p>
      )}
    </main>
  );
}
