use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::{
    env,
    ffi::OsStr,
    fs,
    io::{BufRead, BufReader, Read},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
    thread,
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use tauri::{path::BaseDirectory, Emitter, Manager};

#[derive(Debug, Clone)]
struct HelperInvocation {
    program: PathBuf,
    prefix_args: Vec<String>,
    python_path: Option<PathBuf>,
    workdir: Option<PathBuf>,
}

#[derive(Debug, Serialize)]
struct HelperResult {
    ok: bool,
    code: Option<i32>,
    stdout: String,
    stderr: String,
    cancelled: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct ModelOperationProgress {
    schema: u8,
    id: String,
    kind: String,
    action: String,
    model: String,
    phase: String,
    component: Option<String>,
    downloaded_bytes: u64,
    total_bytes: Option<u64>,
    percent: Option<f64>,
    cancellable: bool,
    updated_at: f64,
}

struct ActiveModelOperation {
    id: String,
    child: Arc<Mutex<Child>>,
    cancelled: Arc<AtomicBool>,
}

#[derive(Default)]
struct ModelOperationInner {
    active: Option<ActiveModelOperation>,
    latest: Option<ModelOperationProgress>,
}

#[derive(Default)]
struct ModelOperationState(Mutex<ModelOperationInner>);

const MODEL_PROGRESS_PREFIX: &str = "BLE_STT_MODEL_PROGRESS ";

const TELEMETRY_FILE_NAME: &str = "ble-stt-runtime.json";
const PERFORMANCE_FILE_NAME: &str = "ble-stt-performance.json";
const TELEMETRY_SCHEMA: i32 = 2;
const TELEMETRY_STALE_SECONDS: f64 = 8.0;

fn helper_cli_args() -> Option<Vec<String>> {
    let mut args: Vec<String> = env::args()
        .skip(1)
        .filter(|arg| !arg.starts_with("-psn_"))
        .collect();
    if args.is_empty() {
        return None;
    }
    if args[0] == "service-run" {
        args[0] = "run".into();
        return Some(args);
    }
    match args[0].as_str() {
        "run" | "status" | "logs" | "telemetry" | "performance" | "service" | "permissions"
        | "prepare" | "models" | "mappings" | "commands" | "voice-settings" | "doctor" | "test"
        | "journey-test" | "restart" | "upgrade" | "uninstall" | "help" | "--version" | "-h"
        | "--help" => Some(args),
        _ => None,
    }
}

fn helper_binary_name() -> &'static str {
    if cfg!(windows) {
        "m5stopwatch-ble-stt.exe"
    } else {
        "m5stopwatch-ble-stt"
    }
}

fn target_sidecar_name() -> &'static str {
    if cfg!(all(target_os = "macos", target_arch = "aarch64")) {
        "m5stopwatch-ble-stt-aarch64-apple-darwin"
    } else if cfg!(all(target_os = "macos", target_arch = "x86_64")) {
        "m5stopwatch-ble-stt-x86_64-apple-darwin"
    } else if cfg!(all(target_os = "windows", target_arch = "x86_64")) {
        "m5stopwatch-ble-stt-x86_64-pc-windows-msvc.exe"
    } else if cfg!(all(target_os = "windows", target_arch = "aarch64")) {
        "m5stopwatch-ble-stt-aarch64-pc-windows-msvc.exe"
    } else if cfg!(all(target_os = "linux", target_arch = "x86_64")) {
        "m5stopwatch-ble-stt-x86_64-unknown-linux-gnu"
    } else if cfg!(all(target_os = "linux", target_arch = "aarch64")) {
        "m5stopwatch-ble-stt-aarch64-unknown-linux-gnu"
    } else {
        helper_binary_name()
    }
}

#[cfg(target_os = "macos")]
fn helper_app_executable(root: &Path) -> PathBuf {
    root.join("M5StopWatch.app")
        .join("Contents")
        .join("MacOS")
        .join("M5StopWatch")
}

