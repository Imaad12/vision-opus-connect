mod keychain;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  tauri::Builder::default()
    // Must be registered first (the crate's own documented requirement).
    // On Windows/Linux, a vinco:// launch while the app is already running
    // starts a *second* process rather than notifying the first one --
    // without this plugin that second process would just open its own
    // (unauthenticated) window and the OAuth callback would never reach
    // the original one. The "deep-link" feature makes it forward the
    // second launch's URL into tauri-plugin-deep-link's normal
    // `onOpenUrl` event automatically, so src/lib/tauri-auth.ts doesn't
    // need to know this happened -- same event, same handler, on every
    // platform. A no-op on macOS/iOS, which route repeat launches to the
    // running instance at the OS level already.
    .plugin(tauri_plugin_single_instance::init(|_app, _argv, _cwd| {}))
    .plugin(tauri_plugin_opener::init())
    .plugin(tauri_plugin_deep_link::init())
    .invoke_handler(tauri::generate_handler![
      keychain::keychain_get,
      keychain::keychain_set,
      keychain::keychain_delete,
    ])
    .setup(|app| {
      if cfg!(debug_assertions) {
        app.handle().plugin(
          tauri_plugin_log::Builder::default()
            .level(log::LevelFilter::Info)
            .build(),
        )?;
      }

      // Windows/Linux only: on those platforms a deep-link launch starts a
      // *new* process, so the scheme has to be registered explicitly here
      // (macOS/iOS instead route it through Info.plist, already declared
      // in tauri.conf.json's deep-link config). No-op everywhere else.
      //
      // Deliberately non-fatal: registration writes OS-level integration
      // state (a .desktop MIME association on Linux, a registry key on
      // Windows) that can fail on a locked-down or incompletely-configured
      // machine (confirmed: fails in this sandbox's minimal Linux
      // environment, no display-manager/XDG setup) without that being a
      // reason the whole app should refuse to start -- a user who can't
      // register the scheme just can't complete Google sign-in via the
      // deep-link callback yet; every other screen still works.
      #[cfg(any(target_os = "windows", target_os = "linux"))]
      {
        use tauri_plugin_deep_link::DeepLinkExt;
        if let Err(err) = app.deep_link().register_all() {
          log::warn!("failed to register vinco:// deep-link scheme: {err}");
        }
      }

      Ok(())
    })
    .run(tauri::generate_context!())
    .expect("error while running tauri application");
}
