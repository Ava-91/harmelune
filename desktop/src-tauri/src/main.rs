use serde_json::{json, Value};
use std::{
    io::{BufRead, BufReader, Write},
    path::PathBuf,
    process::{Child, ChildStdin, ChildStdout, Command, Stdio},
    sync::Mutex,
};
use tauri::{AppHandle, Emitter, Manager, State, path::BaseDirectory};

const PROTOCOL_VERSION: u64 = 1;

struct EngineProcess {
    child: Child,
    stdin: ChildStdin,
    stdout: BufReader<ChildStdout>,
}

#[derive(Default)]
struct EngineState(Mutex<Option<EngineProcess>>);

fn spawn_engine(app: &AppHandle) -> Result<EngineProcess, String> {
    let mut command = if cfg!(debug_assertions) {
        let project_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../..")
            .canonicalize()
            .map_err(|error| format!("Could not locate the Python project: {error}"))?;
        let python = if cfg!(windows) { "python" } else { "python3" };
        let mut command = Command::new(python);
        command
            .args(["-m", "harmelune.sidecar"])
            .current_dir(project_root);
        command
    } else {
        let sidecar = app
            .path()
            .resolve("binaries/harmelune-sidecar.exe", BaseDirectory::Resource)
            .map_err(|error| format!("Could not locate the packaged Python engine: {error}"))?;
        Command::new(sidecar)
    };

    let mut child = command
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()
        .map_err(|error| format!("Could not start the Python engine: {error}"))?;
    let stdin = child.stdin.take().ok_or("Python engine stdin was unavailable.")?;
    let stdout = child.stdout.take().ok_or("Python engine stdout was unavailable.")?;
    Ok(EngineProcess { child, stdin, stdout: BufReader::new(stdout) })
}

#[tauri::command]
fn engine_request(
    app: AppHandle,
    state: State<'_, EngineState>,
    request: Value,
) -> Result<Value, String> {
    if request.get("version").and_then(Value::as_u64) != Some(PROTOCOL_VERSION) {
        return Err(format!("Unsupported desktop protocol version; expected {PROTOCOL_VERSION}."));
    }
    let request_id = request
        .get("id")
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty() && value.len() <= 128)
        .ok_or("Every engine request needs a non-empty id.")?
        .to_owned();
    if request.get("command").and_then(Value::as_str) == Some("shutdown") {
        return Err("Use engine_stop to shut down the Python process cleanly.".to_string());
    }

    let mut guard = state.0.lock().map_err(|_| "Python engine lock was poisoned.")?;
    let exited = match guard.as_mut() {
        Some(process) => process.child.try_wait().map_err(|error| error.to_string())?.is_some(),
        None => true,
    };
    if exited {
        *guard = Some(spawn_engine(&app)?);
    }
    let process = guard.as_mut().ok_or("Python engine could not be started.")?;
    let encoded = serde_json::to_string(&request).map_err(|error| error.to_string())?;
    writeln!(process.stdin, "{encoded}").map_err(|error| format!("Could not write to Python engine: {error}"))?;
    process.stdin.flush().map_err(|error| format!("Could not flush Python request: {error}"))?;

    loop {
        let mut line = String::new();
        let bytes = process.stdout.read_line(&mut line)
            .map_err(|error| format!("Could not read Python engine response: {error}"))?;
        if bytes == 0 {
            return Err("Python engine closed its output unexpectedly.".to_string());
        }
        let response: Value = serde_json::from_str(&line)
            .map_err(|error| format!("Python engine returned invalid JSONL: {error}"))?;
        if response.get("type").and_then(Value::as_str) == Some("progress") {
            let _ = app.emit("engine-progress", response.clone());
            continue;
        }
        if response.get("id").and_then(Value::as_str) == Some(request_id.as_str()) {
            return Ok(response);
        }
    }
}

fn shutdown_engine(state: &EngineState) -> Result<(), String> {
    let mut guard = state.0.lock().map_err(|_| "Python engine lock was poisoned.")?;
    let Some(mut process) = guard.take() else { return Ok(()); };

    let request = json!({
        "version": PROTOCOL_VERSION,
        "id": "desktop-shutdown",
        "command": "shutdown",
        "params": {}
    });
    let encoded = serde_json::to_string(&request).map_err(|error| error.to_string())?;
    let mut clean_response = false;
    if writeln!(process.stdin, "{encoded}").is_ok() && process.stdin.flush().is_ok() {
        loop {
            let mut line = String::new();
            match process.stdout.read_line(&mut line) {
                Ok(0) | Err(_) => break,
                Ok(_) => {
                    if let Ok(response) = serde_json::from_str::<Value>(&line) {
                        if response.get("id").and_then(Value::as_str) == Some("desktop-shutdown")
                            && response.get("type").and_then(Value::as_str) == Some("result")
                        {
                            clean_response = true;
                            break;
                        }
                    }
                }
            }
        }
    }

    if clean_response {
        process.child.wait().map_err(|error| format!("Could not reap Python engine: {error}"))?;
        Ok(())
    } else {
        let _ = process.child.kill();
        let _ = process.child.wait();
        Err("Python engine did not acknowledge shutdown; the process was stopped.".to_string())
    }
}

#[tauri::command]
fn engine_stop(state: State<'_, EngineState>) -> Result<(), String> {
    shutdown_engine(state.inner())
}

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(EngineState::default())
        .invoke_handler(tauri::generate_handler![engine_request, engine_stop])
        .build(tauri::generate_context!())
        .expect("error while building Harmelune desktop");

    app.run(|app_handle, event| {
        if let tauri::RunEvent::Exit = event {
            let state = app_handle.state::<EngineState>();
            let _ = shutdown_engine(state.inner());
        }
    });
}
