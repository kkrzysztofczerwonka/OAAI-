use tauri::Window;
use std::process::Command;
use std::fs;
use arboard::Clipboard;

#[tauri::command]
async fn take_screenshot(
    window: Window, 
    area: Option<serde_json::Value>
) -> Result<String, String> {
    // 1. Hide the window to get it out of the screenshot
    window.hide().map_err(|e| e.to_string())?;

    // 2. Define temp file path correctly for the OS
    let mut temp_path = std::env::temp_dir();
    temp_path.push("arcus_screenshot.png");
    let _temp_str = temp_path.to_str().ok_or("Błąd ścieżki tymczasowej")?;

    if temp_path.exists() {
        let _ = fs::remove_file(&temp_path);
    }

    #[cfg(target_os = "macos")]
    {
        // 3a. Call native macOS screencapture with interactive selection (-i)
        let status = Command::new("screencapture")
            .args(["-i", "-o", temp_str])
            .status()
            .map_err(|e| e.to_string())?;

        // 4. Show the window back
        window.show().map_err(|e| e.to_string())?;

        if status.success() {
            if temp_path.exists() {
                let bytes = fs::read(&temp_path).map_err(|e| e.to_string())?;
                use base64::{Engine as _, engine::general_purpose};
                let b64 = general_purpose::STANDARD.encode(bytes);
                let _ = fs::remove_file(&temp_path);
                Ok(format!("data:image/png;base64,{}", b64))
            } else {
                Err("Zrzut ekranu został anulowany.".into())
            }
        } else {
            Err("Proces screencapture nie powiódł się".into())
        }
    }

    #[cfg(target_os = "windows")]
    {
        use screenshots::Screen;

        // Give a small delay to let the window hide
        std::thread::sleep(std::time::Duration::from_millis(150));

        let screens = Screen::all().map_err(|e| e.to_string())?;
        if let Some(screen) = screens.first() {
            let mut image = screen.capture().map_err(|e| e.to_string())?;
            
            // If area is provided, crop the image
            if let Some(area_val) = area {
                let x = area_val["x"].as_i64().unwrap_or(0) as u32;
                let y = area_val["y"].as_i64().unwrap_or(0) as u32;
                let w = area_val["width"].as_i64().unwrap_or(image.width() as i64) as u32;
                let h = area_val["height"].as_i64().unwrap_or(image.height() as i64) as u32;
                
                // Crop using the 'image' crate functionality through screenshots
                // screenshots uses 'image' crate under the hood but returns its own Wrapper
                // We need to be careful with bounds
                let crop_x = x.min(image.width());
                let crop_y = y.min(image.height());
                let crop_w = w.min(image.width() - crop_x);
                let crop_h = h.min(image.height() - crop_y);

                if crop_w > 0 && crop_h > 0 {
                    // Re-capture area if possible or crop the full one
                    // screenshots crate Screen::capture_area is better if available
                    image = screen.capture_area(crop_x as i32, crop_y as i32, crop_w, crop_h).map_err(|e| e.to_string())?;
                }
            }

            image.save(&temp_path).map_err(|e| e.to_string())?;

            // 4. Show the window back
            window.show().map_err(|e| e.to_string())?;

            if temp_path.exists() {
                let bytes = fs::read(&temp_path).map_err(|e| e.to_string())?;
                use base64::{Engine as _, engine::general_purpose};
                let b64 = general_purpose::STANDARD.encode(bytes);
                let _ = fs::remove_file(&temp_path);
                Ok(format!("data:image/png;base64,{}", b64))
            } else {
                Err("Błąd zapisu zrzutu na Windows.".into())
            }
        } else {
            window.show().map_err(|e| e.to_string())?;
            Err("Nie znaleziono ekranu do przechwycenia.".into())
        }
    }

    #[cfg(not(any(target_os = "macos", target_os = "windows")))]
    {
        window.show().map_err(|e| e.to_string())?;
        Err("Zrzuty ekranu nie są wspierane na tym systemie.".into())
    }
}

#[tauri::command]
async fn trigger_windows_snip() -> Result<(), String> {
    #[cfg(target_os = "windows")]
    {
        Command::new("powershell")
            .args(["-Command", "Start-Process ms-screen-sketch:snip"])
            .spawn()
            .map_err(|e| e.to_string())?;
        Ok(())
    }
    #[cfg(not(target_os = "windows"))]
    Err("To jest funkcja dostępna tylko na Windows.".into())
}

#[tauri::command]
async fn read_clipboard_image() -> Result<String, String> {
    let mut clipboard = Clipboard::new().map_err(|e| format!("Błąd schowka: {}", e))?;
    let image = clipboard.get_image().map_err(|_| "W schowku nie znaleziono obrazu. Upewnij się, że zrobiłeś zrzut ekranu.".to_string())?;
    
    // Convert to PNG bytes
    let mut png_bytes: Vec<u8> = Vec::new();
    let dynamic_image = image::DynamicImage::ImageRgba8(
        image::ImageBuffer::from_raw(
            image.width as u32,
            image.height as u32,
            image.bytes.into_owned()
        ).ok_or("Błąd przetwarzania danych obrazu")?
    );
    
    let mut cursor = std::io::Cursor::new(&mut png_bytes);
    dynamic_image.write_to(&mut cursor, image::ImageFormat::Png)
        .map_err(|e| format!("Błąd zapisu PNG: {}", e))?;

    use base64::{Engine as _, engine::general_purpose};
    let b64 = general_purpose::STANDARD.encode(png_bytes);
    Ok(format!("data:image/png;base64,{}", b64))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![
            take_screenshot, 
            trigger_windows_snip,
            read_clipboard_image
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
