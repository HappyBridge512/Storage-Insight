import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { backendClient } from "../../services/backendClient";
import { notifyAlert } from "../../services/notificationService";
import type { AlertInfo, BackendEvent, MonitoringSnapshot } from "../../types/backend";

interface BackendState {
  snapshot: MonitoringSnapshot | null;
  events: BackendEvent[];
  status: "connecting" | "online" | "offline" | "error";
  error: string | null;
  refresh: () => Promise<void>;
}

const BackendContext = createContext<BackendState | null>(null);
const CONNECT_TIMEOUT_MS = 45_000;

function withTimeout<T>(promise: Promise<T>, timeoutMs: number, label: string): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => {
      reject(new Error(`${label} timed out after ${Math.round(timeoutMs / 1000)}s`));
    }, timeoutMs);

    promise
      .then((value) => {
        window.clearTimeout(timer);
        resolve(value);
      })
      .catch((error) => {
        window.clearTimeout(timer);
        reject(error);
      });
  });
}

export function BackendProvider({ children }: { children: ReactNode }) {
  const [snapshot, setSnapshot] = useState<MonitoringSnapshot | null>(null);
  const [events, setEvents] = useState<BackendEvent[]>([]);
  const [status, setStatus] = useState<BackendState["status"]>("connecting");
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const next = await backendClient.snapshot();
    setSnapshot(next);
    setError(null);
    setStatus("online");
  }, []);

  useEffect(() => {
    let mounted = true;
    let unlisten: (() => void) | undefined;

    async function connect() {
      try {
        unlisten = await backendClient.listen((event) => {
          if (!mounted) return;

          setEvents((current) => [event, ...current].slice(0, 30));

          if (event.event === "monitoring.snapshot") {
            setSnapshot(event.payload as MonitoringSnapshot);
            setStatus("online");
            setError(null);
          }

          if (event.event === "alerts.raised") {
            notifyAlert(event.payload as AlertInfo);
          }

          if (event.event === "backend.exited") {
            setStatus("offline");
            setError("Python backend stopped unexpectedly. Restart Storage Insight to reconnect.");
          }

          if (event.event === "backend.stderr") {
            const line = String((event.payload as { line?: string }).line ?? "");
            if (line.includes("Traceback") || line.includes("ModuleNotFoundError")) {
              setError(line);
            }
          }
        });

        await withTimeout(backendClient.startMonitoring(), CONNECT_TIMEOUT_MS, "Backend start");
        await withTimeout(refresh(), CONNECT_TIMEOUT_MS, "Backend snapshot");
        if (mounted) setStatus("online");
      } catch (err) {
        if (mounted) {
          setStatus("error");
          setError(err instanceof Error ? err.message : String(err));
        }
      }
    }

    connect();

    return () => {
      mounted = false;
      unlisten?.();
      backendClient.stopMonitoring().catch(() => undefined);
    };
  }, [refresh]);

  const value = useMemo<BackendState>(
    () => ({ snapshot, events, status, error, refresh }),
    [snapshot, events, status, error, refresh],
  );

  return <BackendContext.Provider value={value}>{children}</BackendContext.Provider>;
}

export function useBackend() {
  const value = useContext(BackendContext);
  if (!value) {
    throw new Error("useBackend must be used inside BackendProvider");
  }
  return value;
}
