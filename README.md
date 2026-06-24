# Storage Insight

Storage Insight is a Windows desktop application for disk health monitoring, storage usage analysis, realtime activity tracking, folder-size scanning, and treemap visualization.

## Architecture

- `src/` - React + TypeScript frontend.
- `src-tauri/` - Tauri v2 desktop shell and Rust IPC bridge.
- `backend/` - Python monitoring engine.
- Tauri communicates with the backend over JSON Lines.
- Development uses `.venv\Scripts\python.exe`; production uses the bundled `storage-insight-backend.exe` when available.
- The frontend must run inside Tauri to access backend IPC.

## Requirements

- Windows 10/11
- Node.js 20+
- Python 3.11+
- Rust toolchain with `cargo`
- Microsoft C++ Build Tools with MSVC compiler
- Optional for SMART details: `smartmontools` on `PATH` and administrator privileges

Check installed tools:

```powershell
node --version
npm --version
python --version
rustc --version
cargo --version
```

Install missing tools:

- Node.js: https://nodejs.org/
- Python: https://www.python.org/downloads/windows/
- Rust: install `rustup` from https://rustup.rs/
- MSVC Build Tools: install "Desktop development with C++" from Visual Studio Build Tools.
- Optional SMART: https://www.smartmontools.org/

After installing Rust, close the current terminal and open a new PowerShell window. Then verify:

```powershell
cargo --version
rustc --version
rustup --version
```

If `cargo --version` works in a new PowerShell window but `npm run tauri -- dev` still fails, the app is being started from an old terminal session. Close that terminal, open a fresh one, then run the app again from the project directory.

## First-Time Setup

Run from the project root:

```powershell
npm install
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

If PowerShell blocks venv activation, you do not need to activate it. The Tauri bridge automatically uses:

```powershell
.\.venv\Scripts\python.exe
```

## Run The Desktop App

Use this command for the real application:

```powershell
npm run tauri -- dev
```

This starts:

- Vite frontend
- Tauri desktop window
- Python backend process
- disk detection, monitoring, scanner, alerts, and IPC event streaming

Do not use `npm run dev` for the full app. It opens only the React frontend in a browser, where Tauri IPC is unavailable.

## Frontend-Only Mode

Use only for CSS/layout work:

```powershell
npm run dev
```

In this mode disk detection, folder scanning, monitoring, alerts, and backend calls will not work because the browser cannot access Tauri commands.

## Production Build

Rebuild the bundled backend executable after Python backend changes:

```powershell
cd backend
..\.venv\Scripts\python.exe -m PyInstaller --noconfirm --onefile --noconsole --name storage-insight-backend --distpath dist --workpath build storage_insight_backend\__main__.py
cd ..
Copy-Item -LiteralPath backend\dist\storage-insight-backend.exe -Destination backend\bin\storage-insight-backend.exe -Force
```

Build the frontend and Windows app:

```powershell
npm run build
npm run release:windows
```

The Tauri NSIS installer configuration bundles `backend\bin\storage-insight-backend.exe`, configures the application icon, creates Start Menu/Desktop shortcuts, and embeds the Microsoft Edge WebView2 Evergreen Standalone Installer for clean Windows 10/11 systems.

The generated installer is written to:

```text
src-tauri\target\release\bundle\nsis\Storage Insight_0.1.0_x64-setup.exe
```

### WebView2 Deployment

Storage Insight uses the Tauri NSIS installer, not Inno Setup, WiX, MSI, or MSIX.

WebView2 is configured in `src-tauri\tauri.conf.json`:

```json
"webviewInstallMode": {
  "type": "offlineInstaller",
  "silent": true
},
"minimumWebview2Version": "109.0.1518.0"
```

This makes the installer check for Microsoft Edge WebView2 Runtime and install the Evergreen Runtime silently when it is missing. The offline installer mode increases installer size, but works in Windows Sandbox and offline environments.

Before building a release, run:

```powershell
npm run release:check
```

### Windows Sandbox Verification

1. Open Windows Sandbox.
2. Copy `Storage Insight_0.1.0_x64-setup.exe` and `scripts\check-webview2-runtime.ps1` into the sandbox.
3. Confirm WebView2 is absent or unknown:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check-webview2-runtime.ps1
```

4. Install Storage Insight:

```powershell
.\Storage` Insight_0.1.0_x64-setup.exe /S
```

5. Verify WebView2 was installed:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\check-webview2-runtime.ps1
```

6. Start Storage Insight from the Start Menu or Desktop shortcut. It should open without `Could not find the WebView2 Runtime`.

Alternative deployment modes:

- `downloadBootstrapper`: smallest installer, requires internet during installation.
- `embedBootstrapper`: adds about 2 MB, still requires internet.
- `offlineInstaller`: current choice; larger installer, works without internet.
- `fixedRuntime`: no system installation needed, but adds a large fixed runtime and requires manual security updates.

## Backend Smoke Tests

Compile Python files:

```powershell
python -m compileall backend
```

Run Windows disk detection directly:

```powershell
.\.venv\Scripts\python.exe backend\examples\detect_windows_disks.py
```

Run SMART polling directly:

