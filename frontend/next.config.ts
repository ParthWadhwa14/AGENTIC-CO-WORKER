import type { NextConfig } from "next";

const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  devIndicators: false,
  async rewrites() {
    return [
      {
        source: "/health",
        destination: `${backendUrl}/health`
      },
      {
        source: "/setup/:path*",
        destination: `${backendUrl}/setup/:path*`
      },
      {
        source: "/auth/google/:path*",
        destination: `${backendUrl}/auth/google/:path*`
      },
      {
        source: "/documents/:path*",
        destination: `${backendUrl}/documents/:path*`
      },
      {
        source: "/agent/:path*",
        destination: `${backendUrl}/agent/:path*`
      },
      {
        source: "/drive/:path*",
        destination: `${backendUrl}/drive/:path*`
      },
      {
        source: "/gmail/:path*",
        destination: `${backendUrl}/gmail/:path*`
      },
      {
        source: "/sync/:path*",
        destination: `${backendUrl}/sync/:path*`
      },
      {
        source: "/sources/:path*",
        destination: `${backendUrl}/sources/:path*`
      },
      {
        source: "/scopes/:path*",
        destination: `${backendUrl}/scopes/:path*`
      },
      {
        source: "/upload",
        destination: `${backendUrl}/upload`
      },
      {
        source: "/references/:path*",
        destination: `${backendUrl}/references/:path*`
      }
    ];
  }
};

export default nextConfig;
