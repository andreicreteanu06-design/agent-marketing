import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Build-ul pentru Docker (Dockerfile.frontend): .next/standalone are doar server.js
  // si fisierele urmarite de build - imaginea nu mai cara node_modules-ul intreg.
  output: "standalone",
};

export default nextConfig;
