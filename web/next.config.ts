import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  cacheComponents: true,
  // A self-contained server for the container image.
  output: "standalone",
  // The API is reached by the server only. Nothing about it is exposed to the browser.
  poweredByHeader: false,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
