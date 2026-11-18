use serde_json::{json, Value};
use std::{
    collections::HashMap,
    io::{BufRead, BufReader, Read, Write},
    path::PathBuf,
    process::{Child, ChildStdin, ChildStdout, Command, Stdio},
    sync::{mpsc, Arc, Mutex},
    thread,
    time::{Duration, Instant},
};
use tauri::{AppHandle, Emitter, Manager, State, path::BaseDirectory};

const PROTOCOL_VERSION: u64 = 1;
const MAX_REQUEST_BYTES: usize = 1_048_576;
const MAX_RESPONSE_BYTES: u64 = 4_194_304;
const DEFAULT_REQUEST_TIMEOUT: Duration = Duration::from_secs(30);
const LONG_REQUEST_TIMEOUT: Duration = Duration::from_secs(10 * 60);

type PendingRequests = Arc<Mutex<HashMap<String, mpsc::Sender<Value>>>>;

struct EngineProcess {
    child: Child,
    stdin: ChildStdin,
    pending: PendingRequests,
}

#[derive(Default)]
struct EngineState(Mutex<Option<EngineProcess>>);

fn fail_pending(pending: &PendingRequests, message: &str) {
    if let Ok(mut requests) = pending.lock() {
        for (id, sender) in requests.drain() {
            let _ = sender.send(json!({
                "version": PROTOCOL_VERSION, "id": id, "type": "error", "ok": false,
                "error": {"code": "ENGINE_STOPPED", "message": message}
            }));
        }
    }
}

fn spawn_engine(app: &AppHandle) -> Result<EngineProcess, String> {
    let mut command = if cfg!(debug_assertions) {
        let project_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../..")
            .canonicalize()
            .map_err(|error| format!("Could not locate the Python project: {error}"))?;
        let python = if cfg!(windows) { "python" } else { "python3" };
        let mut command = Command::new(python);
        command.args(["-m", "harmelune.sidecar"]).current_dir(project_root);
        command
    } else {
        let sidecar = app.path()
            .resolve("binaries/harmelune-sidecar.exe", BaseDirectory::Resource)
            .map_err(|error| format!("Could not locate the packaged Python engine: {error}"))?;
        Command::new(sidecar)
    };

    let mut child = command.stdin(Stdio::piped()).stdout(Stdio::piped())
        .stderr(Stdio::inherit()).spawn()
        .map_err(|error| format!("Could not start the Python engine: {error}"))?;
    let stdin = child.stdin.take().ok_or("Python engine stdin was unavailable.")?;
    let stdout = child.stdout.take().ok_or("Python engine stdout was unavailable.")?;
    let pending: PendingRequests = Arc::new(Mutex::new(HashMap::new()));
    let reader_pending = Arc::clone(&pending);
    let reader_app = app.clone();

    thread::Builder::new().name("harmelune-sidecar-reader".into()).spawn(move || {
        let mut reader = BufReader::new(stdout);
        loop {
            let mut line = Vec::new();
            let bytes = {
                let mut limited = (&mut reader).take(MAX_RESPONSE_BYTES + 1);
                match limited.read_until(b'\n', &mut line) {
                    Ok(size) => size,
                    Err(error) => {
                        fail_pending(&reader_pending, &format!("Could not read Python engine output: {error}"));
                        return;
                    }
                }
            };
            if bytes == 0 {
                fail_pending(&reader_pending, "Python engine closed its output unexpectedly.");
                return;
            }
            if bytes as u64 > MAX_RESPONSE_BYTES || !line.ends_with(b"\n") {
                fail_pending(&reader_pending, "Python engine response exceeded the 4 MiB line limit.");
                return;
            }
            let response: Value = match serde_json::from_slice(&line) {
                Ok(value) => value,
                Err(error) => {
                    fail_pending(&reader_pending, &format!("Python engine returned invalid JSONL: {error}"));
                    return;
                }
            };
            if response.get("type").and_then(Value::as_str) == Some("progress") {
                let _ = reader_app.emit("engine-progress", response);
                continue;
            }
            if let Some(id) = response.get("id").and_then(Value::as_str) {
                if let Ok(mut requests) = reader_pending.lock() {
                    if let Some(sender) = requests.remove(id) {
                        let _ = sender.send(response);
                    }
                }
            }
        }
    }).map_err(|error| format!("Could not start the sidecar response reader: {error}"))?;

    Ok(EngineProcess { child, stdin, pending })
}

