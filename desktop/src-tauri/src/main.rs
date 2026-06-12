// Surfing AI Desktop — Tauri shell.
//
// The shell does exactly three things:
//   1. pick a free localhost port + random token
//   2. spawn the Python bridge sidecar:
//        python3 scripts/surfing_ai desktop --port P --token T --root W
//   3. open a window at http://127.0.0.1:P/?token=T
//
// Everything else (sessions, allowlist, file guard, redaction,
// approvals, audit) lives in the Python harness. The shell adds no
// authority and the bridge binds 127.0.0.1 only.
//
// Root resolution (where the Python code lives):
//   1. $SURFING_AI_ROOT                  — explicit override
//   2. the app bundle's resource dir     — installed app (resources
//      include harness/, scripts/, desktop/ui/)
//   3. ../../ from this manifest         — dev checkout
//
// Working dir (where sessions run and audit logs go):
//   installed app -> ~/SurfingAI (created on first launch)
//   dev checkout  -> the checkout itself

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::Read;
use std::net::TcpListener;
use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Mutex;

use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};

struct Sidecar(Mutex<Option<Child>>);

fn free_port() -> u16 {
    TcpListener::bind("127.0.0.1:0")
        .expect("no free localhost port")
        .local_addr()
        .unwrap()
        .port()
}

fn random_token() -> String {
    let mut bytes = [0u8; 16];
    if let Ok(mut urandom) = std::fs::File::open("/dev/urandom") {
        let _ = urandom.read_exact(&mut bytes);
    } else {
        // non-unix fallback: time + pid (localhost-only token)
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let pid = std::process::id() as u128;
        let mix = now ^ (pid << 64) ^ 0x9e37_79b9_7f4a_7c15u128;
        bytes.copy_from_slice(&mix.to_le_bytes());
    }
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

fn python_binary() -> &'static str {
    if cfg!(windows) {
        "python"
    } else {
        "python3"
    }
}

fn home_dir() -> PathBuf {
    std::env::var("HOME")
        .or_else(|_| std::env::var("USERPROFILE"))
        .map(PathBuf::from)
        .unwrap_or_else(|_| std::env::temp_dir())
}

/// (code_root, workdir)
fn resolve_dirs(app: &tauri::AppHandle) -> (PathBuf, PathBuf) {
    if let Ok(root) = std::env::var("SURFING_AI_ROOT") {
        let root = PathBuf::from(root);
        return (root.clone(), root);
    }
    if let Ok(resources) = app.path().resource_dir() {
        if resources.join("scripts").join("surfing_ai").exists() {
            return (resources, home_dir().join("SurfingAI"));
        }
    }
    let dev = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let dev = dev.canonicalize().unwrap_or(dev);
    (dev.clone(), dev)
}

fn main() {
    let port = free_port();
    let token = random_token();
    let url = format!("http://127.0.0.1:{port}/?token={token}");

    tauri::Builder::default()
        .manage(Sidecar(Mutex::new(None)))
        .setup(move |app| {
            let (root, workdir) = resolve_dirs(app.handle());
            std::fs::create_dir_all(&workdir).ok();

            let child = Command::new(python_binary())
                .arg(root.join("scripts").join("surfing_ai"))
                .arg("desktop")
                .args(["--port", &port.to_string()])
                .args(["--token", &token])
                .args(["--root", &workdir.to_string_lossy()])
                .current_dir(&root)
                .spawn()
                .expect("could not start the Python bridge — \
                         Surfing AI Desktop requires python3 on PATH");
            *app.state::<Sidecar>().0.lock().unwrap() = Some(child);

            // give the bridge a moment to bind before first load
            std::thread::sleep(std::time::Duration::from_millis(700));
            WebviewWindowBuilder::new(
                app,
                "main",
                WebviewUrl::External(url.parse().unwrap()),
            )
            .title("Surfing AI — Private Desktop")
            .inner_size(1280.0, 820.0)
            .min_inner_size(900.0, 600.0)
            .build()?;
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                if let Some(state) = app.try_state::<Sidecar>() {
                    if let Some(mut child) = state.0.lock().unwrap().take() {
                        let _ = child.kill();
                        let _ = child.wait();
                    }
                }
            }
        });
}
