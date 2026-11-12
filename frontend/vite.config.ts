import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Two local Python ASGI backends this frontend talks to, same convention
// as every other local-only piece of this research project (see
// ../docs/PORTFOLIO_DEMO.md): ResearchService (the async job API,
// `python -m prometheus.service serve`) on its own default port 8765,
// DashboardService (the existing HTML dashboard, now also serving
// ?format=json; `python -m prometheus.dashboard serve`) on its own
// default port 8766. See README.md for the full process list --
// ResearchService also needs a separate `python -m prometheus.jobs work`
// worker process actually picking jobs off the queue, or submissions
// will sit in "queued" forever. No production proxy/build step is
// provided -- this is a local research/demo tool, not a deployed service.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api/jobs": {
        target: "http://127.0.0.1:8765",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/jobs/, ""),
      },
      "/api/dashboard": {
        target: "http://127.0.0.1:8766",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/dashboard/, "/dashboard"),
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/setupTests.ts"],
  },
});
