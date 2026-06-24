import { Activity, AlertTriangle, Database, FolderSearch, RefreshCw } from "lucide-react";
import { useMemo, useState } from "react";
import { AlertsPanel } from "../components/alerts/AlertsPanel";
import { DriveCard } from "../components/drives/DriveCard";
import { ActivityPanel } from "../components/monitoring/ActivityPanel";
import { FolderScannerPanel } from "../components/scanner/FolderScannerPanel";
import { formatBytes } from "../utils/format";
import { useBackend } from "./providers/BackendProvider";

export function App() {
  const { snapshot, events, status, error, refresh } = useBackend();
  const [isRefreshing, setRefreshing] = useState(false);

  const capacity = useMemo(() => {
    const drives = snapshot?.drives ?? [];
    const total = drives.reduce((sum, drive) => sum + drive.total_bytes, 0);
    const free = drives.reduce((sum, drive) => sum + drive.free_bytes, 0);
    return { total, free, used: total - free };
  }, [snapshot]);

  const usedPercent = capacity.total > 0 ? (capacity.used / capacity.total) * 100 : 0;
  const alertCount = snapshot?.alerts.length ?? 0;
  const driveCount = snapshot?.drives.length ?? 0;

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      await refresh();
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">
            <Database size={19} />
          </div>
          <div>
            <strong>Storage Insight</strong>
            <span className={`backend-state ${status}`}>
              <i />
              {status}
            </span>
          </div>
        </div>

        <nav className="nav-list" aria-label="Primary">
          <a href="#overview" className="nav-item active">
            <Activity size={17} /> Overview
          </a>
          <a href="#scanner" className="nav-item">
            <FolderSearch size={17} /> Scanner
          </a>
        </nav>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">Windows storage monitoring</p>
            <h1>Storage overview</h1>
          </div>
          <button className="icon-button" onClick={handleRefresh} aria-label="Refresh snapshot">
            <RefreshCw size={17} className={isRefreshing ? "spin" : ""} />
          </button>
        </header>

        {error ? (
          <section className="notice error">
            <AlertTriangle size={18} />
            <span>{error}</span>
          </section>
        ) : null}

        <section id="overview" className="metrics-grid">
          <Metric label="Total capacity" value={formatBytes(capacity.total)} detail={`${driveCount} volumes`} />
          <Metric label="Used" value={formatBytes(capacity.used)} detail={`${usedPercent.toFixed(1)}% allocated`} />
          <Metric label="Available" value={formatBytes(capacity.free)} detail="Across fixed volumes" />
          <Metric
            label="Active alerts"
            value={String(alertCount)}
            detail={alertCount > 0 ? "Needs attention" : "Clear"}
            tone={alertCount > 0 ? "warn" : "ok"}
          />
        </section>

        <section className="content-grid">
          <div className="panel drives-panel">
            <div className="panel-heading">
              <h2>Volumes</h2>
              <span>{driveCount}</span>
            </div>
            <div className="drive-list">
              {(snapshot?.drives ?? []).map((drive) => (
                <DriveCard key={drive.id} drive={drive} />
              ))}
              {status === "connecting" ? <p className="muted">Connecting to backend...</p> : null}
            </div>
          </div>

          <div className="right-column">
            <ActivityPanel snapshot={snapshot} />
            <AlertsPanel alerts={snapshot?.alerts ?? []} events={events} />
          </div>
        </section>

        <FolderScannerPanel />
      </section>
    </main>
  );
}

function Metric({
  label,
  value,
  detail,
  tone,
}: {
  label: string;
  value: string;
  detail: string;
  tone?: "ok" | "warn";
}) {
  return (
    <div className={`metric ${tone ?? ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <em>{detail}</em>
    </div>
  );
}
