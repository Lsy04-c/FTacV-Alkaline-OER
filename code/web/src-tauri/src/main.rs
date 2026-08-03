// OER 工作台 — Tauri 外壳。
//
// 这个壳本身不做任何科学计算：启动时把课题组已有的 Python/FastAPI 后端
// （backend/main.py）当子进程拉起来，等 127.0.0.1:7100 端口就绪后再显示
// 窗口（避免用户看到一瞬间的"连接失败"页面），退出时把子进程杀掉。
//
// 这是第一版、偏保守的实现：假定目标机器上已经装好了课题组统一的 Python
// 环境（这在需求文档 2.4 节里是被接受的："组内分发可接受固定 Python 环境
// 或 sidecar"）。更彻底的做法是用 PyInstaller 把 backend + oer_aem 打成一个
// 不依赖用户机器 Python 的独立二进制，再通过 Tauri 的 sidecar/externalBin
// 机制接入——这个留到你们决定"要不要给非组内的人用"之后再做，工作量明显更大。
//
// 配置读取优先级（第一个存在的生效）：
//   1. 环境变量 OER_PYTHON / OER_REPO_ROOT / OER_PYTHON_SRC
//   2. 配置文件 ~/.oer-workbench.json，形如：
//        { "python": "/Users/you/OER-FTAcV/.venv/bin/python",
//          "repo_root": "/Users/you/OER-FTAcV" }
//   3. 默认值：python3 / 当前工作目录
//
// 之所以需要配置文件：这是双击启动的桌面 app，Finder 双击不会带上你在
// Terminal 里 export 的环境变量，也不会把「当前工作目录」设成仓库路径——
// 只用环境变量的话，双击启动这条路径实际上永远不会生效。

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::TcpStream;
use std::path::PathBuf;
use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use serde::Deserialize;
use tauri::Manager;

#[derive(Deserialize, Default)]
struct FileConfig {
    python: Option<String>,
    repo_root: Option<String>,
    python_src: Option<String>,
}

fn read_config_file() -> FileConfig {
    let path = dirs_home().map(|h| h.join(".oer-workbench.json"));
    match path.and_then(|p| std::fs::read_to_string(p).ok()) {
        Some(text) => serde_json::from_str(&text).unwrap_or_default(),
        None => FileConfig::default(),
    }
}

fn dirs_home() -> Option<PathBuf> {
    std::env::var_os("HOME")
        .or_else(|| std::env::var_os("USERPROFILE"))
        .map(PathBuf::from)
}

const BACKEND_PORT: u16 = 7100;
const BACKEND_READY_TIMEOUT: Duration = Duration::from_secs(20);

struct BackendHandle(Mutex<Option<Child>>);

fn wait_for_port(port: u16, timeout: Duration) -> bool {
    let start = Instant::now();
    while start.elapsed() < timeout {
        if TcpStream::connect(("127.0.0.1", port)).is_ok() {
            return true;
        }
        std::thread::sleep(Duration::from_millis(150));
    }
    false
}

/// 仓库根目录：env var > 配置文件 > 当前工作目录（最后这个兜底基本只在
/// `cargo tauri dev` 时有意义；双击打包好的 .app 时几乎一定要靠前两者之一）。
fn repo_root(cfg: &FileConfig) -> PathBuf {
    if let Ok(v) = std::env::var("OER_REPO_ROOT") {
        return PathBuf::from(v);
    }
    if let Some(v) = &cfg.repo_root {
        return PathBuf::from(v);
    }
    std::env::current_dir().expect("无法获取当前工作目录")
}

fn python_bin(cfg: &FileConfig) -> String {
    std::env::var("OER_PYTHON")
        .ok()
        .or_else(|| cfg.python.clone())
        .unwrap_or_else(|| "python3".into())
}

fn python_src(cfg: &FileConfig, root: &PathBuf) -> String {
    std::env::var("OER_PYTHON_SRC").ok().or_else(|| cfg.python_src.clone()).unwrap_or_else(|| {
        root.join("code/python/src").to_string_lossy().to_string()
    })
}

fn spawn_backend() -> std::io::Result<Child> {
    let cfg = read_config_file();
    let python = python_bin(&cfg);
    let root = repo_root(&cfg);
    let py_src = python_src(&cfg, &root);
    let web_dir = root.join("code/web");

    eprintln!(
        "[oer-workbench] 启动后端: {python} -m uvicorn backend.main:app  (cwd={:?}, PYTHONPATH={py_src})",
        web_dir
    );

    Command::new(python)
        .args([
            "-m",
            "uvicorn",
            "backend.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            &BACKEND_PORT.to_string(),
        ])
        .current_dir(&web_dir)
        .env("PYTHONPATH", py_src)
        .spawn()
}

fn main() {
    let backend_child = match spawn_backend() {
        Ok(c) => Some(c),
        Err(e) => {
            eprintln!(
                "[oer-workbench] 无法启动 Python 后端：{e}\n\
                 请检查 OER_PYTHON / OER_REPO_ROOT / OER_PYTHON_SRC 是否正确，\
                 或先手动运行 code/web/start.sh 确认后端能单独跑起来。"
            );
            None
        }
    };

    tauri::Builder::default()
        .manage(BackendHandle(Mutex::new(backend_child)))
        .setup(|app| {
            let ready = wait_for_port(BACKEND_PORT, BACKEND_READY_TIMEOUT);
            if !ready {
                eprintln!(
                    "[oer-workbench] 等待后端 {BACKEND_PORT} 端口超时（{}s），\
                     仍会显示窗口，但页面可能是连接失败，需要检查 Python 环境。",
                    BACKEND_READY_TIMEOUT.as_secs()
                );
            }
            // tauri.conf.json 里 windows[0].visible 设成了 false，就是为了等到这里
            // 确认后端就绪（或至少等够超时时间）以后再显示，避免用户看到一闪而过的
            // 连接失败页面。
            if let Some(win) = app.get_window("main") {
                let _ = win.show();
                let _ = win.set_focus();
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("Tauri 应用构建失败")
        .run(|app_handle, event| {
            if let tauri::RunEvent::Exit = event {
                let state: tauri::State<BackendHandle> = app_handle.state();
                let mut guard = state.0.lock().unwrap();
                if let Some(mut child) = guard.take() {
                    eprintln!("[oer-workbench] 退出，关闭后端子进程");
                    let _ = child.kill();
                }
            }
        });
}
