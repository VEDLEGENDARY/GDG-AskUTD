import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  reactStrictMode: true,
  experimental: {
    // Local Ollama can take longer than the default proxy timeout to answer.
    proxyTimeout: 90_000,
  },
  async rewrites() {
    const backend = (process.env.API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '');
    return [{ source: '/api/:path*', destination: `${backend}/api/:path*` }];
  },
};
export default nextConfig;
