# Storage Insight

Storage Insight is a Windows desktop application for:

* Disk health monitoring
* Storage usage analysis
* Realtime disk activity tracking
* Folder size scanning
* Treemap visualization

## Tech Stack

* Frontend: React + TypeScript
* Desktop: Tauri v2
* Backend: Python
* Communication: JSON Lines IPC

## Requirements

* Windows 10/11
* Node.js 20+
* Python 3.11+
* Rust + Cargo
* MSVC Build Tools

## Installation

```bash
npm install

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

## Development

```bash
npm run tauri -- dev
```

> Do not use `npm run dev` for full functionality. It launches only the frontend without Tauri IPC.

## Rebuilding the Python Backend

Rebuild the packed backend after changing anything under `backend/storage_insight_backend/`. Python source changes do not update the already-built [backend/bin/storage-insight-backend.exe](./backend/bin/storage-insight-backend.exe) automatically.

Prerequisites: Windows, the project virtual environment, and PyInstaller installed in that environment (it is installed by the backend development dependencies).

From the project root:

```powershell
Set-Location D:\ww\memory_monitor\backend
..\.venv\Scripts\python.exe -m PyInstaller --noconfirm storage-insight-backend.spec

Set-Location D:\ww\memory_monitor
Copy-Item -LiteralPath backend\dist\storage-insight-backend.exe `
  -Destination backend\bin\storage-insight-backend.exe -Force
```

Only copy the file after PyInstaller reports `Build complete!`. Confirm that the release copy is non-empty and matches the build artifact:

```powershell
Get-Item backend\dist\storage-insight-backend.exe, backend\bin\storage-insight-backend.exe |
  Select-Object FullName, Length, LastWriteTime
Get-FileHash backend\dist\storage-insight-backend.exe, backend\bin\storage-insight-backend.exe
```

Smoke-test JSONL IPC with the packed executable. The script ignores event messages and waits for the matching request id:

```powershell
$exe = (Resolve-Path backend\bin\storage-insight-backend.exe).Path
$process = [System.Diagnostics.Process]::new()
$process.StartInfo.FileName = $exe
$process.StartInfo.UseShellExecute = $false
$process.StartInfo.RedirectStandardInput = $true
$process.StartInfo.RedirectStandardOutput = $true
$process.StartInfo.RedirectStandardError = $true
[void]$process.Start()

function Read-Response([string]$id) {
  do {
    $line = $process.StandardOutput.ReadLine()
    if ($null -eq $line) { throw "Backend stdout closed before response $id" }
    $message = $line | ConvertFrom-Json
  } while ($message.id -ne $id)
  $message
}

$process.StandardInput.WriteLine('{"id":"1","method":"smart.snapshot","payload":{"force":true}}')
$process.StandardInput.Flush()
Read-Response '1'
$process.StandardInput.WriteLine('{"id":"2","method":"shutdown","payload":{}}')
$process.StandardInput.Flush()
Read-Response '2'
$process.WaitForExit(10000)
$process.StandardError.ReadToEnd()
$process.ExitCode
```

The two responses should have `ok: true`, stderr should be empty, and the exit code should be `0`. SMART can legitimately be unavailable in a VM, Windows Sandbox, or behind unsupported controllers; a structured `smart.snapshot` response is still a successful IPC test.

Then run the desktop application:

```powershell
npm run tauri -- dev
```

If the backend does not start, first inspect the backend stderr event/log and verify the executable timestamp and hash above. The backend needs `console=True` in [storage-insight-backend.spec](./backend/storage-insight-backend.spec): it communicates through stdin/stdout JSONL. Do **not** use `console=False` or `--noconsole`. Rust applies `CREATE_NO_WINDOW` when launching the backend, so the application hides its console window without breaking IPC.

## Production Build

```bash
npm run build
npm run release:windows
```

Installer output:

```text
src-tauri/target/release/bundle/nsis/
```

## Features

* Drive detection
* SMART monitoring
* Realtime activity tracking
* Folder scanning
* Treemap visualization
* Desktop notifications
* Tauri IPC integration
