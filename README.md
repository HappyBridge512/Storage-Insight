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
