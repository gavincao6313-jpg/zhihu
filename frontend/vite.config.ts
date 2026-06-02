import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// VITE_API_URL: override to point at a remote API server.
// WIN (execution): leave unset → defaults to local 127.0.0.1:8765
// MAC (viewer):    VITE_API_URL=http://<WIN_LAN_IP>:8765 npm run dev
const apiTarget = process.env.VITE_API_URL ?? "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [react()],
  server: {
    host: process.env.VITE_HOST ?? "127.0.0.1",
    port: Number(process.env.VITE_PORT ?? 5173),
    proxy: {
      "/api": {
        target: apiTarget,
        changeOrigin: true,
      }
    }
  }
});
