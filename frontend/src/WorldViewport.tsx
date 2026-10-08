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

type Props = {
  state: WorldState | null;
};

export function WorldViewport({ state }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !state) return;
    const context = canvas.getContext("2d");
    if (!context) return;

    const cell = 10;
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

    context.fillStyle = colors.accent;
    for (const entity of Object.values(state.entities)) {
      context.beginPath();
      context.arc(entity.x * cell + cell / 2, entity.y * cell + cell / 2, cell / 2 - 1, 0, Math.PI * 2);
      context.fill();
    }
  }, [state]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
      <canvas
        ref={canvasRef}
        data-testid="world-viewport"
        style={{ border: `1px solid ${colors.border}`, borderRadius: 3, maxWidth: "100%", imageRendering: "pixelated" }}
      />
      <p style={{ margin: 0, fontSize: "0.7rem", color: colors.dim }}>
        3D view: launch <code>tools/godot.cmd --path world-client</code> (backend on :8000) —
        world truth stays server-side; this canvas is the web-side eye.
      </p>
    </div>
  );
}
