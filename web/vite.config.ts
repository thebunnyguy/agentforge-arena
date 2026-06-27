import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The SPA talks to ONE local FastAPI app. In dev we proxy /api to the API
// server so the app can be opened at the Vite port without CORS headaches.
// In production the built assets are served by the API/web container and the
// client resolves the base URL from VITE_API_BASE or window.location.origin.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.VITE_API_BASE || "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});
