import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

// Deliberately standalone, not the app's own vite.config.ts -- that file
// is wrapped by @lovable.dev/vite-tanstack-config (TanStack Start, Nitro,
// sandbox plugins), none of which the unit tests below need or want
// running. Just enough config to resolve the same "@/*" -> "src/*" alias
// tsconfig.json defines, so test files can import app modules the same
// way the app itself does.
export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    environment: "node",
  },
});
