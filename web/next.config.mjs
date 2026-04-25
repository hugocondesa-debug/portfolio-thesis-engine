/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",

  images: {
    remotePatterns: [
      { protocol: "http", hostname: "100.70.51.18" },
      { protocol: "http", hostname: "pte-api" },
    ],
  },

  env: {
    NEXT_PUBLIC_APP_NAME: "Portfolio Thesis Engine",
  },
};

export default nextConfig;
