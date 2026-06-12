// Surfing AI Desktop — Tauri shell.
//
// The shell does exactly three things:
//   1. pick a free localhost port + random token
//   2. spawn the Python bridge sidecar:
//        python3 scripts/surfing_ai desktop --port P --token T
//   3. open a window at http://127.0.0.1:P/?token=T
//
// Everything else (sessions, allowlist, file guard, redaction,
// approvals, audit) lives in the Python harness. The shell adds no
// authority and the bridge binds 127.0.0.1 only.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::Read;
use std::net::TcpListener;
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

fn repo_root() -> std::path::PathBuf {
    // SURFING_AI_ROOT wins (installed app); otherwise the dev checkout
    // layout desktop/src-tauri/ -> ../../
    if let Ok(root) = std::env::var("SURFING_AI_ROOT") {
        return root.into();
    }
    std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .canonicalize()
        .expect("repo root not found; set SURFING_AI_ROOT")
}

fn main() {
    let port = free_port();
    let token = random_token();
    let root = repo_root();

    let child = Command::new("python3")
        .arg("scripts/surfing_ai")
        .arg("desktop")
        .args(["--port", &port.to_string()])
        .args(["--token", &token])
        .current_dir(&root)
        .spawn()
        .expect("could not start python3 bridge — is python3 on PATH?");

    let url = format!("http://127.0.0.1:{port}/?token={token}");

    tauri::Builder::default()
        .manage(Sidecar(Mutex::new(Some(child))))
        .setup(move |app| {
            // give the bridge a moment to bind before first load
            std::thread::sleep(std::time::Duration::from_millis(600));
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
