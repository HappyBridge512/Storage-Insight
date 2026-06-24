import type { AlertInfo } from "../types/backend";

export async function notifyAlert(alert: AlertInfo) {
  if (!("Notification" in window)) return;

  try {
    let permission = Notification.permission;
    if (permission === "default") {
      permission = await Notification.requestPermission();
    }
    if (permission !== "granted") return;

    new Notification(`Storage Insight: ${alert.title}`, {
      body: alert.message,
      tag: alert.fingerprint,
      silent: alert.severity === "info",
    });
  } catch {
    // Notifications are optional; alert events remain visible in the app.
  }
}
