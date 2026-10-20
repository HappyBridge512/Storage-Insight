mod protocol;

use protocol::{BackendRequest, BackendResponse};
use serde_json::{json, Value};
use std::{
    collections::HashMap,
    env,
    io::{BufRead, BufReader, Write},
    path::{Path, PathBuf},
    process::{Child, ChildStdin, Command, Stdio},
    sync::{
        mpsc::{self, Receiver, Sender},
        Arc, Mutex,
    },
    thread,
    time::Duration,
};
use tauri::{AppHandle, Emitter, Manager};
use thiserror::Error;
use uuid::Uuid;

#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;

type PendingMap = Arc<Mutex<HashMap<String, Sender<Result<Value, BackendBridgeError>>>>>;

struct BackendRuntime {
    executable: PathBuf,
    args: Vec<String>,
    working_dir: PathBuf,
    kind: &'static str,
}

#[derive(Debug, Clone, Error)]
pub enum BackendBridgeError {
    #[error("backend process is not available")]
    ProcessUnavailable,
    #[error("backend process exited unexpectedly (code {0})")]
    ProcessExited(i32),
    #[error("backend stdin is closed")]
    StdinClosed,
    #[error("backend request timed out")]
    RequestTimedOut,
    #[error("backend returned {code}: {message}")]
    BackendReturned { code: String, message: String },
    #[error("backend runtime check failed: {0}")]
    RuntimeCheckFailed(String),
    #[error("io error: {0}")]
    Io(String),
    #[error("json error: {0}")]
    Json(String),
}

impl From<std::io::Error> for BackendBridgeError {
    fn from(error: std::io::Error) -> Self {
        BackendBridgeError::Io(error.to_string())
    }
}

impl From<serde_json::Error> for BackendBridgeError {
    fn from(error: serde_json::Error) -> Self {
        BackendBridgeError::Json(error.to_string())
    }
}

#[derive(Clone)]
pub struct BackendBridge {
    inner: Arc<BackendBridgeInner>,
}

struct BackendBridgeInner {
    child: Arc<Mutex<Child>>,
    stdin: Arc<Mutex<ChildStdin>>,
    pending: PendingMap,
}

impl BackendBridge {
    pub fn spawn(app_handle: AppHandle) -> Result<Self, BackendBridgeError> {
        let runtime = backend_runtime(&app_handle)?;

        let mut command = Command::new(&runtime.executable);
        command
            .args(&runtime.args)
            .current_dir(&runtime.working_dir)
            .env("PYTHONUNBUFFERED", "1")
            .env("PYTHONUTF8", "1")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        configure_backend_command(&mut command);

        let mut child = command.spawn()?;

        let _ = app_handle.emit(
            "backend-event",
            json!({
                "event": "backend.runtime",
                "payload": {
                    "kind": runtime.kind,
                    "executable": runtime.executable.display().to_string()
                }
            }),
        );

        let stdin = child.stdin.take().ok_or(BackendBridgeError::StdinClosed)?;
        let stdout = child.stdout.take().ok_or(BackendBridgeError::ProcessUnavailable)?;
        let stderr = child.stderr.take().ok_or(BackendBridgeError::ProcessUnavailable)?;

        let child = Arc::new(Mutex::new(child));
        let pending: PendingMap = Arc::new(Mutex::new(HashMap::new()));

        spawn_stdout_reader(app_handle.clone(), stdout, pending.clone(), child.clone());
        spawn_stderr_reader(app_handle.clone(), stderr);

        Ok(Self {
            inner: Arc::new(BackendBridgeInner {
                child,
                stdin: Arc::new(Mutex::new(stdin)),
                pending,
            }),
        })
    }

    pub fn request(&self, method: &str, payload: Value) -> Result<Value, BackendBridgeError> {
        self.inner
            .request_with_timeout(method, payload, Duration::from_secs(30 * 60))
    }

    pub fn shutdown(&self) -> Result<(), BackendBridgeError> {
        self.inner.shutdown()
    }
}

impl BackendBridgeInner {
    fn request_with_timeout(
        &self,
        method: &str,
        payload: Value,
        timeout: Duration,
    ) -> Result<Value, BackendBridgeError> {
        self.ensure_child_running()?;

        let id = Uuid::new_v4().to_string();
        let (tx, rx): (
            Sender<Result<Value, BackendBridgeError>>,
            Receiver<Result<Value, BackendBridgeError>>,
        ) = mpsc::channel();

        self.pending.lock().expect("pending map poisoned").insert(id.clone(), tx);

        let request = BackendRequest {
            id: &id,
            method,
            payload,
        };

        let write_result = self.write_message(&request);
        if let Err(error) = write_result {
            self.pending.lock().expect("pending map poisoned").remove(&id);
            return Err(error);
        }

        match rx.recv_timeout(timeout) {
            Ok(response) => response,
            Err(_) => {
                self.pending.lock().expect("pending map poisoned").remove(&id);
                Err(BackendBridgeError::RequestTimedOut)
            }
        }
    }

