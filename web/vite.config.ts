import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const backendOrigin = process.env.HAL_WEB_BACKEND_ORIGIN ?? "http://localhost:8765";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": new URL("./src", import.meta.url).pathname,
    },
  },
  server: {
    port: 3000,
    strictPort: true,
    proxy: {
      "/threads": {
        target: backendOrigin,
        changeOrigin: true,
      },
      "/sessions": {
        target: backendOrigin,
        changeOrigin: true,
        ws: true,
      },
    },
  },
});
