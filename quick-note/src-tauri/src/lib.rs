use tauri::Window;
use std::process::Command;
use std::fs;

#[tauri::command]
async fn take_screenshot(window: Window) -> Result<String, String> {
    // 1. Hide the window to get it out of the screenshot
    window.hide().map_err(|e| e.to_string())?;

    // 2. Define temp file path
    let temp_path = "/tmp/arcus_screenshot.png";
    if fs::metadata(temp_path).is_ok() {
        let _ = fs::remove_file(temp_path);
    }

    // 3. Call native macOS screencapture with interactive selection (-i)
    // -s: interactive, -r: selection (optional, -i already allows selection), -o: no sound
    let status = Command::new("screencapture")
        .args(["-i", "-o", temp_path])
        .status()
        .map_err(|e| e.to_string())?;

    // 4. Show the window back
    window.show().map_err(|e| e.to_string())?;

    if status.success() {
        // 5. Read the file and convert to base64
        if fs::metadata(temp_path).is_ok() {
            let bytes = fs::read(temp_path).map_err(|e| e.to_string())?;
            use base64::{Engine as _, engine::general_purpose};
            let b64 = general_purpose::STANDARD.encode(bytes);
            let _ = fs::remove_file(temp_path);
            Ok(format!("data:image/png;base64,{}", b64))
        } else {
            Err("Zrzut ekranu został anulowany lub wystąpił błąd.".into())
        }
    } else {
        Err("Process screencapture failed".into())
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![take_screenshot])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
