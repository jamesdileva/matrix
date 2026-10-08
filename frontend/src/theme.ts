// The console's Matrix-dark palette and shared panel styles (S01's
// theme, extended for the dashboard).

export const colors = {
  bg: "#060a06",
  panel: "#0b140b",
  panelAlt: "#081008",
  border: "#1c3a22",
  borderBright: "#2a5c36",
  text: "#9fd8a5",
  dim: "#4a7a55",
  accent: "#3dff7a",
  warn: "#ffb347",
  error: "#ff6b6b",
  decision: "#7fd4ff",
  message: "#d9a3ff",
  lineage: "#ffd166",
};

export const font = "'Cascadia Code', 'Fira Code', Consolas, monospace";

export const panelStyle: React.CSSProperties = {
  backgroundColor: colors.panel,
  border: `1px solid ${colors.border}`,
  borderRadius: 4,
  padding: "0.75rem 1rem",
  display: "flex",
  flexDirection: "column",
  gap: "0.5rem",
  minWidth: 0,
};

export const headingStyle: React.CSSProperties = {
  margin: 0,
  fontSize: "0.7rem",
  letterSpacing: "0.25em",
  textTransform: "uppercase",
  color: colors.dim,
};

export const buttonStyle: React.CSSProperties = {
  backgroundColor: colors.panelAlt,
  color: colors.accent,
  border: `1px solid ${colors.borderBright}`,
  borderRadius: 3,
  padding: "0.3rem 0.8rem",
  fontFamily: font,
  fontSize: "0.75rem",
  cursor: "pointer",
};

export const inputStyle: React.CSSProperties = {
  backgroundColor: colors.panelAlt,
  color: colors.text,
  border: `1px solid ${colors.border}`,
  borderRadius: 3,
  padding: "0.3rem 0.5rem",
  fontFamily: font,
  fontSize: "0.75rem",
  width: "100%",
  boxSizing: "border-box",
};
