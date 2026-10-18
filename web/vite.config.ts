import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiPort = process.env.STRAT_API_PORT ?? "8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: Number(process.env.STRAT_WEB_PORT ?? 5173),
    strictPort: true,
    proxy: {
      "/api": `http://127.0.0.1:${apiPort}`,
      "/ws": { target: `http://127.0.0.1:${apiPort}`, ws: true },
    },
  },
});
