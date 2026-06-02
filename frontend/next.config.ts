import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  images: {
    // Shop product images are hot-linked from the source shop.
    // Add a pattern per shop host as new scrapers come online.
    remotePatterns: [
      { protocol: "https", hostname: "pcandparts.com", pathname: "/wp-content/**" },
    ],
  },
};

export default nextConfig;
