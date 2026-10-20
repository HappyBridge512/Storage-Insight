import { invoke } from "@tauri-apps/api/core";
import { listen, UnlistenFn } from "@tauri-apps/api/event";
import type {
  AlertInfo,
  BackendEvent,
  DiskActivitySnapshot,
  FolderScanResult,
  MonitoringSnapshot,
  SmartMonitorSnapshot,
} from "../types/backend";

type BackendMethod =
  | "config.get"
  | "drives.list"
  | "monitoring.start"
  | "monitoring.stop"
  | "monitoring.snapshot"
  | "activity.start"
  | "activity.stop"
  | "activity.snapshot"
  | "smart.snapshot"
  | "alerts.active"
  | "alerts.history"
  | "scanner.scanFolder"
  | "scanner.start"
  | "scanner.cancel"
  | "scanner.result";

const TAURI_UNAVAILABLE_MESSAGE =
  "Tauri IPC is unavailable. Start the desktop app with `npm run tauri -- dev`; browser-only `npm run dev` cannot access the backend.";

async function request<T>(method: BackendMethod, payload: Record<string, unknown> = {}): Promise<T> {
  ensureTauriRuntime();

  try {
    return await invoke<T>("backend_request", { method, payload });
  } catch (err) {
    void invoke("frontend_log", {
      level: "error",
      message: "Backend request failed",
      context: { method, error: err instanceof Error ? err.message : String(err) },
    }).catch(() => undefined);
    throw normalizeBackendError(err);
  }
}

async function invokeDesktopCommand<T>(command: string, payload: Record<string, unknown> = {}): Promise<T> {
  ensureTauriRuntime();

  try {
    return await invoke<T>(command, payload);
  } catch (err) {
    throw normalizeBackendError(err);
  }
}

function ensureTauriRuntime() {
  if (!isTauriRuntime()) {
    throw new Error(TAURI_UNAVAILABLE_MESSAGE);
  }
}

function isTauriRuntime() {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

function normalizeBackendError(err: unknown) {
  const message = err instanceof Error ? err.message : String(err);
  if (message.includes("transformCallback") || message.includes("invoke")) {
    return new Error(TAURI_UNAVAILABLE_MESSAGE);
  }
  if (
    message.includes("pipe is being closed") ||
    message.includes("os error 232") ||
    message.includes("backend process is not available") ||
    message.includes("backend process exited")
  ) {
    return new Error(
      "Python backend is unavailable or stopped unexpectedly. Restart Storage Insight and verify `.venv` dependencies from `backend\\requirements.txt`.",
    );
  }
  if (
    message.includes("backend runtime check failed") ||
    message.includes("python runtime check failed") ||
    message.includes("could not import storage_insight_backend")
  ) {
    return new Error(
      "Storage Insight backend is not available. For development, run `python -m venv .venv` and install `backend\\requirements.txt`; for release, build the bundled backend executable.",
    );
  }
  return err instanceof Error ? err : new Error(message);
}

export const backendClient = {
  getConfig: () => request<Record<string, unknown>>("config.get"),
  listDrives: () => request<Pick<MonitoringSnapshot, "drives">>("drives.list"),
  startMonitoring: () => request<{ status: string }>("monitoring.start"),
  stopMonitoring: () => request<{ status: string }>("monitoring.stop"),
  snapshot: () => request<MonitoringSnapshot>("monitoring.snapshot"),
  startActivity: () => request<{ status: string }>("activity.start"),
  stopActivity: () => request<{ status: string }>("activity.stop"),
  activitySnapshot: (force = false) => request<DiskActivitySnapshot>("activity.snapshot", { force }),
  smartSnapshot: (force = false) => request<SmartMonitorSnapshot>("smart.snapshot", { force }),
  activeAlerts: () => request<{ alerts: AlertInfo[] }>("alerts.active"),
  alertHistory: (limit = 100, includeResolved = true) =>
    request<{ alerts: AlertInfo[] }>("alerts.history", { limit, includeResolved }),
  scanFolder: (path: string, maxDepth = 12) =>
    request<FolderScanResult>("scanner.scanFolder", { path, maxDepth }),
  startFolderScan: (path: string, maxDepth = 12) =>
    request<{ scan_id: string; path: string; status: string }>("scanner.start", { path, maxDepth }),
  cancelFolderScan: (scanId?: string) =>
    request<{ status: string; scan_ids: string[] }>("scanner.cancel", scanId ? { scanId } : {}),
  folderScanResult: (scanId: string) => request<FolderScanResult>("scanner.result", { scanId }),
  openFolder: (path: string) => invokeDesktopCommand<void>("open_folder_in_explorer", { path }),
  logFrontendError: (level: string, message: string, context?: Record<string, unknown>) =>
    invokeDesktopCommand<void>("frontend_log", { level, message, context: context ?? null }),
  listen: (handler: (event: BackendEvent) => void): Promise<UnlistenFn> => {
    if (!isTauriRuntime()) {
      return Promise.resolve(() => undefined);
    }
    return listen<BackendEvent>("backend-event", (message) => handler(message.payload)).catch((err) => {
      throw normalizeBackendError(err);
    });
  },
};
