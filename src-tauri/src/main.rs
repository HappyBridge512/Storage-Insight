#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod backend;

use backend::BackendBridge;
use serde_json::{json, Value};
use std::{
    fs::{self, OpenOptions},
    io::Write,
    path::PathBuf,
    process::Command,
    time::{SystemTime, UNIX_EPOCH},
};
use tauri::{AppHandle, Manager, State};

#[tauri::command]
async fn backend_request(
    state: State<'_, BackendBridge>,
    method: String,
    payload: Value,
) -> Result<Value, String> {
    let bridge = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || bridge.request(&method, payload))
        .await
        .map_err(|error| error.to_string())?
        .map_err(|error| error.to_string())
}

#[tauri::command]
async fn open_folder_in_explorer(path: String) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || open_folder_in_explorer_blocking(path))
        .await
        .map_err(|error| error.to_string())?
}

#[tauri::command]
async fn frontend_log(
    app: AppHandle,
    level: String,
    message: String,
    context: Option<Value>,
) -> Result<(), String> {
    let log_path = frontend_log_path(&app)?;
    tauri::async_runtime::spawn_blocking(move || write_frontend_log(log_path, level, message, context))
        .await
        .map_err(|error| error.to_string())?
}

pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            let bridge = BackendBridge::spawn(app.handle().clone())?;
            app.manage(bridge);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            backend_request,
            open_folder_in_explorer,
            frontend_log
        ])
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                let app = window.app_handle();
                if let Some(bridge) = app.try_state::<BackendBridge>() {
                    let _ = bridge.shutdown();
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running Storage Insight");
}

fn main() {
    run();
}

fn open_folder_in_explorer_blocking(path: String) -> Result<(), String> {
    #[cfg(not(target_os = "windows"))]
    {
        let _ = path;
        return Err("Opening folders is currently supported only on Windows.".to_string());
    }

    #[cfg(target_os = "windows")]
    {
        let trimmed = path.trim();
        if trimmed.is_empty() {
            return Err("Select a folder before opening it.".to_string());
        }

        let folder = PathBuf::from(trimmed);
        let metadata = fs::metadata(&folder)
            .map_err(|error| format!("Selected folder is unavailable: {}", error))?;

        if !metadata.is_dir() {
            return Err("Selected path is not a folder.".to_string());
        }

        let folder = folder.canonicalize().unwrap_or(folder);
        Command::new("explorer.exe")
            .arg(folder.as_os_str())
            .spawn()
            .map(|_| ())
            .map_err(|error| format!("Failed to open Windows Explorer: {}", error))
    }
}

fn frontend_log_path(app: &AppHandle) -> Result<PathBuf, String> {
    app.path()
        .app_data_dir()
        .map(|path| path.join("logs").join("frontend.log"))
        .map_err(|error| format!("Failed to resolve app data directory: {}", error))
}

fn write_frontend_log(
    log_path: PathBuf,
    level: String,
    message: String,
    context: Option<Value>,
) -> Result<(), String> {
    if let Some(parent) = log_path.parent() {
        fs::create_dir_all(parent).map_err(|error| format!("Failed to create log directory: {}", error))?;
    }

    let timestamp_ms = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis())
        .unwrap_or_default();

    let entry = json!({
        "timestamp_ms": timestamp_ms,
        "level": normalize_log_level(&level),
        "message": message,
        "context": context.unwrap_or(Value::Null)
    });

    let mut file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&log_path)
        .map_err(|error| format!("Failed to open frontend log: {}", error))?;

    writeln!(file, "{}", entry).map_err(|error| format!("Failed to write frontend log: {}", error))
}

fn normalize_log_level(level: &str) -> &str {
    match level {
        "debug" | "info" | "warn" | "error" | "fatal" => level,
        _ => "error",
    }
}
