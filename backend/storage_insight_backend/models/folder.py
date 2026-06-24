from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FileTypeStat:
    count: int = 0
    size_bytes: int = 0

    def to_dict(self) -> dict[str, int]:
        return {"count": self.count, "size_bytes": self.size_bytes}


@dataclass
class FolderNode:
    name: str
    path: str
    size_bytes: int = 0
    file_count: int = 0
    dir_count: int = 0
    inaccessible_count: int = 0
    file_types: dict[str, FileTypeStat] = field(default_factory=dict)
    children: list["FolderNode"] = field(default_factory=list)

    def record_file_type(self, extension: str, size_bytes: int) -> None:
        stat = self.file_types.setdefault(extension, FileTypeStat())
        stat.count += 1
        stat.size_bytes += size_bytes

    def merge_file_types(self, child: "FolderNode", max_file_types: int | None = None) -> None:
        for extension, child_stat in child.file_types.items():
            stat = self.file_types.setdefault(extension, FileTypeStat())
            stat.count += child_stat.count
            stat.size_bytes += child_stat.size_bytes
        self.trim_file_types(max_file_types)

    def trim_file_types(self, max_file_types: int | None = None) -> None:
        if max_file_types is None or len(self.file_types) <= max_file_types:
            return

        allowed = {
            extension
            for extension, _ in sorted(
                self.file_types.items(),
                key=lambda item: item[1].size_bytes,
                reverse=True,
            )[:max_file_types]
        }
        for extension in list(self.file_types):
            if extension not in allowed:
                del self.file_types[extension]

    def to_dict(
        self,
        *,
        max_nodes: int | None = None,
        max_file_types: int | None = None,
        include_nested_file_types: bool = False,
    ) -> dict[str, Any]:
        remaining = [max(1, max_nodes)] if max_nodes is not None else None
        return self._to_dict(
            remaining=remaining,
            max_file_types=max_file_types,
            include_nested_file_types=include_nested_file_types,
            is_root=True,
        )

    def _to_dict(
        self,
        *,
        remaining: list[int] | None,
        max_file_types: int | None,
        include_nested_file_types: bool,
        is_root: bool,
    ) -> dict[str, Any]:
        if remaining is not None:
            if remaining[0] <= 0:
                return self._summary_dict(max_file_types=max_file_types, include_file_types=False)
            remaining[0] -= 1

        children: list[dict[str, Any]] = []
        for index, child in enumerate(self.children):
            if remaining is not None and remaining[0] <= 1 and index < len(self.children) - 1:
                remaining[0] = 0
                children.append(_aggregate_children(self.children[index:], self.path)._summary_dict())
                break

            children.append(
                child._to_dict(
                    remaining=remaining,
                    max_file_types=max_file_types,
                    include_nested_file_types=include_nested_file_types,
                    is_root=False,
                )
            )

        include_file_types = is_root or include_nested_file_types
        return {
            "name": self.name,
            "path": self.path,
            "size_bytes": self.size_bytes,
            "file_count": self.file_count,
            "dir_count": self.dir_count,
            "inaccessible_count": self.inaccessible_count,
            "file_types": self._file_types_dict(max_file_types) if include_file_types else {},
            "children": children,
        }

    def _summary_dict(
        self,
        *,
        max_file_types: int | None = None,
        include_file_types: bool = False,
    ) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "size_bytes": self.size_bytes,
            "file_count": self.file_count,
            "dir_count": self.dir_count,
            "inaccessible_count": self.inaccessible_count,
            "file_types": self._file_types_dict(max_file_types) if include_file_types else {},
            "children": [],
        }

    def _file_types_dict(self, max_file_types: int | None = None) -> dict[str, dict[str, int]]:
        items = sorted(self.file_types.items(), key=lambda item: item[1].size_bytes, reverse=True)
        if max_file_types is not None:
            items = items[: max(0, max_file_types)]
        return {extension: stat.to_dict() for extension, stat in items}


def _aggregate_children(children: list[FolderNode], parent_path: str) -> FolderNode:
    aggregate = FolderNode(name="Other", path=f"{parent_path}\\*")
    for child in children:
        aggregate.size_bytes += child.size_bytes
        aggregate.file_count += child.file_count
        aggregate.dir_count += child.dir_count + 1
        aggregate.inaccessible_count += child.inaccessible_count
    return aggregate
