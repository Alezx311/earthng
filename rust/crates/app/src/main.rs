//! EarthNG.exe: one file that installs the mod and builds map packs (docs/MAPBUILDER_APP.md).
//!
//! A WebView2 window shows the page in app/ui; earthng/app_service.py (Python) does the work and
//! talks JSON lines over stdin/stdout. A release exe carries its runtime (embedded Python, the
//! pipeline, mod/, bin/) as a ZIP appended to itself and unpacks it once per version into
//! %LOCALAPPDATA%\EarthNG\runtime. Run from a checkout's rust/target it uses the checkout instead.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod runtime;
mod tiles;

use std::borrow::Cow;
use std::io::{BufRead, BufReader, Write};
use std::path::{Component, Path, PathBuf};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::{Arc, Mutex};

use anyhow::{Context, Result};
use serde_json::{Value, json};
use tao::event::{Event, WindowEvent};
use tao::event_loop::{ControlFlow, EventLoopBuilder, EventLoopProxy};
use tao::window::{Icon, WindowBuilder};
use wry::http::{Request, Response, header::CONTENT_TYPE};
use wry::{WebContext, WebViewBuilder};

use runtime::Runtime;

pub const VERSION: &str = env!("CARGO_PKG_VERSION");

enum UserEvent {
    /// the runtime is unpacked (or found): load the page and start the service
    Ready(Runtime),
    Failed(String),
    /// a JSON line from the service, or an event of our own
    Message(String),
}

/// %LOCALAPPDATA%\EarthNG: runtime, data, caches and logs of the exe.
pub fn local() -> PathBuf {
    let base = std::env::var_os("LOCALAPPDATA").map(PathBuf::from).unwrap_or_else(std::env::temp_dir);
    base.join("EarthNG")
}

pub fn log(text: &str) {
    let dir = local().join("logs");
    let _ = std::fs::create_dir_all(&dir);
    if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(dir.join("app.log")) {
        let _ = writeln!(f, "{text}");
    }
}

const LOADING: &str = r#"<!doctype html><meta charset="utf-8"><title>EarthNG</title>
<style>html,body{height:100%;margin:0;background:#11161c;color:#d8dee6;font:15px system-ui,sans-serif}
body{display:grid;place-items:center}p{opacity:.7}</style>
<div><h2>EarthNG</h2><p id="m">Розпаковую компоненти (лише перший запуск)…</p></div>"#;

struct Service {
    child: Child,
    stdin: ChildStdin,
}

fn start_service(rt: &Runtime, proxy: EventLoopProxy<UserEvent>) -> Result<Service> {
    let logs = local().join("logs");
    std::fs::create_dir_all(&logs)?;
    let stderr = std::fs::File::create(logs.join("service.log"))?;
    let mut command = Command::new(&rt.python);
    command
        .arg("-X")
        .arg("utf8")
        .arg(rt.code.join("earthng").join("app_service.py"))
        .current_dir(&rt.code)
        .env("PYTHONIOENCODING", "utf-8")
        .env("PYTHONUNBUFFERED", "1")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::from(stderr));
    if let Some(home) = &rt.home {
        std::fs::create_dir_all(home)?;
        command.env("EARTHNG_HOME", home);
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    let mut child = command.spawn().with_context(|| format!("start {}", rt.python.display()))?;
    let stdin = child.stdin.take().context("service stdin")?;
    let stdout = child.stdout.take().context("service stdout")?;
    std::thread::spawn(move || {
        for line in BufReader::new(stdout).lines() {
            match line {
                Ok(line) if !line.trim().is_empty() => {
                    if proxy.send_event(UserEvent::Message(line)).is_err() {
                        return;
                    }
                }
                Ok(_) => {}
                Err(_) => break,
            }
        }
        let _ = proxy.send_event(UserEvent::Message(json!({"event": "service_exit"}).to_string()));
    });
    Ok(Service { child, stdin })
}

fn mime(path: &str) -> &'static str {
    match path.rsplit('.').next().unwrap_or("") {
        "html" => "text/html; charset=utf-8",
        "js" | "mjs" => "text/javascript; charset=utf-8",
        "css" => "text/css; charset=utf-8",
        "json" => "application/json",
        "png" => "image/png",
        "svg" => "image/svg+xml",
        "ico" => "image/x-icon",
        "woff2" => "font/woff2",
        _ => "application/octet-stream",
    }
}

fn respond(status: u16, kind: &str, body: Vec<u8>) -> Response<Cow<'static, [u8]>> {
    Response::builder()
        .status(status)
        .header(CONTENT_TYPE, kind)
        .header("Cache-Control", "no-store")
        .body(Cow::Owned(body))
        .expect("response")
}

/// A file of the page: app/ui/<path>, never outside it.
fn asset(ui: &Path, path: &str) -> Response<Cow<'static, [u8]>> {
    let rel = path.trim_start_matches('/');
    let rel = if rel.is_empty() { "index.html" } else { rel };
    let candidate = Path::new(rel);
    if candidate.components().any(|c| !matches!(c, Component::Normal(_))) {
        return respond(400, "text/plain", b"bad path".to_vec());
    }
    match std::fs::read(ui.join(candidate)) {
        Ok(bytes) => respond(200, mime(rel), bytes),
        Err(_) => respond(404, "text/plain", format!("not found: {rel}").into_bytes()),
    }
}

/// Pages and BeamNG.drive through Steam ("Start BeamNG.drive" after a build); nothing else.
const STEAM_BEAMNG: &str = "steam://rungameid/284160";

