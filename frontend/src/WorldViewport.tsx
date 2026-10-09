// The world viewport: the state snapshot rendered as a grid (S13).
//
// The 3D experience is the Godot client (D001) — this canvas is the
// web-side eye, drawn straight from the engine's render-ready
// snapshot. Terrain characters map to colors; objects and entities
// draw on top.

import { useEffect, useRef } from "react";
import type { WorldState } from "./api";
import { colors } from "./theme";

const TERRAIN_COLORS: Record<string, string> = {
  ".": "#0e1a0e",
  "#": "#22402a",
  "~": "#12303f",
  " ": "#050805",
};

const OBJECT_COLORS: Record<string, string> = {
  tree: "#2f8f4e",
  stone: "#8a8f96",
  food: "#e0b13c",
};

const CELL = 10; // draw and pick share this

type Props = {
  state: WorldState | null;
  selectedAgentId: number | null;
  onSelectAgent: (agentId: number | null) => void;
};

export function WorldViewport({ state, selectedAgentId, onSelectAgent }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !state) return;
    const context = canvas.getContext("2d");
    if (!context) return;

    const cell = CELL;
    const width = state.width;
    const height = state.height;
    canvas.width = width * cell;
    canvas.height = height * cell;

    context.fillStyle = colors.bg;
    context.fillRect(0, 0, canvas.width, canvas.height);

    for (let y = 0; y < height; y += 1) {
      const row = state.terrain[y] ?? "";
      for (let x = 0; x < width; x += 1) {
        context.fillStyle = TERRAIN_COLORS[row[x]] ?? "#111";
        context.fillRect(x * cell, y * cell, cell - 1, cell - 1);
      }
    }

    for (const object of state.objects) {
      context.fillStyle = OBJECT_COLORS[object.type] ?? colors.text;
      context.fillRect(object.position.x * cell + 2, object.position.y * cell + 2, cell - 5, cell - 5);
    }

    const entityAt = new Map(
      Object.entries(state.entities).map(([id, position]) => [`${position.x},${position.y}`, id]),
    );
    for (const [cellKey, id] of entityAt) {
      const [x, y] = cellKey.split(",").map(Number);
      const isSelected = Number(id) === selectedAgentId;
      context.fillStyle = isSelected ? colors.warn : colors.accent;
      context.beginPath();
      context.arc(x * cell + cell / 2, y * cell + cell / 2, cell / 2 - 1, 0, Math.PI * 2);
      context.fill();
    }
  }, [state, selectedAgentId]);

  // Screen-space picking, the web-side twin of the Godot client's:
  // click a cell; if an entity stands there, the inspector opens.
  function handleClick(event: React.MouseEvent<HTMLCanvasElement>) {
    if (!state) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const scaleX = event.currentTarget.width / rect.width;
    const scaleY = event.currentTarget.height / rect.height;
    const x = Math.floor(((event.clientX - rect.left) * scaleX) / CELL);
    const y = Math.floor(((event.clientY - rect.top) * scaleY) / CELL);
    const found = Object.entries(state.entities).find(
      ([, position]) => position.x === x && position.y === y,
    );
    onSelectAgent(found ? Number(found[0]) : null);
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
      <canvas
        ref={canvasRef}
        data-testid="world-viewport"
        onClick={handleClick}
        style={{ border: `1px solid ${colors.border}`, borderRadius: 3, maxWidth: "100%", imageRendering: "pixelated", cursor: "crosshair" }}
      />
      <p style={{ margin: 0, fontSize: "0.7rem", color: colors.dim }}>
        click an agent to inspect it · 3D view: launch <code>tools/godot.cmd --path world-client</code> (backend on
        :8000) — world truth stays server-side; this canvas is the web-side eye.
      </p>
    </div>
  );
}
