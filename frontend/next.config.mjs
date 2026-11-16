/** @type {import('next').NextConfig} */
const dev = process.env.NODE_ENV !== "production";
// Everything is served from this origin: scripts, fonts (bundled) and the API (through /api below). Next.js puts its
// hydration data in inline <script> tags, and per-request nonces would make every page dynamic, so inline scripts are
// allowed; the policy still blocks scripts, connections, frames and form posts to any other origin. React style
// props need inline styles. Development adds eval and the hot-reload websocket.
const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${dev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  `connect-src 'self'${dev ? " ws: wss:" : ""}`,
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");
const securityHeaders = [
  { key: "Content-Security-Policy", value: csp },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];
// The browser calls the API through this site's own domain (/api/...), which Next.js / Vercel forward to the
// analysis service. Requests to a separate hosting domain (onrender.com) are blocked by some ad blockers;
// same-site requests are not, and no CORS round-trip is needed.
const API_ORIGIN = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // `next start` / `next dev` cut proxied /api requests at 30 s by default (a plain 500), before the client's own
  // 45-60 s timeouts in lib/api.ts can report a slow or waking service
  experimental: { proxyTimeout: 90000 },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_ORIGIN}/:path*` }];
  },
};
export default nextConfig;
