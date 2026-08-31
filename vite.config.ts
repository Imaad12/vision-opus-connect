// @lovable.dev/vite-tanstack-config already includes the following — do NOT add them manually
// or the app will break with duplicate plugins:
//   - TanStack devtools (dev-only, first), tanstackStart, viteReact, tailwindcss, tsConfigPaths,
//     nitro (build-only using cloudflare as a default target), VITE_* env injection, @ path alias,
//     React/TanStack dedupe, error logger plugins, and sandbox detection (port/host/strictPort).
// You can pass additional config via defineConfig({ vite: { ... }, etc... }) if needed.
import { defineConfig } from "@lovable.dev/vite-tanstack-config";

// VINCO_TARGET=desktop builds a plain static/CSR bundle for the Tauri
// shell instead of a Cloudflare Worker (see src-tauri/README.md). Every
// route in this app already sets `ssr: false` (index.tsx, auth.tsx, and
// the whole `_authenticated` subtree), so disabling nitro here changes
// nothing about what's rendered -- only how the built assets are served
// (plain static files Tauri loads into its webview, vs. a Worker `fetch`
// handler for Cloudflare). The web/Cloudflare build is untouched: this
// only takes effect when VINCO_TARGET=desktop is set, which the web
// build/deploy pipeline never sets.
const isDesktopBuild = process.env["VINCO_TARGET"] === "desktop";

export default defineConfig({
  tanstackStart: {
    // Redirect TanStack Start's bundled server entry to src/server.ts (our SSR error wrapper).
    // nitro/vite builds from this
    server: { entry: "server" },
    // Desktop only: emit a standalone static index.html (TanStack Start's
    // "SPA shell" mode) instead of relying on a server to generate the
    // HTML document per request. Every route already has `ssr: false`,
    // so this changes nothing about what's rendered -- Tauri just needs
    // a real index.html file to load, which the default full-stack mode
    // doesn't produce even with nitro disabled (verified: without this,
    // `dist/client/` has JS/CSS assets but no index.html at all).
    ...(isDesktopBuild ? { spa: { enabled: true } } : {}),
  },
  ...(isDesktopBuild ? { nitro: false } : {}),
});