```powershell
.\.venv\Scripts\python.exe backend\examples\smart_snapshot.py
```

Run realtime disk activity monitoring directly:

```powershell
.\.venv\Scripts\python.exe backend\examples\disk_activity_monitor.py
```

Run the backend IPC process manually:

```powershell
cd backend
..\.venv\Scripts\python.exe -m storage_insight_backend
```

## Troubleshooting

### `Cannot read properties of undefined (reading 'transformCallback')`

The app was opened in a normal browser instead of Tauri. Start it with:

```powershell
npm run tauri -- dev
```

### `Cannot read properties of undefined (reading 'invoke')`

Same cause: Tauri IPC is not available in browser-only mode. Use the desktop command above.

### `event.listen not allowed`

Tauri event permissions are missing or stale. Storage Insight needs:

```json
"permissions": ["core:default", "core:event:default"]
```

This is configured in:

```text
src-tauri/capabilities/default.json
```

After changing Tauri capabilities, restart the dev process:

```powershell
Ctrl+C
npm run tauri -- dev
```

### No drives are detected

Make sure the app is running through Tauri, not Vite-only browser mode. Some WMI/SMART fields may also require administrator privileges.

### SMART values are `unknown`

Storage Insight never fabricates SMART values. If Windows APIs, `pySMART`, or `smartctl` cannot read a device, the backend reports `unknown` with a reason.

For better SMART coverage:

```powershell
smartctl --version
```

If the command is missing, install `smartmontools` and restart the terminal.

### `io error: The pipe is being closed. (os error 232)`

This means the Python backend process is not running anymore. The UI may stay on `connecting` and folder scan will fail with this IPC error.

Common causes:

- the app was started without project dependencies (system `python` instead of `.venv`)
- `backend\requirements.txt` is not installed
- the backend crashed on startup (check `%APPDATA%\Storage Insight\logs\storage-insight-backend.log`)

Fix:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
npm run tauri -- dev
```

If you previously started the app many times during development, stop orphaned backend processes:

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -like '*storage_insight_backend*' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

### Backend dependency errors

Reinstall Python dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

### Rust or Tauri build errors

Verify MSVC and Rust:

```powershell
rustup show
cargo --version
where.exe link
```

Then rerun:

```powershell
npm run tauri -- dev
```

### `failed to run 'cargo metadata'` / `program not found`

Tauri could not find Rust `cargo`.

Install Rust:

```powershell
winget install Rustlang.Rustup
```

Then close PowerShell, open a new PowerShell window, and verify:

```powershell
cargo --version
rustc --version
```

Run Tauri from the same terminal where `cargo --version` works:

```powershell
npm run tauri -- dev
```

For VS Code integrated terminal, close the integrated terminal or reload the VS Code window after installing Rust.

If `cargo` is still missing, add Cargo to `PATH` for the current terminal:

```powershell
$env:Path += ";$env:USERPROFILE\.cargo\bin"
cargo --version
```

Install MSVC Build Tools if Tauri later reports linker or compiler errors:

```powershell
winget install Microsoft.VisualStudio.2022.BuildTools
```

During Visual Studio Build Tools setup, select:

- Desktop development with C++
- MSVC v143 build tools
- Windows 10/11 SDK

### `error: linker 'link.exe' not found`

Rust is installed, but the Microsoft C++ linker is missing. Tauri on Windows needs MSVC Build Tools.

Install Visual Studio Build Tools:

```powershell
winget install --id Microsoft.VisualStudio.2022.BuildTools -e
```

When the installer opens, select:

- Desktop development with C++
- MSVC v143 build tools
- Windows 10/11 SDK

Then restart PowerShell and verify:

```powershell
where.exe link
cargo --version
```

If `where.exe link` still cannot find the linker, open **Developer PowerShell for VS 2022** and run:

```powershell
npm run tauri -- dev
```

If Build Tools is already installed but `VC\Tools\MSVC` is missing, add the C++ workload with Visual Studio Installer:

```powershell
& "C:\Program Files (x86)\Microsoft Visual Studio\Installer\vs_installer.exe" modify --installPath "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools" --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended --passive --norestart
```

For unattended first-time installation, this usually installs the required C++ workload:

```powershell
winget install --id Microsoft.VisualStudio.2022.BuildTools -e --override "--wait --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
```

After workload installation, close PowerShell and either:

- run from **Developer PowerShell for VS 2022**, or
- initialize MSVC tools in the current terminal:

```powershell
cmd /c "`"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat`" && where link"
```

### Visual Studio Installer `SizePreCheckEvaluator` / exit code `-2147024784`

This is Windows error `0x80070070`: not enough disk space. The C++ workload was selected, but Visual Studio Installer stopped before downloading or installing it.

Check free space:

```powershell
Get-PSDrive C
```

Free at least 10-15 GB on `C:`. Then run the workload install again:

```powershell
& "C:\Program Files (x86)\Microsoft Visual Studio\Installer\vs_installer.exe" modify --installPath "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools" --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended --passive --norestart
```

After installation:

```powershell
where.exe link
Test-Path "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Tools\MSVC"
```