fn candidate_sidecars(app: Option<&tauri::AppHandle>) -> Vec<PathBuf> {
    let mut paths = Vec::new();
    if let Ok(path) = env::var("BLE_STT_HELPER") {
        paths.push(PathBuf::from(path));
    }
    if cfg!(target_os = "macos") {
        for root in [
            PathBuf::from("/Applications/M5StopWatch.app"),
            env::var_os("HOME")
                .map(PathBuf::from)
                .map(|home| home.join("Applications").join("M5StopWatch.app"))
                .unwrap_or_default(),
        ] {
            if root.as_os_str().is_empty() {
                continue;
            }
            let helper_root = root
                .join("Contents")
                .join("Resources")
                .join("resources")
                .join("ble-stt-helper");
            paths.push(helper_app_executable(&helper_root));
            paths.push(helper_root.join("M5StopWatch"));
            paths.push(helper_root.join(helper_binary_name()));
            paths.push(helper_root.join(target_sidecar_name()));
        }
    }
    if let Some(app) = app {
        let resource_candidates = [
            "ble-stt-helper/M5StopWatch.app/Contents/MacOS/M5StopWatch".to_string(),
            format!("ble-stt-helper/{}", helper_binary_name()),
            "ble-stt-helper/M5StopWatch".to_string(),
            format!("ble-stt-helper/{}", target_sidecar_name()),
            "resources/ble-stt-helper/M5StopWatch.app/Contents/MacOS/M5StopWatch".to_string(),
            format!("resources/ble-stt-helper/{}", helper_binary_name()),
            "resources/ble-stt-helper/M5StopWatch".to_string(),
            format!("resources/ble-stt-helper/{}", target_sidecar_name()),
        ];
        for resource_path in resource_candidates {
            if let Ok(path) = app.path().resolve(resource_path, BaseDirectory::Resource) {
                paths.push(path);
            }
        }
    }
    if let Ok(exe) = env::current_exe() {
        if let Some(directory) = exe.parent() {
            paths.push(directory.join(helper_binary_name()));
            paths.push(directory.join(target_sidecar_name()));
            if cfg!(target_os = "macos") {
                if let Some(contents) = directory.parent() {
                    let resources = contents.join("Resources");
                    paths.push(resources.join(helper_binary_name()));
                    paths.push(resources.join(target_sidecar_name()));
                    let helper_root = resources.join("resources").join("ble-stt-helper");
                    paths.push(helper_app_executable(&helper_root));
                    paths.push(helper_root.join("M5StopWatch"));
                    paths.push(helper_root.join(helper_binary_name()));
                    paths.push(helper_root.join(target_sidecar_name()));
                }
            }
        }
    }
    paths
}

fn source_helper_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .and_then(Path::parent)
        .map(Path::to_path_buf)
        .unwrap_or_else(|| PathBuf::from(".."))
}

fn resolve_helper(app: Option<&tauri::AppHandle>) -> Result<HelperInvocation, String> {
    for path in candidate_sidecars(app) {
        if path.exists() {
            return Ok(HelperInvocation {
                program: path,
                prefix_args: Vec::new(),
                python_path: None,
                workdir: None,
            });
        }
    }

    let root = source_helper_root();
    if !root.join("ble_stt").join("__init__.py").exists() {
        return Err("could not locate the bundled helper or source-tree ble_stt package".into());
    }

    let python = env::var("BLE_STT_PYTHON").unwrap_or_else(|_| {
        if cfg!(windows) {
            "python".into()
        } else {
            "python3".into()
        }
    });
    Ok(HelperInvocation {
        program: PathBuf::from(python),
        prefix_args: vec!["-m".into(), "ble_stt".into()],
        python_path: Some(root.clone()),
        workdir: Some(root),
    })
}

fn run_helper<I, S>(app: Option<&tauri::AppHandle>, args: I) -> Result<HelperResult, String>
where
    I: IntoIterator<Item = S>,
    S: AsRef<OsStr>,
{
    let helper = resolve_helper(app)?;
    let mut command = Command::new(&helper.program);
    command.args(&helper.prefix_args).args(args);
    configure_macos_service_env(&mut command, &helper);
    configure_bundled_models_env(&mut command, app, &helper);
    if let Some(path) = helper.python_path {
        command.env("PYTHONPATH", path);
    }
    if let Some(path) = helper.workdir {
        command.current_dir(path);
    }
    let output = command
        .output()
        .map_err(|error| format!("failed to run helper: {error}"))?;
    Ok(HelperResult {
        ok: output.status.success(),
        code: output.status.code(),
        stdout: String::from_utf8_lossy(&output.stdout).into_owned(),
        stderr: String::from_utf8_lossy(&output.stderr).into_owned(),
        cancelled: false,
    })
}

