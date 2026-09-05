# VINCO ERP Desktop -- Internal Install Guide

Internal company software. These builds are unsigned (no Apple Developer
ID, no Windows Authenticode certificate -- see `DESKTOP_ARCHITECTURE.md`'s
"Signing" sections for why, and what obtaining one would take). Your
operating system will warn about that on first launch. The instructions
below are how to get past that warning safely for internal use -- they
are not a workaround for anything malicious, just what "unsigned" means
in practice.

Never enter your VINCO password anywhere except the VINCO ERP app's own
login screen.

## 1. Which file to use

| Machine | File |
|---|---|
| Mac, Apple Silicon (M1/M2/M3/M4) | `VINCO ERP_<version>_aarch64.dmg` |
| Mac, Intel | `VINCO ERP_<version>_x64.dmg` |
| Windows 10/11, 64-bit | `VINCO ERP_<version>_x64-setup.exe` |

Not sure which Mac you have: Apple menu -> **About This Mac** -> look at
the chip name. "Apple M1/M2/M3/M4" = Apple Silicon. "Intel" = Intel.

## 2. Installing

**Mac:**
1. Open the `.dmg` file.
2. Drag **VINCO ERP** into the **Applications** folder shown in the window.
3. Open **Applications** and double-click **VINCO ERP**.

**Windows:**
1. Run the `.exe` installer.
2. Follow the setup wizard (Next -> Install -> Finish).
3. Launch **VINCO ERP** from the Start Menu.

## 3. First-launch security warning (unsigned software)

This is expected for internal, unsigned builds -- it does not mean the
app is unsafe, only that it wasn't submitted to Apple/Microsoft for
their (paid) signing programs.

**Mac ("VINCO ERP" can't be opened / is from an unidentified developer):**
1. Try to open the app once (it will be blocked) -- **OK**.
2. Open **System Settings -> Privacy & Security**.
3. Scroll down to the security message about VINCO ERP and click
   **Open Anyway**.
4. Confirm **Open** on the next prompt.
5. You only need to do this once per machine.

**Windows (SmartScreen: "Windows protected your PC"):**
1. On the blue SmartScreen prompt, click **More info**.
2. Click **Run anyway**.
3. You only need to do this once per machine, per version.

If your IT/security team has a stricter policy that blocks this outright,
ask them to approve `VINCO ERP` specifically rather than disabling
protection generally.

## 4. Logging in

Use your normal VINCO username and password -- the same ones you use on
the web version. There is no separate desktop account. If you don't have
a VINCO account yet, ask your administrator to create one (Users & Access
in the web app).

## 5. Updating to a newer version

There is no auto-update in this build. To update:
1. Quit VINCO ERP if it's running.
2. Download the newer installer from wherever your team distributes it
   (see §6).
3. **Mac:** open the new `.dmg` and drag it into Applications again --
   this replaces the old version.
   **Windows:** run the new `.exe` installer -- it replaces the old
   version automatically.
4. Your data is not stored in the app itself (it lives in VINCO's
   database), so updating never loses anything.

## 6. Where to get the latest approved installer

Ask your VINCO administrator for the current internal distribution
location (e.g. a shared drive, an internal file share, or the latest
successful "Desktop build" GitHub Actions run's artifacts). Do not use
a build you were not given directly by your administrator or IT team.
