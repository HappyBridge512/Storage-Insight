import { backendClient } from "./backendClient";

type ErrorLevel = "debug" | "info" | "warn" | "error" | "fatal";

export function logFrontendError(
  level: ErrorLevel,
  message: string,
  context?: Record<string, unknown>,
) {
  backendClient.logFrontendError(level, message, context).catch(() => {
    console.error("[frontend-log]", level, message, context);
  });
}

export function installGlobalErrorHandlers() {
  window.addEventListener("error", (event) => {
    logFrontendError("error", event.message || "Unhandled frontend error", {
      filename: event.filename,
      lineno: event.lineno,
      colno: event.colno,
      stack: event.error instanceof Error ? event.error.stack : null,
    });
  });

  window.addEventListener("unhandledrejection", (event) => {
    const reason = event.reason;
    logFrontendError("error", reason instanceof Error ? reason.message : "Unhandled promise rejection", {
      reason: reason instanceof Error ? reason.stack : String(reason),
    });
  });
}
