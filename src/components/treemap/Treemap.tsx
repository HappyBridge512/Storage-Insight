import type { FolderNode } from "../../types/backend";
import type { CSSProperties } from "react";
import { useEffect, useMemo, useState } from "react";
import { formatBytes } from "../../utils/format";

interface Rect {
  node: FolderNode;
  x: number;
  y: number;
  width: number;
  height: number;
  depth: number;
}

interface TreemapProps {
  root: FolderNode;
  selectedPath?: string | null;
  onSelect?: (node: FolderNode) => void;
}

export function Treemap({ root, selectedPath, onSelect }: TreemapProps) {
  const [stack, setStack] = useState<FolderNode[]>([root]);
  const current = stack[stack.length - 1] ?? root;
  const rects = useMemo(
    () => layoutTreemap(current, 0, 0, 100, 100, 0).filter((rect) => rect.depth > 0),
    [current],
  );

  useEffect(() => {
    setStack([root]);
    onSelect?.(root);
  }, [root]);

  const selectNode = (node: FolderNode) => {
    onSelect?.(node);
    if (node.children.length > 0) {
      setStack((items) => [...items, node]);
    }
  };

  const jumpTo = (index: number) => {
    setStack((items) => {
      const next = items.slice(0, index + 1);
      onSelect?.(next[next.length - 1] ?? root);
      return next;
    });
  };

  return (
    <div className="treemap-wrap">
      <div className="treemap-nav" aria-label="Treemap navigation">
        {stack.map((node, index) => (
          <button key={`${node.path}-${index}`} type="button" onClick={() => jumpTo(index)}>
            {index === 0 ? node.name || node.path : node.name}
          </button>
        ))}
      </div>
      <div className="treemap" role="img" aria-label={`Treemap for ${current.path}`}>
        {rects.map((rect) => (
          <button
            type="button"
            className={`treemap-cell ${rect.node.children.length > 0 ? "zoomable" : ""} ${
              rect.node.path === selectedPath ? "selected" : ""
            }`}
            key={`${rect.node.path}-${rect.depth}`}
            title={`${rect.node.path}\n${formatBytes(rect.node.size_bytes)}`}
            onClick={() => selectNode(rect.node)}
            style={{
              left: `${rect.x}%`,
              top: `${rect.y}%`,
              width: `${rect.width}%`,
              height: `${rect.height}%`,
              "--depth": rect.depth,
            } as CSSProperties}
          >
            {rect.width > 12 && rect.height > 10 ? (
              <>
                <strong>{rect.node.name}</strong>
                <span>{formatBytes(rect.node.size_bytes)}</span>
              </>
            ) : null}
          </button>
        ))}
      </div>
    </div>
  );
}

function layoutTreemap(
  node: FolderNode,
  x: number,
  y: number,
  width: number,
  height: number,
  depth: number,
): Rect[] {
  const rects: Rect[] = [{ node, x, y, width, height, depth }];
  const children = node.children.filter((child) => child.size_bytes > 0).slice(0, 36);
  const total = children.reduce((sum, child) => sum + child.size_bytes, 0);
  if (children.length === 0 || total <= 0 || depth >= 3) {
    return rects;
  }

  let offset = 0;
  const horizontal = width >= height;

  for (const child of children) {
    const share = child.size_bytes / total;
    if (horizontal) {
      const childWidth = width * share;
      rects.push(...layoutTreemap(child, x + offset, y, childWidth, height, depth + 1));
      offset += childWidth;
    } else {
      const childHeight = height * share;
      rects.push(...layoutTreemap(child, x, y + offset, width, childHeight, depth + 1));
      offset += childHeight;
    }
  }

  return rects;
}
