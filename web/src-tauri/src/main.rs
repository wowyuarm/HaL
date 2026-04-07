use std::net::{SocketAddr, TcpStream};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};

use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};

const HAL_HOST: &str = "127.0.0.1";
const HAL_DEV_PORT: u16 = 3000;
const HAL_PORT: u16 = 8765;
const HAL_START_TIMEOUT_SECS: u64 = 15;
const HAL_POLL_INTERVAL_MS: u64 = 250;

struct HalProcess(Mutex<Option<Child>>);

fn main() {
    let app = tauri::Builder::default()
        .setup(|app| {
            let child = if cfg!(debug_assertions) {
                None
            } else {
                let child = if is_hal_available() {
                    None
                } else {
                    Some(start_hal_process()?)
                };

                if !wait_for_hal_server(Duration::from_secs(HAL_START_TIMEOUT_SECS)) {
                    return Err(format!(
                        "HaL web runtime did not start at {}:{} within {} seconds.",
                        HAL_HOST, HAL_PORT, HAL_START_TIMEOUT_SECS
                    )
                    .into());
                }

                child
            };

            app.manage(HalProcess(Mutex::new(child)));

            let url = app_url();
            WebviewWindowBuilder::new(app, "main", WebviewUrl::External(url.parse()?))
                .title("HaL")
                .inner_size(1440.0, 960.0)
                .min_inner_size(1080.0, 720.0)
                .build()?;

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build HaL desktop app");

    app.run(|app_handle, event| {
        if let tauri::RunEvent::Exit = event {
            stop_hal_process(app_handle);
        }
    });
}

fn app_url() -> String {
    if cfg!(debug_assertions) {
        format!("http://{}:{}", HAL_HOST, HAL_DEV_PORT)
    } else {
        hal_url()
    }
}

fn hal_url() -> String {
    format!("http://{}:{}", HAL_HOST, HAL_PORT)
}

fn hal_socket_addr() -> SocketAddr {
    format!("{}:{}", HAL_HOST, HAL_PORT)
        .parse()
        .expect("valid HaL socket address")
}

fn is_hal_available() -> bool {
    TcpStream::connect_timeout(&hal_socket_addr(), Duration::from_millis(250)).is_ok()
}

fn wait_for_hal_server(timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if is_hal_available() {
            return true;
        }
        thread::sleep(Duration::from_millis(HAL_POLL_INTERVAL_MS));
    }
    false
}

fn start_hal_process() -> Result<Child, Box<dyn std::error::Error>> {
    let child = Command::new("hal")
        .args(["web", "--host", HAL_HOST, "--port", &HAL_PORT.to_string()])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()?;
    Ok(child)
}

fn stop_hal_process(app_handle: &tauri::AppHandle) {
    if let Some(process) = app_handle.try_state::<HalProcess>() {
        if let Ok(mut guard) = process.0.lock() {
            if let Some(mut child) = guard.take() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    }
}