fn emit_model_progress(app: &tauri::AppHandle, progress: ModelOperationProgress) {
    if let Ok(mut inner) = app.state::<ModelOperationState>().0.lock() {
        inner.latest = Some(progress.clone());
    }
    let _ = app.emit("model-operation-progress", progress);
}

fn parse_model_progress(line: &str) -> Option<ModelOperationProgress> {
    let start = line.find(MODEL_PROGRESS_PREFIX)? + MODEL_PROGRESS_PREFIX.len();
    serde_json::from_str(line[start..].trim()).ok()
}

fn model_operation_id() -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_nanos())
        .unwrap_or(0);
    format!("{}-{nanos}", std::process::id())
}

fn initial_model_progress(
    id: &str,
    kind: &str,
    action: &str,
    model: &str,
) -> ModelOperationProgress {
    ModelOperationProgress {
        schema: 1,
        id: id.into(),
        kind: kind.into(),
        action: action.into(),
        model: model.into(),
        phase: "preparing".into(),
        component: None,
        downloaded_bytes: 0,
        total_bytes: None,
        percent: None,
        cancellable: true,
        updated_at: unix_timestamp(),
    }
}

fn terminal_model_progress(
    app: &tauri::AppHandle,
    id: &str,
    kind: &str,
    action: &str,
    model: &str,
    phase: &str,
) -> ModelOperationProgress {
    let latest = app
        .state::<ModelOperationState>()
        .0
        .lock()
        .ok()
        .and_then(|inner| inner.latest.clone())
        .filter(|progress| progress.id == id);
    let mut progress = latest.unwrap_or_else(|| initial_model_progress(id, kind, action, model));
    progress.phase = phase.into();
    progress.cancellable = false;
    progress.updated_at = unix_timestamp();
    if phase == "completed" {
        if let Some(total) = progress.total_bytes {
            progress.downloaded_bytes = total;
            progress.percent = Some(100.0);
        }
    }
    progress
}

fn run_managed_model_helper(
    app: tauri::AppHandle,
    args: Vec<String>,
    kind: String,
    action: String,
    model: String,
) -> Result<HelperResult, String> {
    let helper = resolve_helper(Some(&app))?;
    let id = model_operation_id();
    let mut command = Command::new(&helper.program);
    command.args(&helper.prefix_args).args(args);
    configure_macos_service_env(&mut command, &helper);
    configure_bundled_models_env(&mut command, Some(&app), &helper);
    command
        .env("BLE_STT_MODEL_PROGRESS", "1")
        .env("BLE_STT_MODEL_OPERATION_ID", &id)
        .env("BLE_STT_MODEL_KIND", &kind)
        .env("BLE_STT_MODEL_ACTION", &action)
        .env("BLE_STT_MODEL_NAME", &model)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    if let Some(path) = helper.python_path {
        command.env("PYTHONPATH", path);
    }
    if let Some(path) = helper.workdir {
        command.current_dir(path);
    }

    let cancelled = Arc::new(AtomicBool::new(false));
    let child = {
        let state = app.state::<ModelOperationState>();
        let mut inner = state
            .0
            .lock()
            .map_err(|_| "model operation state is unavailable".to_string())?;
        if inner.active.is_some() {
            return Err("another model operation is already running".into());
        }
        let spawned = command
            .spawn()
            .map_err(|error| format!("failed to run helper: {error}"))?;
        let child = Arc::new(Mutex::new(spawned));
        inner.active = Some(ActiveModelOperation {
            id: id.clone(),
            child: Arc::clone(&child),
            cancelled: Arc::clone(&cancelled),
        });
        child
    };
    emit_model_progress(&app, initial_model_progress(&id, &kind, &action, &model));

    let (stdout, stderr) = {
        let mut process = child
            .lock()
            .map_err(|_| "model helper process is unavailable".to_string())?;
        (process.stdout.take(), process.stderr.take())
    };
    let stdout_thread = thread::spawn(move || {
        let mut output = String::new();
        if let Some(mut stream) = stdout {
            let _ = stream.read_to_string(&mut output);
        }
        output
    });
    let progress_app = app.clone();
    let stderr_thread = thread::spawn(move || {
        let mut output = String::new();
        if let Some(stream) = stderr {
            for line in BufReader::new(stream).lines().map_while(Result::ok) {
                if let Some(progress) = parse_model_progress(&line) {
                    emit_model_progress(&progress_app, progress);
                    if let Some(prefix) = line.split(MODEL_PROGRESS_PREFIX).next() {
                        if !prefix.trim().is_empty() {
                            output.push_str(prefix);
                            output.push('\n');
                        }
                    }
                } else {
                    output.push_str(&line);
                    output.push('\n');
                }
            }
        }
        output
    });

    let status = loop {
        let maybe_status = child
            .lock()
            .map_err(|_| "model helper process is unavailable".to_string())?
            .try_wait()
            .map_err(|error| format!("failed to wait for model helper: {error}"))?;
        if let Some(status) = maybe_status {
            break status;
        }
        thread::sleep(Duration::from_millis(100));
    };
    let stdout = stdout_thread.join().unwrap_or_default();
    let stderr = stderr_thread.join().unwrap_or_default();
    if let Ok(mut inner) = app.state::<ModelOperationState>().0.lock() {
        if inner.active.as_ref().map(|active| active.id.as_str()) == Some(id.as_str()) {
            inner.active = None;
        }
    }

    let was_cancelled = cancelled.load(Ordering::SeqCst);
    let phase = if was_cancelled {
        "cancelled"
    } else if status.success() {
        "completed"
    } else {
        "error"
    };
    emit_model_progress(
        &app,
        terminal_model_progress(&app, &id, &kind, &action, &model, phase),
    );
    Ok(HelperResult {
        ok: status.success() && !was_cancelled,
        code: status.code(),
        stdout,
        stderr,
        cancelled: was_cancelled,
    })
}

