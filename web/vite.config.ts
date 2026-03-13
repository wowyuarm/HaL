import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": new URL("./src", import.meta.url).pathname,
    },
  },
  server: {
    port: 3000,
    proxy: {
      "/threads": {
        target: "http://localhost:8765",
        changeOrigin: true,
      },
      "/sessions": {
        target: "http://localhost:8765",
        changeOrigin: true,
        ws: true,
      },
    },
  },
});