    fn shutdown(&self) -> Result<(), BackendBridgeError> {
        if self.ensure_child_running().is_ok() {
            let _ = self.request_with_timeout("shutdown", json!({}), Duration::from_secs(2));
        }

        let mut child = self.child.lock().expect("child mutex poisoned");
        thread::sleep(Duration::from_millis(150));
        match child.try_wait()? {
            Some(_) => Ok(()),
            None => {
                let _ = child.kill();
                Ok(())
            }
        }
    }

    fn ensure_child_running(&self) -> Result<(), BackendBridgeError> {
        let mut child = self.child.lock().expect("child mutex poisoned");
        match child.try_wait()? {
            None => Ok(()),
            Some(status) => Err(BackendBridgeError::ProcessExited(status.code().unwrap_or(-1))),
        }
    }

    fn write_message(&self, request: &BackendRequest<'_>) -> Result<(), BackendBridgeError> {
        self.ensure_child_running()?;
        let encoded = serde_json::to_string(request)?;
        let mut stdin = self.stdin.lock().expect("stdin mutex poisoned");
        stdin.write_all(encoded.as_bytes())?;
        stdin.write_all(b"\n")?;
        stdin.flush()?;
        Ok(())
    }
}

impl Drop for BackendBridgeInner {
    fn drop(&mut self) {
        let _ = self.shutdown();
    }
}

fn backend_runtime(app_handle: &AppHandle) -> Result<BackendRuntime, BackendBridgeError> {
    let mut errors = Vec::new();
    let python = python_backend_runtime();
    let bundled = bundled_backend_runtime(app_handle);

    let candidates = vec![bundled, python];

    for runtime in candidates.into_iter().flatten() {
        if !runtime.working_dir.is_dir() {
            errors.push(format!(
                "{} backend working directory not found: {}",
                runtime.kind,
                runtime.working_dir.display()
            ));
            continue;
        }

        if !runtime_executable_available(&runtime.executable) {
            errors.push(format!(
                "{} backend executable not found: {}",
                runtime.kind,
                runtime.executable.display()
            ));
            continue;
        }

        if runtime.kind == "python" {
            match verify_backend_runtime(&runtime.executable, &runtime.working_dir) {
                Ok(()) => return Ok(runtime),
                Err(error) => {
                    errors.push(error.to_string());
                    continue;
                }
            }
        }

        return Ok(runtime);
    }

    Err(BackendBridgeError::RuntimeCheckFailed(format!(
        "no usable backend runtime found. {}",
        errors.join("; ")
    )))
}

fn python_backend_runtime() -> Option<BackendRuntime> {
    Some(BackendRuntime {
        executable: python_executable(),
        args: vec!["-m".to_string(), "storage_insight_backend".to_string()],
        working_dir: backend_dir(),
        kind: "python",
    })
}

fn bundled_backend_runtime(app_handle: &AppHandle) -> Option<BackendRuntime> {
    for executable in bundled_backend_candidates(app_handle) {
        if executable.is_file() {
            let working_dir = executable
                .parent()
                .map(Path::to_path_buf)
                .unwrap_or_else(project_root);
            return Some(BackendRuntime {
                executable,
                args: Vec::new(),
                working_dir,
                kind: "bundled",
            });
        }
    }

    None
}

fn bundled_backend_candidates(app_handle: &AppHandle) -> Vec<PathBuf> {
    let mut candidates = Vec::new();

    if let Ok(path) = env::var("STORAGE_INSIGHT_BACKEND_EXE") {
        candidates.push(PathBuf::from(path));
    }

    let project = project_root();
    let project_candidates = [
        project
            .join("backend")
            .join("bin")
            .join("storage-insight-backend.exe"),
        project
            .join("backend")
            .join("dist")
            .join("storage-insight-backend.exe"),
    ];

    if cfg!(debug_assertions) {
        candidates.extend(project_candidates.iter().cloned());
    }

    if let Ok(resource_dir) = app_handle.path().resource_dir() {
        candidates.push(
            resource_dir
                .join("backend")
                .join("bin")
                .join("storage-insight-backend.exe"),
        );
        candidates.push(resource_dir.join("storage-insight-backend.exe"));
    }

    if !cfg!(debug_assertions) {
        candidates.extend(project_candidates);
    }

    candidates
}

