import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      manifest: {
        name: "Spark: engineer learning feed",
        short_name: "Spark",
        description: "A quick feed for engineers to learn what matters.",
        id: "/",
        theme_color: "#3b3bff",
        background_color: "#111321",
        display: "standalone",
        start_url: "/",
        icons: [
          {
            src: "/icon-192.png",
            sizes: "192x192",
            type: "image/png",
            purpose: "any maskable",
          },
          {
            src: "/icon-512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "any maskable",
          },
        ],
      },
      workbox: {
        globPatterns: ["**/*.{js,css,html,svg,png,woff,woff2}"],
        globIgnores: ["feed.json"],
        runtimeCaching: [
          {
            urlPattern: /\/feed\.json$/,
            handler: "NetworkFirst",
            options: {
              cacheName: "spark-feed",
              cacheableResponse: { statuses: [200] },
              expiration: { maxEntries: 2, maxAgeSeconds: 60 * 60 * 24 * 14 },
            },
          },
        ],
      },
    }),
  ],
});
