# VINCO Desktop — macOS DMG packaging investigation

Status: config hardened and verified everywhere this sandbox can verify
it (source-level trace-matching, `cargo check`/`test`, both frontend
build targets). The literal `.dmg` file itself could not be produced or
tested here — Tauri's macOS DMG bundler is macOS-only code, not present
in the Linux build of the Tauri CLI at all (confirmed, not assumed — see
§A). One thing is needed back from you to close this out for certain:
see "What I still need from you" at the end.

## A. Exact root cause

**Traced against the actual `tauri-bundler` source** (the crate behind
`@tauri-apps/cli`'s DMG bundling — fetched and read directly, not
recalled from memory), not the leftover script's `--help` text:

`mod.rs`'s `bundle_project()` builds the `bundle_dmg.sh` invocation as a
single `Command`, appending arguments in stages — `--volname`, `--icon`,
`--app-drop-link`, `--window-size`, `--hide-extension`, then
conditionally `--window-pos`/`--background`/`--volicon`/`--eula`/
`--skip-jenkins`, and *always*, last, the two required positional
arguments (`<dmg_name> <bundle_file_name>`). Cross-checking every one of
those flags against `bundle_dmg`'s own argument-parsing loop (`--icon`
consumes 4 tokens, matching the 4 Rust supplies; `--window-size` consumes
3, matching 3; `--hide-extension` consumes 2, matching 2; and so on for
every flag) — **the counts match exactly.** There is no argument-count
mismatch between what Tauri's Rust code sends and what the embedded
script expects.

**The script's own logic pinpoints exactly where "Not enough arguments"
comes from:** immediately after its argument-parsing loop exits, it does
```sh
if [[ -z "$2" ]]; then
	echo "Not enough arguments. Run 'create-dmg --help' for help."
	exit 1
fi
```
— i.e. it's checking whether the *second positional argument* (the
source folder) is empty. Your own `bash -x` trace shows the script
reaching this check with **none** of the flag-branch variable
assignments (`VOLUME_NAME=...`, etc.) having executed first — meaning
every flag from `--volname` onward was skipped entirely, which only
happens when `$1` never starts with `-` to begin with. That is
conclusive: **the invocation your trace captured received zero
arguments**, consistent exactly with what you described running --
`bash -x .../bundle_dmg.sh` with nothing after it. It is not consistent
with Tauri's real invocation, which always supplies 15+ arguments.

**In plain terms:** re-running the leftover script by hand with no
arguments will print this exact "Not enough arguments" message every
time, regardless of whether the real `bun run tauri:build` invocation
(which *does* supply all the required arguments) succeeded, failed, or
failed for a completely different reason. That manual test doesn't
reproduce the real build's failure -- it demonstrates that the script
requires arguments, which was never in question. I want to be direct
about this rather than pretend the trace proves something it doesn't: it
does not, by itself, tell us what actually went wrong in the real build.

No defect was found in this project's `tauri.conf.json`, `Cargo.toml`,
or `package.json` that would cause Tauri's own invocation to omit an
argument. The DMG-specific settings (`appPosition`, `windowSize`, etc.)
were previously left unset, relying on `tauri-bundler`'s built-in
defaults (`{x:180,y:170}` / `{width:660,height:400}`, confirmed from the
CLI's own JSON schema) -- those defaults are real, populated values, not
something that resolves to empty and drops an argument.

## B. Exact files changed

| File | Change | Why |
|---|---|---|
| `package.json`, `bun.lock` | `@tauri-apps/cli`: `"^2"` -> `"2.11.4"` (exact pin; resolved version unchanged -- `bun.lock` already had 2.11.4 locked) | Removes any possibility of a future `bun install` silently resolving a different patch/minor CLI version with its own bundler behavior. Doesn't explain today's failure (the lockfile already pinned 2.11.4), but is a real, defensible hardening you asked for ("compare against the correct config for the installed CLI version") -- now that version can't drift. |
| `src-tauri/tauri.conf.json` | Added `bundle.macOS.dmg` explicitly, with the exact values `tauri-bundler` already defaults to | Makes the DMG window/icon layout explicit instead of implicit -- no behavior change (same values), but removes any reliance on unstated defaults and gives a single place to tune it later. |

No change to `Cargo.toml`, `src-tauri/src/*.rs`, or anything outside
these two files. `bundle_dmg.sh` itself was not touched, per your
instruction (it's generated fresh by Tauri on every build regardless).

## C. Why the generated script was "missing arguments"

Per §A: as far as this investigation can determine, it wasn't -- not in
the real build. The only concretely observed "missing arguments" event
was the manual, zero-argument reproduction. I could not find a defect in
this project's config that would cause the real, argument-supplying
invocation to fail the same way, and the trace you shared doesn't show
that invocation failing -- it shows the leftover script being run by hand
without its arguments.

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

**What was verified here (steps 1-5 of your checklist):**

- `cargo check` -- clean, including the new `tauri.conf.json` (which is
  parsed and validated at compile time via `generate_context!()`, so an
  invalid `macOS.dmg` shape would have failed this step).
- `cargo test` -- 3/3 (unaffected; unrelated to bundling).
- `cargo build --release` -- clean.
- `bunx tsc --noEmit` -- clean.
- `bun run build` (web) -- clean.
- `bun run build:desktop` -- clean.
- Relaunched the compiled release binary under `xvfb-run` -- runs
  stably, no crash (unrelated to bundling, but confirms nothing else
  regressed).

**Steps 6-7 (`.app`/`.dmg` generation) require your Mac or the CI
workflow's macOS runners** -- see "What I still need from you" below for
exactly what to run and share.

## E. CI compatibility

`.github/workflows/desktop-build.yml` is unaffected and needs no change:
its `build-desktop` job already runs `bunx tauri build` after `bun
install --frozen-lockfile`, which will now resolve the pinned
`2.11.4` from the lockfile exactly as before (the pin didn't change the
resolved version, only removed the floating range) and pick up the new
explicit `macOS.dmg` config automatically, since it reads the same
`tauri.conf.json`. `frontend-checks` and `rust-checks` (typecheck, unit
tests, web/desktop builds, `cargo check`/`test`) all still pass, as
verified above.

## F. Commit pushed

`083c264` — "Investigate macOS DMG packaging failure; harden bundler
config" — pushed to `main`.

## What I still need from you

If the real `bun run tauri:build` still fails at the DMG stage after
this fix, the one thing that would let me actually locate a real bug (if
one exists) is the **raw output of that real command**, specifically
whatever appears between the `Bundling: VINCO ERP.app` line and the
final failure -- not a re-run of the leftover script by hand. If Tauri's
own error output includes something like `error running bundle_dmg.sh:
Caused by: ...`, that "Caused by" text is the actual signal; please
paste it verbatim. Without it, I have no further config-level defect to
point to -- everything I can check statically checks out.
