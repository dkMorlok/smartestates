import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Sreality serves listing photos from img.sreality.cz; allow them once the
  // detail page renders images (Week-4 follow-up).
  images: {
    remotePatterns: [{ protocol: "https", hostname: "*.sreality.cz" }],
  },
};

export default nextConfig;
