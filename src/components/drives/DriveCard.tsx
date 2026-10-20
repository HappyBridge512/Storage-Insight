import { HardDrive, Thermometer, Zap } from "lucide-react";
import type { DriveInfo } from "../../types/backend";
import { formatBytes } from "../../utils/format";

export function DriveCard({ drive }: { drive: DriveInfo }) {
  const freePercent = Math.max(0, 100 - drive.percent_used);
  const health = drive.smart.health;
  const smartAvailable = drive.smart.supported && health !== "unknown";
  const displayName = drive.volume_label || drive.mount_point;
  const subtitle = [drive.model, drive.storage_type, drive.file_system, drive.drive_type]
    .filter(Boolean)
    .join(" / ");

  return (
    <article className="drive-card">
      <div className="drive-card-main">
        <div className="drive-icon">
          <HardDrive size={19} />
        </div>

        <div className="drive-title">
          <h3>{displayName}</h3>
          <p>{subtitle}</p>
        </div>

        <span className={`drive-health ${smartAvailable ? health : "unavailable"}`}>
          {smartAvailable ? health : "SMART not reported"}
        </span>
      </div>

      <div className="capacity-bar" aria-label={`Used ${drive.percent_used}%`}>
        <span style={{ width: `${drive.percent_used}%` }} />
      </div>

      <dl className="drive-stats">
        <div>
          <dt>Used</dt>
          <dd>{formatBytes(drive.used_bytes)}</dd>
        </div>
        <div>
          <dt>Free</dt>
          <dd>
            {formatBytes(drive.free_bytes)} <small>{freePercent.toFixed(1)}%</small>
          </dd>
        </div>
        <div>
          <dt>Total</dt>
          <dd>{formatBytes(drive.total_bytes)}</dd>
        </div>
      </dl>

      <footer className="drive-foot">
        <span>
          <Thermometer size={14} />
          {drive.smart.temperature_celsius === null ? "Temperature unavailable" : `${drive.smart.temperature_celsius} C`}
        </span>
        <span title={drive.smart.reason ?? undefined}>
          <Zap size={14} />
          {drive.smart.supported ? drive.smart.source : "SMART unavailable"}
        </span>
      </footer>
    </article>
  );
}
