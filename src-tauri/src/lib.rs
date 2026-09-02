mod session_store;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  tauri::Builder::default()
    // Must be registered first (the crate's own documented requirement).
    // Prevents a second launch from opening a second, separately
    // authenticated window -- a no-op on macOS/iOS, which already route
    // repeat launches to the running instance at the OS level.
    .plugin(tauri_plugin_single_instance::init(|_app, _argv, _cwd| {}))
    .plugin(tauri_plugin_opener::init())
    .manage(session_store::SessionStoreState::new())
    .invoke_handler(tauri::generate_handler![
      session_store::session_store_get,
      session_store::session_store_set,
      session_store::session_store_delete,
    ])
    .setup(|app| {
      if cfg!(debug_assertions) {
        app.handle().plugin(
          tauri_plugin_log::Builder::default()
            .level(log::LevelFilter::Info)
            .build(),
        )?;
      }

      Ok(())
    })
    .run(tauri::generate_context!())
    .expect("error while running tauri application");
}
