import { AlertTriangle, Bell, CheckCircle2, Info } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { backendClient } from "../../services/backendClient";
import type { AlertInfo, BackendEvent } from "../../types/backend";

export function AlertsPanel({
  alerts,
  events,
}: {
  alerts: AlertInfo[];
  events: BackendEvent[];
}) {
  const [history, setHistory] = useState<AlertInfo[]>([]);
  const latestAlertEvent = useMemo(() => events.find((event) => event.event.startsWith("alerts.")), [events]);

  useEffect(() => {
    let mounted = true;
    backendClient
      .alertHistory(12, true)
      .then((response) => {
        if (mounted) setHistory(response.alerts);
      })
      .catch(() => undefined);

    return () => {
      mounted = false;
    };
  }, [latestAlertEvent?.event, (latestAlertEvent?.payload as AlertInfo | undefined)?.id]);

  return (
    <aside className="panel alerts-panel">
      <div className="panel-heading">
        <h2>Alerts</h2>
        <Bell size={18} />
      </div>

      <div className="alert-stack">
        {alerts.length > 0 ? (
          alerts.map((alert) => <AlertRow key={alert.id} alert={alert} />)
        ) : (
          <div className="alert-empty">
            <CheckCircle2 size={18} />
            <span>No active alerts</span>
          </div>
        )}
      </div>

      <div className="history-block">
        <h3>Recent history</h3>
        <div className="history-list">
          {history.slice(0, 6).map((alert) => (
            <div className="history-row" key={`${alert.id}-${alert.last_seen_at}`}>
              <span className={`severity-dot ${alert.severity}`} />
              <strong>{alert.title}</strong>
              <span>{formatTime(alert.last_seen_at)}</span>
            </div>
          ))}
          {history.length === 0 ? <p className="muted">No alert history yet.</p> : null}
        </div>
      </div>
    </aside>
  );
}

function AlertRow({ alert }: { alert: AlertInfo }) {
  const Icon = alert.severity === "info" ? Info : AlertTriangle;

  return (
    <article className={`alert-card ${alert.severity}`}>
      <Icon size={18} />
      <div>
        <strong>{alert.title}</strong>
        <p>{alert.message}</p>
        <span>{[alert.source, alert.drive_id ?? alert.disk_name, formatTime(alert.last_seen_at)].filter(Boolean).join(" / ")}</span>
      </div>
    </article>
  );
}

function formatTime(timestampSeconds: number) {
  return new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(timestampSeconds * 1000));
}
