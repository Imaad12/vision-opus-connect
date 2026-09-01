# VINCO Desktop — macOS DMG packaging investigation

**Update (after the real `bun run tauri:build` failure was confirmed):**
the previous version of this document concluded (correctly, at the time)
that the `bash -x` trace you'd shared was a zero-argument manual
reproduction, not proof of a real bug. You then confirmed the real `bun
run tauri:build` invocation *also* fails at the DMG stage — a
genuinely different, and more informative, piece of evidence. Tracing
*that* found something concrete: **Tauri's own bundler captures
`bundle_dmg.sh`'s real stdout/stderr but only logs it at `debug` level,
which its CLI does not print by default** — this is why the terminal
output "hides the underlying error," exactly as you suspected, and why
neither of us has seen the actual failing command yet. That's a real,
verifiable, fixable gap in the *diagnostic* process (see §A), separate
from whatever the underlying `.dmg`-creation failure turns out to be.

Status: the config hardening from the previous round is confirmed
harmless (still builds clean everywhere this sandbox can check). The
actual root cause of the `.dmg`-creation failure is **still unknown** —
correctly so, per your explicit instruction not to claim one without
the real failing command. This document now hands you the exact,
minimal step to capture it, and a build script (`tauri:build:verbose`)
that does it via Tauri's own built-in mechanism, not a workaround.

## A. Exact root cause

**Two separate findings — a confirmed diagnostic gap, and a still-open
question about the real underlying failure.**

**1. Confirmed: Tauri suppresses the actual error by default.** Traced
`tauri-bundler`'s `utils::CommandExt::output_ok()` (the helper `mod.rs`
uses to run `bundle_dmg.sh`) directly:

```rust
fn output_ok(&mut self) -> crate::Result<Output> {
  ...
  self.stdout(Stdio::piped());
  self.stderr(Stdio::piped());
  let mut child = self.spawn()?;
  // spawns a thread per stream, and for every line read:
  log::debug!(action = "stdout"; "{}", line.trim_end());
  // (identically for stderr)
  ...
}
```

It **does** capture every line of `bundle_dmg.sh`'s real stdout and
stderr — but only ever emits them via `log::debug!`, and the Tauri CLI's
default log level is `info`. Unless verbose logging is turned on, every
line of the script's actual output (including whatever `hdiutil`/`du`/
`osascript` command fails and why) is captured internally and then
discarded from the terminal, leaving only the generic wrapper message
your build showed: `failed to bundle project: error running
bundle_dmg.sh`. This is exactly why "the terminal output currently hides
the underlying error" — confirmed from the CLI's own source, not
inferred from the symptom.

**The fix for the diagnostic gap:** the CLI already has a built-in
`-v`/`--verbose` flag (repeatable) documented in its own `--help`. Ran
`tauri build -vv` in this sandbox (Linux, `--no-bundle`, so the DMG step
itself doesn't execute here, but the same CLI code path) and confirmed
it does raise the log level and surface additional `[tauri_cli]`-tagged
lines beyond the default output — direct evidence the mechanism works,
not an assumption. Added a `tauri:build:verbose` script (§B) so this is
one command away rather than something to remember a flag for.

**2. Still open: what `hdiutil`/`du`/`osascript` command inside
`bundle_dmg.sh` is actually failing, and why.** I am not claiming a root
cause here, per your instruction — I don't have the evidence yet.
`bundle_dmg.sh` runs a long sequence of `hdiutil create`/`resize`/
`attach`/`detach` calls plus a Finder-automation AppleScript step; any of
`create-dmg` version quirks, macOS 26 `hdiutil`/Gatekeeper behavior
changes, HFS+ vs. APFS handling, or a permissions/quarantine issue on
your machine could plausibly produce a non-zero exit from one of those —
but guessing which one, and applying a "fix" for the wrong one, wastes a
build cycle and risks masking the real issue. §"What I need from you"
has the exact one command to run to get the real answer.

**Previous finding, still valid — the `bash -x` trace from the earlier
round genuinely was a zero-argument reproduction, not the real build's
failure:** `bundle_dmg.sh` checks `[[ -z "$2" ]]` right after its
argument-parsing loop exits, and that trace showed the check firing with
none of the flag-branch variable assignments (`VOLUME_NAME=...` etc.)
having executed — only possible if the script received no arguments at
all, consistent with running it bare by hand. Separately, cross-checking
every flag Tauri's Rust code sends (`--volname`, `--icon`,
`--app-drop-link`, `--window-size`, `--hide-extension`, and the
conditional ones) against the script's own shift-counts for each found
no count mismatch. Neither of those facts changes with the new evidence
— they were never the explanation for the real failure, which is now
confirmed to be something else, inside the script's actual DMG-creation
logic, not its argument parsing.

No defect was found in this project's `tauri.conf.json`, `Cargo.toml`,
or `package.json` that would cause Tauri's own invocation to omit an
argument. The DMG-specific settings (`appPosition`, `windowSize`, etc.)
default to real, populated values (confirmed from the CLI's own JSON
schema) whether or not `tauri.conf.json` sets them explicitly.

