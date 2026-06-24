import { FolderOpen, FolderSearch, Loader2, X } from "lucide-react";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { backendClient } from "../../services/backendClient";
import type { BackendEvent, FolderNode, FolderScanProgress, FolderScanResult } from "../../types/backend";
import { Treemap } from "../treemap/Treemap";
import { formatBytes } from "../../utils/format";

export function FolderScannerPanel() {
  const [path, setPath] = useState("C:\\");
  const [result, setResult] = useState<FolderScanResult | null>(null);
  const [progress, setProgress] = useState<FolderScanProgress | null>(null);
  const [scanId, setScanId] = useState<string | null>(null);
  const scanIdRef = useRef<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [selectedNode, setSelectedNode] = useState<FolderNode | null>(null);
  const [openingFolder, setOpeningFolder] = useState(false);

  useEffect(() => {
    scanIdRef.current = scanId;
  }, [scanId]);

  useEffect(() => {
    let mounted = true;
    let unlisten: (() => void) | undefined;

    backendClient.listen(async (event: BackendEvent) => {
      if (!mounted) return;
      if (event.event === "scanner.progress") {
        const payload = event.payload as FolderScanProgress;
        const activeScanId = scanIdRef.current;
        if (!activeScanId || payload.scan_id === activeScanId) {
          setProgress(payload);
        }
      }

      if (event.event === "scanner.completed" || event.event === "scanner.cancelled") {
        const payload = event.payload as { scan_id: string };
        const activeScanId = scanIdRef.current;
        if (activeScanId && payload.scan_id !== activeScanId) return;
        try {
          const next = await backendClient.folderScanResult(payload.scan_id);
          if (!mounted) return;
          setResult(next);
          setProgress(next.progress);
          setSelectedNode(next.root);
        } catch (err) {
          if (mounted) setError(err instanceof Error ? err.message : String(err));
        } finally {
          if (mounted) {
            setLoading(false);
            setScanId(null);
          }
        }
      }

      if (event.event === "scanner.failed") {
        const payload = event.payload as { scan_id: string; message?: string };
        const activeScanId = scanIdRef.current;
        if (activeScanId && payload.scan_id !== activeScanId) return;
        setError(payload.message || "Folder scan failed.");
        setLoading(false);
        setScanId(null);
      }
    }).then((dispose) => {
      unlisten = dispose;
    });

    return () => {
      mounted = false;
      unlisten?.();
    };
  }, []);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setLoading(true);
    setError(null);
    setResult(null);
    setProgress(null);
    setSelectedNode(null);
    try {
      const started = await backendClient.startFolderScan(path);
      setScanId(started.scan_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setLoading(false);
    }
  };

  const cancel = async () => {
    if (!scanId) return;
    try {
      await backendClient.cancelFolderScan(scanId);
      setProgress((current) => (current ? { ...current, cancelled: true } : current));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const openSelectedFolder = async () => {
    if (!selectedNode) {
      setError("Select a folder from scan results first.");
      return;
    }

    setOpeningFolder(true);
    setError(null);
    try {
      await backendClient.openFolder(selectedNode.path);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setOpeningFolder(false);
    }
  };

  const topTypes = useMemo(() => {
    return Object.entries(result?.file_types ?? {})
      .slice(0, 6)
      .map(([extension, stat]) => ({ extension, ...stat }));
  }, [result]);

  return (
    <section id="scanner" className="scanner-section">
      <div className="panel-heading">
        <h2>Folder size analysis</h2>
        {result ? <span>{formatBytes(result.root.size_bytes)}</span> : null}
      </div>

      <form className="scanner-form" onSubmit={submit}>
        <label htmlFor="folder-path">Folder path</label>
        <input
          id="folder-path"
          value={path}
          onChange={(event) => setPath(event.target.value)}
          spellCheck={false}
        />
        <button type="submit" disabled={loading}>
          {loading ? <Loader2 size={17} className="spin" /> : <FolderSearch size={17} />}
          Scan
        </button>
        {loading ? (
          <button type="button" className="secondary-button" onClick={cancel} aria-label="Cancel scan">
            <X size={17} />
          </button>
        ) : null}
        <button
          type="button"
          className="open-folder-button"
          onClick={openSelectedFolder}
          disabled={!selectedNode || openingFolder}
          title={selectedNode ? selectedNode.path : "Run a scan and select a folder first"}
        >
          {openingFolder ? <Loader2 size={17} className="spin" /> : <FolderOpen size={17} />}
          Open Folder
        </button>
      </form>

      {selectedNode ? (
        <div className="scanner-selection" title={selectedNode.path}>
          <span>Selected</span>
          <strong>{selectedNode.path}</strong>
        </div>
      ) : null}

      {progress ? (
        <div className="scan-progress">
          <div>
            <strong>{formatBytes(progress.bytes_scanned)}</strong>
            <span>{progress.scanned_files.toLocaleString()} files</span>
          </div>
          <div>
            <strong>{progress.scanned_dirs.toLocaleString()}</strong>
            <span>folders</span>
          </div>
          <div>
            <strong>{progress.inaccessible_count.toLocaleString()}</strong>
            <span>inaccessible</span>
          </div>
          <p title={progress.current_path}>{progress.current_path}</p>
        </div>
      ) : null}

      {error ? <p className="form-error">{error}</p> : null}

      {topTypes.length > 0 ? (
        <div className="file-type-row">
          {topTypes.map((item) => (
            <span key={item.extension}>
              {item.extension} - {formatBytes(item.size_bytes)}
            </span>
          ))}
        </div>
      ) : null}

      <div className="treemap-shell">
        {result ? (
          <Treemap root={result.root} selectedPath={selectedNode?.path} onSelect={setSelectedNode} />
        ) : (
          <div className="empty-treemap">No scan results yet</div>
        )}
      </div>
    </section>
  );
}
