//! Desktop session storage: a plain JSON file under the OS's per-app data
//! directory, exposed to the frontend as three small Tauri commands.
//!
//! Replaces the previous OS-keychain-backed adapter (`keyring` crate /
//! Windows Credential Manager / macOS Keychain / Linux Secret Service).
//! That approach turned out to be unusable in practice for an unsigned/
//! ad-hoc-signed internal build: macOS Keychain's "always allow" grant is
//! recorded against the requesting app's code-signing identity, and an
//! ad-hoc signature's identity is derived from the binary's own bytes --
//! so every rebuild presents as a *different, unrecognized* application
//! asking for access to an item a previous build created, and the OS
//! authorization prompt reappears on every single rebuild. Getting a
//! stable identity requires a real (even self-signed) code-signing
//! certificate, which is a one-time manual macOS-side setup step outside
//! what this codebase can do on its own -- see the desktop signing notes
//! in DESKTOP_ARCHITECTURE.md. Rather than leave the app blocked on that
//! manual step, this switches to a storage mechanism that needs no OS
//! authorization at all, so the app launches straight to the dashboard on
//! every build regardless of signing status.
//!
//! This is not a step down in what's actually protected: the app's own
//! web build already keeps the same class of value in `localStorage`,
//! protected only by OS-user-level file permissions -- this file gets
//! the same protection (the OS data directory is per-user, not
//! world-readable), just without the OS-managed encryption-at-rest and
//! "which app may read this" prompt a keychain additionally provides.
//! Nothing privileged is ever stored here: only the short-lived Supabase
//! user access/refresh token pair `src/lib/tauri-storage.ts` writes and
//! reads. No service-role key, database credential, or other secret is
//! ever read, written, or in scope here -- the desktop app remains a
//! public OAuth client, exactly like the web app, and every request it
//! makes still carries a real Supabase-issued JWT, verified server-side
//! exactly as before. Nothing about backend authentication changes.

use std::collections::HashMap;
use std::fs;
use std::io::ErrorKind;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

use tauri::{AppHandle, Manager, State};

const STORE_FILE_NAME: &str = "session-store.json";

/// Serializes access to the store file across concurrent command
/// invocations from the webview (Tauri dispatches commands concurrently
/// on its async runtime) -- without this, two overlapping `set` calls
/// could race a read-modify-write and one write silently clobber the
/// other's key instead of merging.
pub struct SessionStoreState(Mutex<()>);

impl SessionStoreState {
    pub fn new() -> Self {
        Self(Mutex::new(()))
    }
}

impl Default for SessionStoreState {
    fn default() -> Self {
        Self::new()
    }
}

fn store_path(app: &AppHandle) -> Result<PathBuf, String> {
    let dir = app
        .path()
        .app_data_dir()
        .map_err(|err| format!("could not resolve app data directory: {err}"))?;
    fs::create_dir_all(&dir).map_err(|err| format!("could not create app data directory: {err}"))?;
    Ok(dir.join(STORE_FILE_NAME))
}

fn read_store(path: &Path) -> Result<HashMap<String, String>, String> {
    match fs::read_to_string(path) {
        Ok(contents) => {
            if contents.trim().is_empty() {
                return Ok(HashMap::new());
            }
            serde_json::from_str(&contents).map_err(|err| format!("corrupt session store: {err}"))
        }
        Err(err) if err.kind() == ErrorKind::NotFound => Ok(HashMap::new()),
        Err(err) => Err(format!("could not read session store: {err}")),
    }
}

/// Write-to-temp-then-rename: `rename` is atomic on both APFS (macOS) and
/// NTFS (Windows) for a same-volume destination, so a crash or power loss
/// mid-write can never leave a half-written, corrupt store file behind --
/// readers only ever see the fully-old or fully-new contents.
fn write_store(path: &Path, data: &HashMap<String, String>) -> Result<(), String> {
    let serialized =
        serde_json::to_string(data).map_err(|err| format!("could not serialize session store: {err}"))?;
    let tmp_path = path.with_extension("json.tmp");
    fs::write(&tmp_path, serialized).map_err(|err| format!("could not write session store: {err}"))?;
    fs::rename(&tmp_path, path).map_err(|err| format!("could not finalize session store write: {err}"))?;
    Ok(())
}