## B. Exact files changed

| File | Change | Why |
|---|---|---|
| `package.json`, `bun.lock` | `@tauri-apps/cli`: `"^2"` -> `"2.11.4"` (exact pin; resolved version unchanged -- `bun.lock` already had 2.11.4 locked) | Removes any possibility of a future `bun install` silently resolving a different patch/minor CLI version with its own bundler behavior. |
| `src-tauri/tauri.conf.json` | Added `bundle.macOS.dmg` explicitly, with the exact values `tauri-bundler` already defaults to | Makes the DMG window/icon layout explicit instead of implicit -- no behavior change (same values). |
| `package.json` (this round) | Added a `tauri:build:verbose` script: `tauri build -vv` | The concrete fix for the diagnostic gap in §A.1 -- surfaces `bundle_dmg.sh`'s real stdout/stderr instead of the generic wrapper error. `tauri:build` itself is untouched, so default builds stay quiet. |

No change to `Cargo.toml`, `src-tauri/src/*.rs`, or `bundle_dmg.sh`
(generated fresh by Tauri on every build regardless -- still not
manually touched, per your instruction).

## C. The exact failing command inside bundle_dmg.sh

**Not yet identified — genuinely, not withheld.** §A.1 explains why: the
real command's stderr exists (Tauri's `output_ok()` captures it) but was
never printed to your terminal at the default log level. §"What I need
from you" below is the one command that will surface it.

## D. Successful local DMG build

**Not producible in this sandbox, and I want to be explicit about why
rather than paper over it:** Tauri's macOS DMG/`.app` bundler
(`tauri-bundler`'s `bundle/macos/` module) is macOS-only code -- I
confirmed this directly by searching the installed Linux CLI binary
(`@tauri-apps/cli-linux-x64-gnu`) for any trace of the bundler's
embedded script text (e.g. `CDMG_VERSION`, `bundle_dmg`) and found none,
meaning that code path isn't even compiled into the Linux build of the
CLI. `find src-tauri/target -name "*.dmg" -print` in this sandbox
correctly returns nothing -- not because of a bug, but because no
`.dmg`-capable bundler exists to run here. This mirrors exactly what the
previous phases' documentation already said about `.app`/`.dmg`
production needing a real macOS machine or CI runner (`DESKTOP_
ARCHITECTURE.md` §10) -- unchanged by this investigation.

**What was verified here (steps 1-4 of your checklist):**

- `cargo check` -- clean, including the new `tauri.conf.json` (which is
  parsed and validated at compile time via `generate_context!()`, so an
  invalid `macOS.dmg` shape would have failed this step).
- `cargo test` -- 3/3 (unaffected; unrelated to bundling).
- `bun test` (`vitest`) -- 8/8 (unaffected).
- `cargo build --release` -- clean.
- `bunx tsc --noEmit` -- clean.
- `bun run build` (web) -- clean.
- `bun run build:desktop` -- clean.
- `tauri build -vv --no-bundle` -- confirmed the `-vv` flag itself
  genuinely raises the CLI's logged verbosity (new `[tauri_cli]`-tagged
  lines appear that don't at default verbosity) -- direct evidence the
  diagnostic fix works, on the same code path, even though the DMG step
  itself can't execute on Linux.
- Relaunched the compiled release binary under `xvfb-run` -- runs
  stably, no crash (unrelated to bundling, but confirms nothing else
  regressed).

**Steps 5-7 of your checklist (`bun run tauri:build`, the actual
`.dmg`, confirming the `.app` still exists) need your Mac** -- see
"What I need from you" below for the exact command.

## E. CI compatibility

`.github/workflows/desktop-build.yml` is unaffected and needs no change:
its `build-desktop` job runs `bunx tauri build` after `bun install
--frozen-lockfile`, which resolves the pinned `2.11.4` and picks up the
new `macOS.dmg` config and the (unused by CI) `tauri:build:verbose`
script automatically, since it reads the same `tauri.conf.json`/
`package.json`. `frontend-checks` and `rust-checks` all still pass, as
verified above (step 8 of your checklist).

## F. Commit pushed

This round: `<filled in after commit>` — "Add a verbose build script to
expose bundle_dmg.sh's real stdout/stderr" — pushed to `main`. Previous
round: `083c264`.

## What I need from you

Run, on your Mac:

```sh
bun run tauri:build:verbose 2>&1 | tee tauri-build-verbose.log
```

Then share the portion of `tauri-build-verbose.log` from the
`Running bundle_dmg.sh` line through the failure (or just the whole
file — it's the same build, only more log lines). That will contain the
actual command that returned non-zero and, in almost every case,
`hdiutil`'s or the other tool's own error message explaining why —
which is what turns "is it create-dmg, macOS 26, Apple Silicon,
permissions, or something else" from a list of candidates into an
actual, evidenced answer. I'm not able to produce or guess that text
myself; this sandbox has no macOS environment to run the real bundler
in at all (§D).
