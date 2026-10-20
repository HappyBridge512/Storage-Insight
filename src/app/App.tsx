import { Activity, AlertTriangle, Database, FolderSearch, HardDrive, RefreshCw, Settings2, ShieldCheck } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { AlertsPanel } from "../components/alerts/AlertsPanel";
import { DriveCard } from "../components/drives/DriveCard";
import { ActivityPanel } from "../components/monitoring/ActivityPanel";
import { FolderScannerPanel } from "../components/scanner/FolderScannerPanel";
import type { DriveInfo, MonitoringSnapshot, BackendEvent } from "../types/backend";
import { formatBytes } from "../utils/format";
import { useBackend } from "./providers/BackendProvider";

type Tab = "overview" | "drives" | "scanner" | "settings";
interface PhysicalDriveGroup { key: string; label: string; type: string; drives: DriveInfo[]; total: number; free: number; }

export function App() {
  const { snapshot, events, status, error, refresh } = useBackend();
  const [activeTab, setActiveTab] = useState<Tab>("overview");
  const [isRefreshing, setRefreshing] = useState(false);
  const [selectedDisk, setSelectedDisk] = useState<string | null>(null);
  const capacity = useMemo(() => {
    const drives = snapshot?.drives ?? [];
    const total = drives.reduce((sum, drive) => sum + drive.total_bytes, 0);
    const free = drives.reduce((sum, drive) => sum + drive.free_bytes, 0);
    return { total, free, used: total - free };
  }, [snapshot]);
  const disks = useMemo(() => groupPhysicalDrives(snapshot?.drives ?? []), [snapshot]);
  const usedPercent = capacity.total ? (capacity.used / capacity.total) * 100 : 0;
  const handleRefresh = async () => { setRefreshing(true); try { await refresh(); } finally { setRefreshing(false); } };
  const openDisk = (key: string) => { setSelectedDisk(key); setActiveTab("drives"); };

  return <main className="desktop-shell">
    <header className="app-header">
      <div className="product-title"><span className="product-mark"><Database size={18} /></span><div><h1>Storage Insight</h1><p>Disk capacity, health and activity at a glance</p></div></div>
      <div className="header-actions">
        <div className="last-updated"><span>Last updated</span><strong>{snapshot?.activity?.timestamp ? formatTimestamp(snapshot.activity.timestamp) : "Waiting for data"}</strong></div>
        <span className={`monitor-state ${status}`} title="Disk monitoring status"><i /> {status === "online" ? "Monitoring" : status === "connecting" ? "Connecting" : "Attention needed"}</span>
        <button className="refresh-button" onClick={handleRefresh} disabled={isRefreshing}><RefreshCw size={16} className={isRefreshing ? "spin" : ""} /> Refresh</button>
      </div>
    </header>
    {error ? <section className="notice error"><AlertTriangle size={18} /><span>{error}</span></section> : null}
    <section className="summary-grid" aria-label="Storage summary">
      <Metric label="Total capacity" value={formatBytes(capacity.total)} detail={`${disks.length} physical disks`} />
      <Metric label="Used space" value={formatBytes(capacity.used)} detail={`${usedPercent.toFixed(1)}% of available capacity`} tone="blue" />
      <Metric label="Free space" value={formatBytes(capacity.free)} detail="Across mounted volumes" tone="ok" />
      <Metric label="Active alerts" value={String(snapshot?.alerts.length ?? 0)} detail={snapshot?.alerts.length ? "Needs review" : "All clear"} tone={snapshot?.alerts.length ? "warn" : "ok"} />
    </section>
    <nav className="tabbar" aria-label="Storage Insight sections">
      <TabButton active={activeTab === "overview"} onClick={() => setActiveTab("overview")} icon={<Activity size={16} />}>Overview</TabButton>
      <TabButton active={activeTab === "drives"} onClick={() => setActiveTab("drives")} icon={<HardDrive size={16} />}>Drives</TabButton>
      <TabButton active={activeTab === "scanner"} onClick={() => setActiveTab("scanner")} icon={<FolderSearch size={16} />}>Scanner</TabButton>
      <TabButton active={activeTab === "settings"} onClick={() => setActiveTab("settings")} icon={<Settings2 size={16} />}>Settings</TabButton>
    </nav>
    {activeTab === "overview" ? <Overview disks={disks} snapshot={snapshot} events={events} onOpenDisk={openDisk} /> : null}
    {activeTab === "drives" ? <DrivesView disks={disks} selectedDisk={selectedDisk} /> : null}
    {activeTab === "scanner" ? <FolderScannerPanel /> : null}
    {activeTab === "settings" ? <SettingsView /> : null}
  </main>;
}

