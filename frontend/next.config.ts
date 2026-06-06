import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  images: {
    // Shop product images are hot-linked from the source shop.
    // Add a pattern per shop host as new scrapers come online.
    remotePatterns: [
      { protocol: "https", hostname: "pcandparts.com", pathname: "/wp-content/**" },
      { protocol: "https", hostname: "cdn.shopify.com", pathname: "/s/files/**" },
      { protocol: "https", hostname: "cdn11.bigcommerce.com" },
    ],
  },
};

export default nextConfig;