#[tauri::command]
fn model_operation_status(app: tauri::AppHandle) -> Option<ModelOperationProgress> {
    app.state::<ModelOperationState>()
        .0
        .lock()
        .ok()
        .and_then(|inner| inner.latest.clone())
}

#[tauri::command]
fn cancel_model_operation(app: tauri::AppHandle, id: String) -> Result<(), String> {
    let (child, cancelled, progress) = {
        let state = app.state::<ModelOperationState>();
        let mut inner = state
            .0
            .lock()
            .map_err(|_| "model operation state is unavailable".to_string())?;
        let active = inner
            .active
            .as_ref()
            .filter(|active| active.id == id)
            .ok_or_else(|| "model operation is no longer running".to_string())?;
        if !inner
            .latest
            .as_ref()
            .is_some_and(|progress| progress.id == id && progress.cancellable)
        {
            return Err("model operation can no longer be cancelled".into());
        }
        let child = Arc::clone(&active.child);
        let cancelled = Arc::clone(&active.cancelled);
        let mut progress = inner.latest.clone().expect("checked above");
        progress.phase = "cancelling".into();
        progress.cancellable = false;
        progress.updated_at = unix_timestamp();
        inner.latest = Some(progress.clone());
        (child, cancelled, progress)
    };
    emit_model_progress(&app, progress);
    cancelled.store(true, Ordering::SeqCst);
    let result = child
        .lock()
        .map_err(|_| "model helper process is unavailable".to_string())?
        .kill()
        .map_err(|error| format!("could not cancel model operation: {error}"));
    result
}

fn run_helper_passthrough(args: &[String]) -> Result<i32, String> {
    let helper = resolve_helper(None)?;
    let mut command = Command::new(&helper.program);
    command.args(&helper.prefix_args).args(args);
    configure_macos_service_env(&mut command, &helper);
    configure_bundled_models_env(&mut command, None, &helper);
    if let Some(path) = helper.python_path {
        command.env("PYTHONPATH", path);
    }
    if let Some(path) = helper.workdir {
        command.current_dir(path);
    }
    let status = command
        .status()
        .map_err(|error| format!("failed to run helper: {error}"))?;
    Ok(status.code().unwrap_or(1))
}

#[cfg(target_os = "macos")]
fn configure_macos_service_env(command: &mut Command, helper: &HelperInvocation) {
    command.env("BLE_STT_SERVICE_HELPER", &helper.program);
    if let Ok(runner) = env::current_exe() {
        command.env("BLE_STT_SERVICE_RUNNER", runner);
    }
    if let Some(bundle) = app_bundle_for_executable(&helper.program) {
        command.env("BLE_STT_SERVICE_APP_BUNDLE", bundle);
    }
}

#[cfg(not(target_os = "macos"))]
fn configure_macos_service_env(_command: &mut Command, _helper: &HelperInvocation) {}