fn request_timeout(command: &str) -> Duration {
    match command {
        "scan" | "execute_safe" | "execute_reconcile" | "execute_mirror" | "execute_restore" => LONG_REQUEST_TIMEOUT,
        _ => DEFAULT_REQUEST_TIMEOUT,
    }
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
    let request_id = request.get("id").and_then(Value::as_str)
        .filter(|value| !value.is_empty() && value.len() <= 128)
        .ok_or("Every engine request needs a non-empty id.")?.to_owned();
    let command = request.get("command").and_then(Value::as_str)
        .ok_or("Every engine request needs a command.")?.to_owned();
    let encoded = serde_json::to_vec(&request).map_err(|error| error.to_string())?;
    if encoded.len() > MAX_REQUEST_BYTES {
        return Err("Desktop request exceeded the 1 MiB limit.".to_string());
    }

    let (sender, receiver) = mpsc::channel();
    {
        let mut guard = state.0.lock().map_err(|_| "Python engine lock was poisoned.")?;
        let exited = match guard.as_mut() {
            Some(process) => process.child.try_wait().map_err(|error| error.to_string())?.is_some(),
            None => true,
        };
        if exited {
            if let Some(mut old) = guard.take() {
                fail_pending(&old.pending, "Python engine exited and was restarted.");
                let _ = old.child.kill();
                let _ = old.child.wait();
            }
            *guard = Some(spawn_engine(&app)?);
        }
        let process = guard.as_mut().ok_or("Python engine could not be started.")?;
        {
            let mut pending = process.pending.lock().map_err(|_| "Pending request registry was poisoned.")?;
            if pending.contains_key(&request_id) {
                return Err("Request id is already in use.".to_string());
            }
            pending.insert(request_id.clone(), sender);
        }
        if let Err(error) = process.stdin.write_all(&encoded)
            .and_then(|_| process.stdin.write_all(b"\n"))
            .and_then(|_| process.stdin.flush())
        {
            if let Ok(mut pending) = process.pending.lock() {
                pending.remove(&request_id);
            }
            return Err(format!("Could not send request to Python engine: {error}"));
        }
    }

    match receiver.recv_timeout(request_timeout(&command)) {
        Ok(response) => Ok(response),
        Err(mpsc::RecvTimeoutError::Timeout) => {
            if let Ok(mut guard) = state.0.lock() {
                if let Some(mut process) = guard.take() {
                    fail_pending(&process.pending, "Python engine was stopped after a request timeout.");
                    let _ = process.child.kill();
                    let _ = process.child.wait();
                }
            }
            Err(format!("Python engine request '{command}' exceeded its time limit; the sidecar was stopped. Retry after checking the library state."))
        }
        Err(mpsc::RecvTimeoutError::Disconnected) => {
            Err("Python engine response channel closed unexpectedly.".to_string())
        }
    }
}

fn shutdown_engine(state: &EngineState) -> Result<(), String> {
    let mut guard = state.0.lock().map_err(|_| "Python engine lock was poisoned.")?;
    let Some(mut process) = guard.take() else { return Ok(()); };
    let shutdown = json!({
        "version": PROTOCOL_VERSION, "id": "desktop-shutdown",
        "command": "shutdown", "params": {}
    });
    let _ = serde_json::to_vec(&shutdown).map(|line| {
        let _ = process.stdin.write_all(&line);
        let _ = process.stdin.write_all(b"\n");
        let _ = process.stdin.flush();
    });
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        match process.child.try_wait() {
            Ok(Some(_)) => return Ok(()),
            Ok(None) if Instant::now() < deadline => thread::sleep(Duration::from_millis(50)),
            _ => {
                let _ = process.child.kill();
                let _ = process.child.wait();
                fail_pending(&process.pending, "Python engine was stopped during application shutdown.");
                return Ok(());
            }
        }
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
        .build()
        .expect("error while building Harmelune desktop");

    app.run(|app_handle, event| {
        if let tauri::RunEvent::Exit = event {
            let state = app_handle.state::<EngineState>();
            let _ = shutdown_engine(state.inner());
        }
    });
}
