export type SmartHealth = "ok" | "warning" | "critical" | "unknown";

export interface SmartStatus {
  health: SmartHealth;
  temperature_celsius: number | null;
  supported: boolean;
  source: string | null;
  reason?: string | null;
  power_on_hours?: number | null;
  wear_level_percent?: number | null;
  life_remaining_percent?: number | null;
  available_spare_percent?: number | null;
  reallocated_sectors?: number | null;
  read_errors?: number | null;
  write_errors?: number | null;
  media_errors?: number | null;
  unsafe_shutdowns?: number | null;
  attributes?: SmartAttribute[];
}

export interface SmartAttribute {
  id: number | null;
  name: string;
  value: number | string | null;
  worst: number | null;
  threshold: number | null;
  raw: string | null;
  raw_int: number | null;
  when_failed: string | null;
  source: string;
}

export interface SmartMetrics {
  temperature_celsius: number | null;
  power_on_hours: number | null;
  wear_level_percent: number | null;
  life_remaining_percent: number | null;
  available_spare_percent: number | null;
  reallocated_sectors: number | null;
  read_errors: number | null;
  write_errors: number | null;
  media_errors: number | null;
  unsafe_shutdowns: number | null;
  bytes_read: number | null;
  bytes_written: number | null;
}

export interface SmartDeviceSnapshot {
  device_id: string;
  model: string | null;
  serial: string | null;
  interface: string | null;
  protocol: string | null;
  supported: boolean;
  health: SmartHealth;
  source: string;
  reason: string | null;
  metrics: SmartMetrics;
  attributes: SmartAttribute[];
  updated_at: number | null;
  errors: string[];
}

export interface SmartMonitorSnapshot {
  devices: SmartDeviceSnapshot[];
  errors: string[];
  polling_interval_seconds: number;
  updated_at: number;
}

export interface DriveInfo {
  id: string;
  mount_point: string;
  device: string;
  file_system: string;
  drive_type: string;
  total_bytes: number;
  free_bytes: number;
  used_bytes: number;
  percent_used: number;
  volume_label: string | null;
  physical_device: string | null;
  model: string | null;
  serial: string | null;
  interface_type: string | null;
  storage_bus_type: string | null;
  storage_type: string;
  smart: SmartStatus;
}

export interface IoCounters {
  read_bytes: number;
  write_bytes: number;
  read_count: number;
  write_count: number;
  read_bytes_per_second?: number | null;
  write_bytes_per_second?: number | null;
  read_iops?: number | null;
  write_iops?: number | null;
  total_iops?: number | null;
  active_time_percent?: number | null;
}

export interface AlertInfo {
  id: string;
  fingerprint: string;
  severity: "warning" | "critical" | "info";
  code: string;
  title: string;
  message: string;
  source: string;
  drive_id: string | null;
  disk_name: string | null;
  value: number | string | null;
  threshold: number | string | null;
  metadata: Record<string, unknown>;
  created_at: number;
  last_seen_at: number;
  count: number;
  active: boolean;
}

export interface MonitoringSnapshot {
  drives: DriveInfo[];
  io: Record<string, IoCounters>;
  activity?: DiskActivitySnapshot;
  alerts: AlertInfo[];
}

export interface DiskUsageSnapshot {
  mount_point: string;
  device: string;
  filesystem: string;
  total_bytes: number;
  free_bytes: number;
  used_bytes: number;
  percent_used: number;
}

export interface DiskActivitySample {
  disk_name: string;
  read_bytes_per_second: number | null;
  write_bytes_per_second: number | null;
  read_iops: number | null;
  write_iops: number | null;
  total_iops: number | null;
  active_time_percent: number | null;
  active_time_source: string | null;
  read_bytes_total: number;
  write_bytes_total: number;
  read_count_total: number;
  write_count_total: number;
  read_time_ms_total: number | null;
  write_time_ms_total: number | null;
  busy_time_ms_total: number | null;
}

export interface DiskActivitySnapshot {
  timestamp: number;
  interval_seconds: number;
  disks: DiskActivitySample[];
  usage: DiskUsageSnapshot[];
  errors: string[];
}

export interface FolderNode {
  name: string;
  path: string;
  size_bytes: number;
  file_count: number;
  dir_count: number;
  inaccessible_count: number;
  file_types: Record<string, FileTypeStat>;
  children: FolderNode[];
}

export interface FileTypeStat {
  count: number;
  size_bytes: number;
}

export interface FolderScanProgress {
  scan_id: string;
  path: string;
  current_path: string;
  scanned_files: number;
  scanned_dirs: number;
  bytes_scanned: number;
  inaccessible_count: number;
  cancelled: boolean;
  elapsed_ms: number;
}

export interface FolderScanResult {
  scan_id: string;
  root: FolderNode;
  file_types: Record<string, FileTypeStat>;
  elapsed_ms: number;
  cancelled: boolean;
  progress: FolderScanProgress;
}

export interface BackendEvent<T = unknown> {
  event: string;
  payload: T;
}
