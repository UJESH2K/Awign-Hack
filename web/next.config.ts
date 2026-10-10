import type { NextConfig } from "next";

const ENGINE = process.env.ENGINE_URL ?? "http://127.0.0.1:8765";

const nextConfig: NextConfig = {
  // The Python engine owns the loop and the Reactor key; the browser only talks to it via /engine.
  async rewrites() {
    return [{ source: "/engine/:path*", destination: `${ENGINE}/:path*` }];
  },
};

export default nextConfig;