#[tauri::command]
pub fn session_store_get(
    app: AppHandle,
    state: State<'_, SessionStoreState>,
    key: String,
) -> Result<Option<String>, String> {
    let _guard = state.0.lock().map_err(|_| "session store lock poisoned".to_string())?;
    let path = store_path(&app)?;
    Ok(read_store(&path)?.get(&key).cloned())
}

#[tauri::command]
pub fn session_store_set(
    app: AppHandle,
    state: State<'_, SessionStoreState>,
    key: String,
    value: String,
) -> Result<(), String> {
    let _guard = state.0.lock().map_err(|_| "session store lock poisoned".to_string())?;
    let path = store_path(&app)?;
    let mut data = read_store(&path)?;
    data.insert(key, value);
    write_store(&path, &data)
}

#[tauri::command]
pub fn session_store_delete(
    app: AppHandle,
    state: State<'_, SessionStoreState>,
    key: String,
) -> Result<(), String> {
    let _guard = state.0.lock().map_err(|_| "session store lock poisoned".to_string())?;
    let path = store_path(&app)?;
    let mut data = read_store(&path)?;
    data.remove(&key);
    write_store(&path, &data)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Exercises the pure file-format logic (read/write/atomic-rename,
    /// missing-file, empty-file, corrupt-file handling) directly against
    /// a real temp file -- the part with real failure modes worth
    /// covering. The `#[tauri::command]` wrappers above are thin
    /// argument/state plumbing around this and aren't independently
    /// tested here, matching this crate's own convention of testing
    /// through a real backend rather than mocking Tauri's command
    /// dispatch (see the OS-keychain version's tests, which used the
    /// `keyring` crate's real mock store for the same reason).
    fn temp_store_path(test_name: &str) -> PathBuf {
        let mut path = std::env::temp_dir();
        path.push(format!(
            "vinco-session-store-test-{test_name}-{}.json",
            std::process::id()
        ));
        let _ = fs::remove_file(&path);
        path
    }

    #[test]
    fn get_missing_key_on_a_nonexistent_file_returns_empty_map() {
        let path = temp_store_path("missing-file");
        assert_eq!(read_store(&path).unwrap(), HashMap::new());
    }

    #[test]
    fn set_then_get_round_trips() {
        let path = temp_store_path("round-trip");
        let mut data = read_store(&path).unwrap();
        data.insert("access_token".to_string(), "secret-value".to_string());
        write_store(&path, &data).unwrap();

        let reloaded = read_store(&path).unwrap();
        assert_eq!(reloaded.get("access_token"), Some(&"secret-value".to_string()));

        fs::remove_file(&path).ok();
    }

    #[test]
    fn overwrite_replaces_the_previous_value() {
        let path = temp_store_path("overwrite");
        let mut data = HashMap::new();
        data.insert("k".to_string(), "first".to_string());
        write_store(&path, &data).unwrap();

        let mut data = read_store(&path).unwrap();
        data.insert("k".to_string(), "second".to_string());
        write_store(&path, &data).unwrap();

        assert_eq!(read_store(&path).unwrap().get("k"), Some(&"second".to_string()));

        fs::remove_file(&path).ok();
    }

    #[test]
    fn delete_removes_only_the_named_key() {
        let path = temp_store_path("delete");
        let mut data = HashMap::new();
        data.insert("keep".to_string(), "1".to_string());
        data.insert("drop".to_string(), "2".to_string());
        write_store(&path, &data).unwrap();

        let mut data = read_store(&path).unwrap();
        data.remove("drop");
        write_store(&path, &data).unwrap();

        let reloaded = read_store(&path).unwrap();
        assert_eq!(reloaded.get("keep"), Some(&"1".to_string()));
        assert_eq!(reloaded.get("drop"), None);

        fs::remove_file(&path).ok();
    }

    #[test]
    fn an_empty_file_is_treated_as_an_empty_store_not_a_corrupt_one() {
        let path = temp_store_path("empty-file");
        fs::write(&path, "").unwrap();
        assert_eq!(read_store(&path).unwrap(), HashMap::new());
        fs::remove_file(&path).ok();
    }

    #[test]
    fn a_genuinely_corrupt_file_is_a_real_error_not_silently_treated_as_empty() {
        let path = temp_store_path("corrupt-file");
        fs::write(&path, "{not valid json").unwrap();
        assert!(read_store(&path).is_err());
        fs::remove_file(&path).ok();
    }
}