fn configure_bundled_models_env(
    command: &mut Command,
    app: Option<&tauri::AppHandle>,
    helper: &HelperInvocation,
) {
    if env::var_os("BLE_STT_BUNDLED_MODELS").is_some() {
        return;
    }
    for path in candidate_bundled_models(app, helper) {
        if path.exists() && path.is_dir() {
            command.env("BLE_STT_BUNDLED_MODELS", path);
            return;
        }
    }
}

fn home_dir() -> PathBuf {
    env::var_os("HOME")
        .or_else(|| env::var_os("USERPROFILE"))
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."))
}

fn telemetry_log_dir() -> PathBuf {
    if cfg!(target_os = "macos") {
        return home_dir().join("Library").join("Logs").join("M5StopWatch");
    }
    if cfg!(target_os = "windows") {
        let base = env::var_os("LOCALAPPDATA")
            .map(PathBuf::from)
            .unwrap_or_else(|| home_dir().join("AppData").join("Local"));
        return base.join("M5StopWatch").join("Logs");
    }
    env::var_os("XDG_STATE_HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| home_dir().join(".local").join("state"))
        .join("m5stopwatch")
}

fn unix_timestamp() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs_f64())
        .unwrap_or(0.0)
}

fn default_telemetry(stage: &str) -> Value {
    json!({
        "schema": TELEMETRY_SCHEMA,
        "stage": stage,
        "session_id": null,
        "audio": {
            "level": 0.0,
            "peak": 0.0,
            "seconds": 0.0,
            "frames": 0
        },
        "recognition": {
            "busy": false,
            "mode": "idle"
        },
        "performance": {
            "revision": 0,
            "current": null,
            "latest": null
        },
        "last_text": null,
        "last_command": null,
        "error": null,
        "updated_at": unix_timestamp(),
        "stale": true,
        "age_seconds": null
    })
}

fn file_modified_timestamp(path: &Path) -> Option<f64> {
    fs::metadata(path)
        .ok()?
        .modified()
        .ok()?
        .duration_since(UNIX_EPOCH)
        .ok()
        .map(|duration| duration.as_secs_f64())
}

fn read_runtime_telemetry() -> Value {
    let path = telemetry_log_dir().join(TELEMETRY_FILE_NAME);
    let now = unix_timestamp();
    let mut payload = fs::read_to_string(&path)
        .ok()
        .and_then(|text| serde_json::from_str::<Value>(&text).ok())
        .filter(Value::is_object)
        .unwrap_or_else(|| default_telemetry("offline"));

    let updated_at = payload
        .get("updated_at")
        .and_then(Value::as_f64)
        .or_else(|| file_modified_timestamp(&path));
    let age = updated_at.map(|timestamp| (now - timestamp).max(0.0));

    if let Some(object) = payload.as_object_mut() {
        object.entry("schema").or_insert(json!(TELEMETRY_SCHEMA));
        object.entry("stage").or_insert(json!("offline"));
        object.entry("session_id").or_insert(Value::Null);
        object.entry("audio").or_insert(json!({
            "level": 0.0,
            "peak": 0.0,
            "seconds": 0.0,
            "frames": 0
        }));
        object.entry("recognition").or_insert(json!({
            "busy": false,
            "mode": "idle"
        }));
        object.entry("performance").or_insert(json!({
            "revision": 0,
            "current": null,
            "latest": null
        }));
        object.entry("last_text").or_insert(Value::Null);
        object.entry("last_command").or_insert(Value::Null);
        object.entry("error").or_insert(Value::Null);
        object.insert(
            "age_seconds".into(),
            age.map(|value| json!((value * 1000.0).round() / 1000.0))
                .unwrap_or(Value::Null),
        );
        object.insert(
            "stale".into(),
            json!(age
                .map(|value| value > TELEMETRY_STALE_SECONDS)
                .unwrap_or(true)),
        );
    }

    payload
}

fn candidate_bundled_models(
    app: Option<&tauri::AppHandle>,
    helper: &HelperInvocation,
) -> Vec<PathBuf> {
    let mut paths = Vec::new();
    if let Some(app) = app {
        if let Ok(path) = app.path().resolve("models", BaseDirectory::Resource) {
            paths.push(path);
        }
        if let Ok(path) = app
            .path()
            .resolve("resources/models", BaseDirectory::Resource)
        {
            paths.push(path);
        }
    }
    if let Ok(exe) = env::current_exe() {
        if let Some(directory) = exe.parent() {
            paths.push(directory.join("models"));
            if let Some(contents) = directory.parent() {
                let resources = contents.join("Resources");
                paths.push(resources.join("models"));
                paths.push(resources.join("resources").join("models"));
            }
        }
    }
    for ancestor in helper.program.ancestors() {
        paths.push(ancestor.join("models"));
        paths.push(ancestor.join("resources").join("models"));
    }
    paths
}

