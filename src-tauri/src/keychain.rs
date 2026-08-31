//! Production-safe Supabase session storage: the OS's own secure
//! credential store (Windows Credential Manager / macOS Keychain / Linux
//! Secret Service via the `keyring` crate), exposed to the frontend as
//! three small Tauri commands.
//!
//! This replaces the `@tauri-apps/plugin-store` JSON-file adapter the
//! desktop build previously used (see DESKTOP_ARCHITECTURE.md's original
//! "DESKTOP STORAGE" section, which named this as the follow-up
//! hardening step rather than guessing at it up front). A JSON file under
//! the app's data directory is readable by anything with that OS user's
//! file permissions; an OS credential store is the same protection every
//! other desktop application on that machine uses for its own secrets,
//! and on most platforms adds OS-level encryption at rest.
//!
//! Nothing privileged ever passes through here: only the short-lived
//! Supabase user access/refresh token pair `src/lib/tauri-storage.ts`
//! writes and reads (the same pair `localStorage` holds on the web
//! build). No service-role key, database credential, or other secret is
//! ever read, written, or in scope here -- the desktop app remains a
//! public OAuth client, exactly like the web app.

use keyring::Entry;

/// Groups every VINCO credential-store entry under one service name in
/// the OS store, distinct from any other application's entries.
const SERVICE: &str = "com.visioncontracting.vinco";

fn entry(key: &str) -> Result<Entry, String> {
    Entry::new(SERVICE, key).map_err(|err| err.to_string())
}

#[tauri::command]
pub fn keychain_get(key: String) -> Result<Option<String>, String> {
    match entry(&key)?.get_password() {
        Ok(value) => Ok(Some(value)),
        Err(keyring::Error::NoEntry) => Ok(None),
        Err(err) => Err(err.to_string()),
    }
}

#[tauri::command]
pub fn keychain_set(key: String, value: String) -> Result<(), String> {
    entry(&key)?.set_password(&value).map_err(|err| err.to_string())
}

#[tauri::command]
pub fn keychain_delete(key: String) -> Result<(), String> {
    match entry(&key)?.delete_credential() {
        Ok(()) => Ok(()),
        Err(keyring::Error::NoEntry) => Ok(()),
        Err(err) => Err(err.to_string()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The `keyring` crate always compiles in a platform-independent mock
    /// credential store specifically for this purpose (see its `mock`
    /// module docs) -- these tests never touch a real OS credential
    /// store, so they run identically in CI and on any developer's
    /// machine regardless of platform, and never leave real secrets
    /// behind.
    ///
    /// `Once`-guarded: Rust runs tests in parallel by default, and each
    /// call to `set_default_credential_builder` installs a *fresh* mock
    /// backend, which raced with other tests in this file's first
    /// version (confirmed by an intermittent failure) -- installing it
    /// once, before any test runs, avoids that.
    fn use_mock_backend() {
        static INIT: std::sync::Once = std::sync::Once::new();
        INIT.call_once(|| {
            keyring::set_default_credential_builder(keyring::mock::default_credential_builder());
        });
    }

    // IMPORTANT MOCK LIMITATION, discovered while writing these tests
    // (not assumed): the mock store's docs say "no persistence other
    // than in the entry itself" -- unlike a real OS keychain, two
    // separate `Entry::new(service, key)` calls for the same key are
    // NOT backed by a shared store under the mock; each gets its own
    // blank in-memory slot. `keychain_get`/`keychain_set`/
    // `keychain_delete` each construct a fresh `Entry` per call (correct
    // for a real backend, which persists to the OS store across separate
    // `Entry` objects) -- so a "set via one command call, get via
    // another" round trip genuinely cannot be exercised against the
    // mock. What CAN be verified here: the error-mapping logic in this
    // file (`NoEntry` -> `None`/`Ok(())`), which is real code with real
    // failure modes, and that `keyring::Entry`'s own set/get/delete cycle
    // round-trips correctly when the same entry is reused (the same
    // pattern `Entry` uses to talk to whichever real backend is
    // compiled in). End-to-end cross-call persistence against a real
    // backend was instead verified manually against this app's compiled
    // binary (see DESKTOP_ARCHITECTURE.md).

    #[test]
    fn get_missing_key_returns_none_not_error() {
        use_mock_backend();
        assert_eq!(keychain_get("test-missing-key".into()).unwrap(), None);
    }

    #[test]
    fn delete_of_missing_key_is_not_an_error() {
        use_mock_backend();
        keychain_delete("test-never-existed".into()).unwrap();
    }

    #[test]
    fn keyring_entry_set_get_delete_roundtrips_when_reused() {
        use_mock_backend();
        let e = entry("test-entry-reuse").unwrap();
        assert_eq!(e.get_password().unwrap_err().to_string(), keyring::Error::NoEntry.to_string());

        e.set_password("secret-value").unwrap();
        assert_eq!(e.get_password().unwrap(), "secret-value");

        e.set_password("overwritten").unwrap();
        assert_eq!(e.get_password().unwrap(), "overwritten");

        e.delete_credential().unwrap();
        assert_eq!(e.get_password().unwrap_err().to_string(), keyring::Error::NoEntry.to_string());
    }
}