function Overview({ disks, snapshot, events, onOpenDisk }: { disks: PhysicalDriveGroup[]; snapshot: MonitoringSnapshot | null; events: BackendEvent[]; onOpenDisk: (key: string) => void }) {
  return <section className="page-grid overview-grid"><div className="overview-main"><ActivityPanel snapshot={snapshot} /><section className="panel compact-disks"><div className="panel-heading"><div><p className="section-kicker">Physical storage</p><h2>Disk overview</h2></div><span>{disks.length}</span></div><div className="compact-disk-list">{disks.map((disk) => <button className="compact-disk" key={disk.key} onClick={() => onOpenDisk(disk.key)}><HardDrive size={18} /><span className="compact-disk-name"><strong>{disk.label}</strong><small>{disk.type} · {disk.drives.length} volume{disk.drives.length === 1 ? "" : "s"}</small></span><span className="compact-disk-capacity"><strong>{formatBytes(disk.free)} free</strong><small>{formatBytes(disk.total)}</small></span></button>)}{disks.length === 0 ? <EmptyState text="Disk inventory will appear when monitoring data is available." /> : null}</div></section></div><AlertsPanel alerts={snapshot?.alerts ?? []} events={events} /></section>;
}

function DrivesView({ disks, selectedDisk }: { disks: PhysicalDriveGroup[]; selectedDisk: string | null }) {
  return <section className="drives-layout"><section className="panel drives-intro"><div><p className="section-kicker">Storage inventory</p><h2>Physical disks and volumes</h2><p className="muted">SMART readings are displayed only when reported by the device or controller.</p></div><span>{disks.length} disks</span></section><div className="physical-drive-list">{disks.map((disk) => <section className={`physical-drive ${selectedDisk === disk.key ? "selected" : ""}`} key={disk.key}><header><div><p className="section-kicker">{disk.type}</p><h2>{disk.label}</h2><p>{formatBytes(disk.total)} total · {formatBytes(disk.free)} free</p></div><div className="disk-usage"><span style={{ width: `${disk.total ? ((disk.total - disk.free) / disk.total) * 100 : 0}%` }} /></div></header><div className="volume-grid">{disk.drives.map((drive) => <DriveCard key={drive.id} drive={drive} />)}</div></section>)}{disks.length === 0 ? <EmptyState text="No physical disks were reported yet." /> : null}</div></section>;
}

function SettingsView() { return <section className="settings-page panel"><ShieldCheck size={22} /><div><p className="section-kicker">Application settings</p><h2>No editable settings available</h2><p className="muted">Storage Insight currently applies its monitoring configuration automatically. Controls will appear here only when they are backed by a saved application setting.</p></div></section>; }
function TabButton({ active, children, icon, onClick }: { active: boolean; children: ReactNode; icon: ReactNode; onClick: () => void }) { return <button className={active ? "tab active" : "tab"} onClick={onClick} aria-current={active ? "page" : undefined}>{icon}{children}</button>; }
function Metric({ label, value, detail, tone }: { label: string; value: string; detail: string; tone?: "ok" | "warn" | "blue" }) { return <article className={`metric ${tone ?? ""}`}><span>{label}</span><strong>{value}</strong><em>{detail}</em></article>; }
function EmptyState({ text }: { text: string }) { return <p className="empty-state">{text}</p>; }
function groupPhysicalDrives(drives: DriveInfo[]): PhysicalDriveGroup[] { const groups = new Map<string, PhysicalDriveGroup>(); for (const drive of drives) { const key = drive.physical_device || drive.serial || drive.model || drive.id; const current = groups.get(key) ?? { key, label: drive.model || drive.physical_device || "Unknown disk", type: drive.storage_type || "unknown", drives: [], total: 0, free: 0 }; current.drives.push(drive); current.total += drive.total_bytes; current.free += drive.free_bytes; groups.set(key, current); } return [...groups.values()]; }
function formatTimestamp(timestamp: number) { return new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(new Date(timestamp * 1000)); }