#[cfg(target_os = "macos")]
fn app_bundle_for_executable(executable: &Path) -> Option<PathBuf> {
    for ancestor in executable.ancestors() {
        if ancestor.extension().and_then(OsStr::to_str) == Some("app") {
            return Some(ancestor.to_path_buf());
        }
    }
    None
}

#[tauri::command]
fn helper_status(app: tauri::AppHandle) -> Result<HelperResult, String> {
    run_helper(Some(&app), ["status", "--json"])
}

#[tauri::command]
fn helper_logs(app: tauri::AppHandle, lines: u16) -> Result<HelperResult, String> {
    run_helper(
        Some(&app),
        vec![
            "logs".to_string(),
            "--json".to_string(),
            "--lines".to_string(),
            lines.to_string(),
        ],
    )
}

#[tauri::command]
fn helper_telemetry(_app: tauri::AppHandle) -> Result<HelperResult, String> {
    let stdout = serde_json::to_string(&json!({
        "ok": true,
        "telemetry": read_runtime_telemetry()
    }))
    .map_err(|error| format!("could not encode telemetry: {error}"))?;

    Ok(HelperResult {
        ok: true,
        code: Some(0),
        stdout: format!("{stdout}\n"),
        stderr: String::new(),
        cancelled: false,
    })
}

fn default_performance(revision: u64) -> Value {
    json!({
        "schema": 1,
        "revision": revision,
        "updated_at": unix_timestamp(),
        "sessions": [],
        "lifecycles": []
    })
}

fn read_performance_history() -> Value {
    let path = telemetry_log_dir().join(PERFORMANCE_FILE_NAME);
    fs::read_to_string(path)
        .ok()
        .and_then(|text| serde_json::from_str::<Value>(&text).ok())
        .filter(Value::is_object)
        .unwrap_or_else(|| default_performance(0))
}

#[tauri::command]
fn helper_performance(_app: tauri::AppHandle) -> Result<HelperResult, String> {
    let stdout = serde_json::to_string(&json!({
        "ok": true,
        "performance": read_performance_history()
    }))
    .map_err(|error| format!("could not encode performance history: {error}"))?;
    Ok(HelperResult {
        ok: true,
        code: Some(0),
        stdout: format!("{stdout}\n"),
        stderr: String::new(),
        cancelled: false,
    })
}

#[tauri::command]
fn performance_clear(_app: tauri::AppHandle) -> Result<HelperResult, String> {
    let previous = read_performance_history();
    let revision = previous
        .get("revision")
        .and_then(Value::as_u64)
        .unwrap_or(0)
        + 1;
    let payload = default_performance(revision);
    let destination = telemetry_log_dir().join(PERFORMANCE_FILE_NAME);
    fs::create_dir_all(telemetry_log_dir())
        .map_err(|error| format!("could not create performance directory: {error}"))?;
    let temporary = destination.with_extension("tmp");
    let encoded = serde_json::to_string(&payload)
        .map_err(|error| format!("could not encode empty performance history: {error}"))?;
    fs::write(&temporary, format!("{encoded}\n"))
        .map_err(|error| format!("could not write empty performance history: {error}"))?;
    #[cfg(target_os = "windows")]
    if destination.exists() {
        fs::remove_file(&destination)
            .map_err(|error| format!("could not replace performance history: {error}"))?;
    }
    fs::rename(&temporary, &destination)
        .map_err(|error| format!("could not clear performance history: {error}"))?;
    let stdout = serde_json::to_string(&json!({"ok": true, "performance": payload}))
        .map_err(|error| format!("could not encode cleared performance history: {error}"))?;
    Ok(HelperResult {
        ok: true,
        code: Some(0),
        stdout: format!("{stdout}\n"),
        stderr: String::new(),
        cancelled: false,
    })
}

fn validate_service_action(action: &str) -> Result<(), String> {
    match action {
        "install" | "start" | "stop" | "restart" | "status" | "uninstall" => Ok(()),
        _ => Err(format!("unsupported service action: {action}")),
    }
}