fn open_external(url: &str) {
    if url.starts_with("https://") || url == STEAM_BEAMNG {
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            let _ = Command::new("rundll32").args(["url.dll,FileProtocolHandler", url]).creation_flags(0x0800_0000).spawn();
        }
    }
}

fn main() -> Result<()> {
    std::panic::set_hook(Box::new(|info| log(&format!("panic: {info}"))));
    let event_loop = EventLoopBuilder::<UserEvent>::with_user_event().build();
    let proxy = event_loop.create_proxy();
    let icon = Icon::from_rgba(include_bytes!("../icon.rgba").to_vec(), 64, 64)?;
    let window = WindowBuilder::new()
        .with_title("EarthNG — Map Builder")
        .with_window_icon(Some(icon))
        .with_inner_size(tao::dpi::LogicalSize::new(1280.0, 860.0))
        .with_min_inner_size(tao::dpi::LogicalSize::new(960.0, 640.0))
        .build(&event_loop)?;

    let ui_dir: Arc<Mutex<Option<PathBuf>>> = Arc::new(Mutex::new(None));
    let service_in: Arc<Mutex<Option<ChildStdin>>> = Arc::new(Mutex::new(None));
    let mut context = WebContext::new(Some(local().join("webview")));

    let pages = ui_dir.clone();
    let to_service = service_in.clone();
    let ipc_proxy = proxy.clone();
    let webview = WebViewBuilder::new_with_web_context(&mut context)
        .with_html(LOADING)
        .with_asynchronous_custom_protocol("earthng".into(), move |_id, request: Request<Vec<u8>>, responder| {
            let path = request.uri().path().to_string();
            if let Some(rest) = path.strip_prefix("/tile/") {
                let rest = rest.to_string();
                std::thread::spawn(move || {
                    let (status, body) = tiles::serve(&rest);
                    responder.respond(respond(status, if status == 200 { "image/png" } else { "text/plain" }, body));
                });
                return;
            }
            let ui = pages.lock().unwrap().clone();
            match ui {
                Some(ui) => responder.respond(asset(&ui, &path)),
                None => responder.respond(respond(503, "text/plain", b"starting".to_vec())),
            }
        })
        .with_ipc_handler(move |request: Request<String>| {
            let body = request.body();
            let message: Value = serde_json::from_str(body).unwrap_or(Value::Null);
            if message.get("to").and_then(Value::as_str) == Some("app") {
                match message.get("cmd").and_then(Value::as_str) {
                    Some("open_url") => open_external(message.get("url").and_then(Value::as_str).unwrap_or("")),
                    Some("version") => {
                        let answer = json!({"id": message.get("id"), "ok": true, "version": VERSION});
                        let _ = ipc_proxy.send_event(UserEvent::Message(answer.to_string()));
                    }
                    _ => {}
                }
                return;
            }
            let mut guard = to_service.lock().unwrap();
            let sent = guard.as_mut().map(|stdin| writeln!(stdin, "{body}").and_then(|_| stdin.flush()));
            if !matches!(sent, Some(Ok(()))) {
                let answer = json!({"id": message.get("id"), "ok": false, "error": "the service is not running"});
                let _ = ipc_proxy.send_event(UserEvent::Message(answer.to_string()));
            }
        })
        .with_devtools(cfg!(debug_assertions) || std::env::var_os("EARTHNG_DEVTOOLS").is_some())
        .build(&window)?;

    // unpack or find the runtime off the UI thread
    let ready = proxy.clone();
    std::thread::spawn(move || {
        let event = match Runtime::locate() {
            Ok(rt) => UserEvent::Ready(rt),
            Err(e) => UserEvent::Failed(format!("{e:#}")),
        };
        let _ = ready.send_event(event);
    });

    let mut service: Option<Child> = None;
    event_loop.run(move |event, _, control_flow| {
        *control_flow = ControlFlow::Wait;
        match event {
            Event::UserEvent(UserEvent::Ready(rt)) => {
                log(&format!("runtime {} ({})", rt.code.display(), if rt.home.is_some() { "release" } else { "checkout" }));
                *ui_dir.lock().unwrap() = Some(rt.ui.clone());
                match start_service(&rt, proxy.clone()) {
                    Ok(s) => {
                        *service_in.lock().unwrap() = Some(s.stdin);
                        service = Some(s.child);
                    }
                    Err(e) => log(&format!("service: {e:#}")),
                }
                // WebView2 serves custom protocols as http://<scheme>.localhost (wry translates with_url only)
                let _ = webview.load_url("http://earthng.localhost/index.html");
            }
            Event::UserEvent(UserEvent::Failed(error)) => {
                log(&format!("runtime: {error}"));
                let text = serde_json::to_string(&format!("Не вдалося підготувати компоненти: {error}")).unwrap();
                let _ = webview.evaluate_script(&format!("document.getElementById('m').textContent={text}"));
            }
            Event::UserEvent(UserEvent::Message(line)) => {
                let _ = webview.evaluate_script(&format!("window.earthng&&window.earthng.receive({line})"));
            }
            Event::WindowEvent { event: WindowEvent::CloseRequested, .. } => {
                // stdin closed: the service stops its job; the build's own processes end with it
                service_in.lock().unwrap().take();
                if let Some(mut child) = service.take() {
                    for _ in 0..30 {
                        if matches!(child.try_wait(), Ok(Some(_))) {
                            break;
                        }
                        std::thread::sleep(std::time::Duration::from_millis(100));
                    }
                    let _ = child.kill();
                }
                *control_flow = ControlFlow::Exit;
            }
            _ => {}
        }
    });
}
