import { defineConfig } from "vite";

export default defineConfig({
  server: {
    port: 5178,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://localhost:8191",
        changeOrigin: true,
      },
    },
  },
});