fn validate_model_action(action: &str) -> Result<(), String> {
    match action {
        "status" | "list" | "check-updates" | "use" | "install" | "update" | "repair"
        | "delete" => Ok(()),
        _ => Err(format!("unsupported model action: {action}")),
    }
}

fn validate_mapping_action(action: &str) -> Result<(), String> {
    match action {
        "status" | "save" | "reset" => Ok(()),
        _ => Err(format!("unsupported mapping action: {action}")),
    }
}

fn validate_command_action(action: &str) -> Result<(), String> {
    match action {
        "status" | "save" | "reset" => Ok(()),
        _ => Err(format!("unsupported command action: {action}")),
    }
}

fn validate_correction_model_action(action: &str) -> Result<(), String> {
    match action {
        "use-model" | "install-model" | "update-model" | "repair-model" | "delete-model" => Ok(()),
        _ => Err(format!("unsupported correction model action: {action}")),
    }
}

#[tauri::command]
fn service_action(app: tauri::AppHandle, action: String) -> Result<HelperResult, String> {
    validate_service_action(action.as_str())?;
    run_helper(Some(&app), ["service", action.as_str(), "--json"])
}

#[tauri::command]
async fn model_action(
    app: tauri::AppHandle,
    action: String,
    model: Option<String>,
) -> Result<HelperResult, String> {
    validate_model_action(action.as_str())?;
    let managed = matches!(action.as_str(), "install" | "update" | "repair");
    let mut args = vec!["models".to_string(), action.clone(), "--json".to_string()];
    let operation_model = model.clone();
    match action.as_str() {
        "use" | "install" | "update" | "repair" | "delete" => {
            let model = model.ok_or_else(|| format!("model is required for {action}"))?;
            args.push("--model".to_string());
            args.push(model);
            args.push("--engine".to_string());
            args.push("auto".to_string());
        }
        _ => {}
    }
    tauri::async_runtime::spawn_blocking(move || {
        if managed {
            run_managed_model_helper(
                app,
                args,
                "speech".into(),
                action,
                operation_model.expect("validated model"),
            )
        } else {
            run_helper(Some(&app), args)
        }
    })
    .await
    .map_err(|error| format!("model action failed to join: {error}"))?
}

#[tauri::command]
fn mapping_status(app: tauri::AppHandle) -> Result<HelperResult, String> {
    run_helper(Some(&app), ["mappings", "status", "--json"])
}

#[tauri::command]
fn mapping_save(app: tauri::AppHandle, payload: String) -> Result<HelperResult, String> {
    validate_mapping_action("save")?;
    run_helper(
        Some(&app),
        ["mappings", "save", "--json", "--payload", payload.as_str()],
    )
}

#[tauri::command]
fn mapping_reset(app: tauri::AppHandle) -> Result<HelperResult, String> {
    validate_mapping_action("reset")?;
    run_helper(Some(&app), ["mappings", "reset", "--json"])
}

#[tauri::command]
fn command_status(app: tauri::AppHandle) -> Result<HelperResult, String> {
    run_helper(Some(&app), ["commands", "status", "--json"])
}

#[tauri::command]
fn command_save(app: tauri::AppHandle, payload: String) -> Result<HelperResult, String> {
    validate_command_action("save")?;
    run_helper(
        Some(&app),
        ["commands", "save", "--json", "--payload", payload.as_str()],
    )
}

#[tauri::command]
fn command_reset(app: tauri::AppHandle) -> Result<HelperResult, String> {
    validate_command_action("reset")?;
    run_helper(Some(&app), ["commands", "reset", "--json"])
}

#[tauri::command]
fn voice_settings_save(app: tauri::AppHandle, payload: String) -> Result<HelperResult, String> {
    run_helper(
        Some(&app),
        [
            "voice-settings",
            "save",
            "--json",
            "--payload",
            payload.as_str(),
        ],
    )
}

#[tauri::command]
async fn correction_model_action(
    app: tauri::AppHandle,
    action: String,
    model: Option<String>,
) -> Result<HelperResult, String> {
    validate_correction_model_action(action.as_str())?;
    let model = model.ok_or_else(|| format!("model is required for {action}"))?;
    let managed = matches!(
        action.as_str(),
        "install-model" | "update-model" | "repair-model"
    );
    let progress_action = action.trim_end_matches("-model").to_string();
    tauri::async_runtime::spawn_blocking(move || {
        let args = vec![
            "voice-settings".to_string(),
            action,
            "--json".to_string(),
            "--model".to_string(),
            model.clone(),
        ];
        if managed {
            run_managed_model_helper(app, args, "correction".into(), progress_action, model)
        } else {
            run_helper(Some(&app), args)
        }
    })
    .await
    .map_err(|error| format!("correction model action failed to join: {error}"))?
}

