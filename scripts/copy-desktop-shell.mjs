// TanStack Start's SPA-mode prerender writes the static shell to
// dist/client/_shell.html (see vite.config.ts's isDesktopBuild branch,
// and DESKTOP_ARCHITECTURE.md for why that file -- not a server -- is
// what Tauri loads). Tauri, and any plain static-file server, expects an
// index.html at the site root, so this copies it into place after
// `vite build`. Cross-platform (no shell `cp`), since this runs as part
// of Tauri's beforeBuildCommand on Windows/macOS/Linux alike.
import { copyFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const shell = join(root, "dist", "client", "_shell.html");
const index = join(root, "dist", "client", "index.html");

if (!existsSync(shell)) {
  console.error(`[copy-desktop-shell] ${shell} not found -- did the desktop build run first?`);
  process.exit(1);
}

copyFileSync(shell, index);
console.log(`[copy-desktop-shell] ${shell} -> ${index}`);
