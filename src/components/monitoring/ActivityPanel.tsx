import { Gauge } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { DiskActivitySample, MonitoringSnapshot } from "../../types/backend";
import { formatBytes } from "../../utils/format";

interface ActivityPoint {
  timestamp: number;
  read: number;
  write: number;
}

export function ActivityPanel({ snapshot }: { snapshot: MonitoringSnapshot | null }) {
  const disks = snapshot?.activity?.disks ?? [];
  const totals = useMemo(() => aggregateActivity(disks), [disks]);
  const [history, setHistory] = useState<ActivityPoint[]>([]);

  useEffect(() => {
    const timestamp = snapshot?.activity?.timestamp;
    if (!timestamp) return;

    setHistory((current) => {
      if (current[current.length - 1]?.timestamp === timestamp) return current;
      return [...current, { timestamp, read: totals.read, write: totals.write }].slice(-48);
    });
  }, [snapshot?.activity?.timestamp, totals.read, totals.write]);

  return (
    <aside className="panel activity-panel">
      <div className="panel-heading">
        <h2>Disk activity</h2>
        <Gauge size={18} />
      </div>

      <div className="activity-summary">
        <Metric label="Read" value={formatRate(totals.read)} />
        <Metric label="Write" value={formatRate(totals.write)} />
        <Metric label="IOPS" value={formatNumber(totals.iops)} />
        <Metric label="Active" value={totals.active === null ? "n/a" : `${totals.active.toFixed(1)}%`} />
      </div>

      <ActivityChart points={history} />

      <div className="activity-list">
        {disks.slice(0, 8).map((disk) => (
          <div key={disk.disk_name} className="activity-row">
            <strong>{disk.disk_name}</strong>
            <span>R {formatRate(disk.read_bytes_per_second)}</span>
            <span>W {formatRate(disk.write_bytes_per_second)}</span>
            <span>{formatNumber(disk.total_iops)} IOPS</span>
          </div>
        ))}
        {disks.length === 0 ? <p className="muted">Waiting for disk counters...</p> : null}
      </div>
    </aside>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function ActivityChart({ points }: { points: ActivityPoint[] }) {
  if (points.length < 2) {
    return <div className="activity-chart empty">Collecting samples</div>;
  }

  return (
    <svg className="activity-chart" viewBox="0 0 320 92" role="img" aria-label="Read and write speed history">
      <path d="M0 91H320" />
      <polyline className="read-line" points={lineFor(points, "read")} />
      <polyline className="write-line" points={lineFor(points, "write")} />
    </svg>
  );
}

function aggregateActivity(disks: DiskActivitySample[]) {
  const read = disks.reduce((sum, disk) => sum + (disk.read_bytes_per_second ?? 0), 0);
  const write = disks.reduce((sum, disk) => sum + (disk.write_bytes_per_second ?? 0), 0);
  const iops = disks.reduce((sum, disk) => sum + (disk.total_iops ?? 0), 0);
  const activeValues = disks
    .map((disk) => disk.active_time_percent)
    .filter((value): value is number => value !== null);

  return {
    read,
    write,
    iops,
    active: activeValues.length ? Math.max(...activeValues) : null,
  };
}

function lineFor(points: ActivityPoint[], key: "read" | "write") {
  const max = Math.max(1, ...points.flatMap((point) => [point.read, point.write]));
  const width = 320;
  const height = 82;
  const top = 5;
  const step = width / Math.max(points.length - 1, 1);

  return points
    .map((point, index) => {
      const x = index * step;
      const y = top + height - (point[key] / max) * height;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

function formatRate(value: number | null) {
  return `${formatBytes(value ?? 0)}/s`;
}

function formatNumber(value: number | null) {
  if (value === null || !Number.isFinite(value)) return "0";
  if (value >= 1000) return value.toFixed(0);
  if (value >= 100) return value.toFixed(1);
  return value.toFixed(2);
}