fn runtime_executable_available(executable: &Path) -> bool {
    executable.is_file() || executable.parent().is_none_or(|parent| parent.as_os_str().is_empty())
}

#[cfg(target_os = "windows")]
fn configure_backend_command(command: &mut Command) {
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    command.creation_flags(CREATE_NO_WINDOW);
}

#[cfg(not(target_os = "windows"))]
fn configure_backend_command(_command: &mut Command) {}

fn verify_backend_runtime(python: &Path, backend_dir: &Path) -> Result<(), BackendBridgeError> {
    let output = Command::new(python)
        .args(["-c", "import storage_insight_backend"])
        .current_dir(backend_dir)
        .stderr(Stdio::piped())
        .output()?;

    if output.status.success() {
        return Ok(());
    }

    let stderr = String::from_utf8_lossy(&output.stderr);
    Err(BackendBridgeError::RuntimeCheckFailed(format!(
        "could not import storage_insight_backend with {}: {}",
        python.display(),
        stderr.trim()
    )))
}

fn fail_all_pending(pending: &PendingMap, error: BackendBridgeError) {
    let mut guard = pending.lock().expect("pending map poisoned");
    for (_, tx) in guard.drain() {
        let _ = tx.send(Err(error.clone()));
    }
}

fn emit_backend_exited(app_handle: &AppHandle, exit_code: Option<i32>) {
    let _ = app_handle.emit(
        "backend-event",
        json!({
            "event": "backend.exited",
            "payload": { "exit_code": exit_code }
        }),
    );
}

fn backend_dir() -> PathBuf {
    if let Ok(path) = env::var("STORAGE_INSIGHT_BACKEND_DIR") {
        return PathBuf::from(path);
    }

    project_root().join("backend")
}

fn project_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("src-tauri should have a project root")
        .to_path_buf()
}

fn python_executable() -> PathBuf {
    if let Ok(path) = env::var("STORAGE_INSIGHT_PYTHON") {
        return PathBuf::from(path);
    }

    let venv_python = project_root().join(".venv").join("Scripts").join("python.exe");
    if venv_python.is_file() {
        return venv_python;
    }

    PathBuf::from("python")
}

fn spawn_stdout_reader<R>(app_handle: AppHandle, stdout: R, pending: PendingMap, child: Arc<Mutex<Child>>)
where
    R: std::io::Read + Send + 'static,
{
    thread::spawn(move || {
        let reader = BufReader::new(stdout);

        for line in reader.lines().map_while(Result::ok) {
            match serde_json::from_str::<BackendResponse>(&line) {
                Ok(message) => {
                    if let Some(event) = message.event {
                        let payload = message.payload.unwrap_or(Value::Null);
                        let _ = app_handle.emit("backend-event", json!({ "event": event, "payload": payload }));
                        continue;
                    }

                    if let Some(id) = message.id {
                        let tx = pending.lock().expect("pending map poisoned").remove(&id);
                        if let Some(tx) = tx {
                            let response = if message.ok.unwrap_or(false) {
                                Ok(message.result.unwrap_or(Value::Null))
                            } else if let Some(error) = message.error {
                                Err(BackendBridgeError::BackendReturned {
                                    code: error.code,
                                    message: error.message,
                                })
                            } else {
                                Err(BackendBridgeError::BackendReturned {
                                    code: "BackendError".to_string(),
                                    message: "backend response did not include result or error".to_string(),
                                })
                            };
                            let _ = tx.send(response);
                        }
                    }
                }
                Err(error) => {
                    let _ = app_handle.emit(
                        "backend-event",
                        json!({
                            "event": "backend.protocol_error",
                            "payload": { "message": error.to_string() }
                        }),
                    );
                }
            }
        }

        let exit_code = child
            .lock()
            .expect("child mutex poisoned")
            .try_wait()
            .ok()
            .flatten()
            .and_then(|status| status.code());

        fail_all_pending(&pending, BackendBridgeError::ProcessUnavailable);
        emit_backend_exited(&app_handle, exit_code);
    });
}

fn spawn_stderr_reader<R>(app_handle: AppHandle, stderr: R)
where
    R: std::io::Read + Send + 'static,
{
    thread::spawn(move || {
        let reader = BufReader::new(stderr);
        for line in reader.lines().map_while(Result::ok) {
            let _ = app_handle.emit(
                "backend-event",
                json!({ "event": "backend.stderr", "payload": { "line": line } }),
            );
        }
    });
}
