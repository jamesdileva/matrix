import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The console is a client of the Simulation API. The dev server proxies
// /api to the backend; `vite preview` does NOT inherit server.proxy,
// so the built app gets the same proxy declared explicitly (S13 —
// watching the dashboard in a browser must work for both).
const proxy = {
  "/api": {
    target: "http://127.0.0.1:8000",
    changeOrigin: true,
  },
};

export default defineConfig({
  plugins: [react()],
  server: {
    proxy,
  },
  preview: {
    proxy,
  },
});