#[tauri::command]
fn open_permission(app: tauri::AppHandle, kind: String) -> Result<HelperResult, String> {
    match kind.as_str() {
        "input" | "bluetooth" => run_helper(
            Some(&app),
            ["permissions", "request", kind.as_str(), "--json"],
        ),
        _ => Err(format!("unsupported permission kind: {kind}")),
    }
}

#[tauri::command]
fn open_logs(app: tauri::AppHandle) -> Result<(), String> {
    let status = run_helper(Some(&app), ["status", "--json"])?;
    let value: serde_json::Value = serde_json::from_str(&status.stdout)
        .map_err(|error| format!("could not parse helper status: {error}"))?;
    let directory = value
        .pointer("/status/logs/directory")
        .and_then(serde_json::Value::as_str)
        .ok_or_else(|| "helper status did not include a log directory".to_string())?;
    open_path(directory)
}

fn open_path(path: &str) -> Result<(), String> {
    let status = if cfg!(target_os = "macos") {
        Command::new("open").arg(path).status()
    } else if cfg!(target_os = "windows") {
        Command::new("explorer").arg(path).status()
    } else {
        Command::new("xdg-open").arg(path).status()
    }
    .map_err(|error| format!("failed to open path: {error}"))?;

    if status.success() {
        Ok(())
    } else {
        Err(format!("open command exited with {status}"))
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    if let Some(args) = helper_cli_args() {
        match run_helper_passthrough(&args) {
            Ok(code) => std::process::exit(code),
            Err(error) => {
                eprintln!("{error}");
                std::process::exit(1);
            }
        }
    }

    let app = tauri::Builder::default()
        .manage(ModelOperationState::default())
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![
            helper_status,
            helper_logs,
            helper_telemetry,
            helper_performance,
            performance_clear,
            service_action,
            model_action,
            mapping_status,
            mapping_save,
            mapping_reset,
            command_status,
            command_save,
            command_reset,
            voice_settings_save,
            correction_model_action,
            model_operation_status,
            cancel_model_operation,
            open_permission,
            open_logs
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application");
    app.run(|handle, event| {
        if matches!(event, tauri::RunEvent::ExitRequested { .. }) {
            if let Ok(inner) = handle.state::<ModelOperationState>().0.lock() {
                if let Some(active) = &inner.active {
                    active.cancelled.store(true, Ordering::SeqCst);
                    if let Ok(mut child) = active.child.lock() {
                        let _ = child.kill();
                    }
                }
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn helper_root_points_at_python_package() {
        assert!(source_helper_root()
            .join("ble_stt")
            .join("__init__.py")
            .exists());
    }

    #[test]
    fn rejects_unknown_service_action() {
        let error = validate_service_action("wipe").unwrap_err();
        assert!(error.contains("unsupported service action"));
    }

    #[test]
    fn rejects_unknown_model_action() {
        let error = validate_model_action("wipe").unwrap_err();
        assert!(error.contains("unsupported model action"));
    }

    #[test]
    fn rejects_unknown_mapping_action() {
        let error = validate_mapping_action("wipe").unwrap_err();
        assert!(error.contains("unsupported mapping action"));
    }

    #[test]
    fn rejects_unknown_command_action() {
        let error = validate_command_action("wipe").unwrap_err();
        assert!(error.contains("unsupported command action"));
    }

    #[test]
    fn rejects_unknown_correction_model_action() {
        let error = validate_correction_model_action("wipe").unwrap_err();
        assert!(error.contains("unsupported correction model action"));
    }

    #[test]
    fn parses_progress_after_terminal_control_text() {
        let line = concat!(
            "downloading 42%\rBLE_STT_MODEL_PROGRESS ",
            r#"{"schema":1,"id":"op-1","kind":"speech","action":"install","model":"medium","phase":"downloading","component":"model","downloaded_bytes":42,"total_bytes":100,"percent":42.0,"cancellable":true,"updated_at":1.0}"#
        );
        let progress = parse_model_progress(line).expect("valid progress");
        assert_eq!(progress.id, "op-1");
        assert_eq!(progress.downloaded_bytes, 42);
        assert!(progress.cancellable);
    }
}
