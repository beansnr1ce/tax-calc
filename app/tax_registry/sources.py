from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Protocol

import yaml


class TaxDataSource(Protocol):
    def list_available(self) -> list[tuple[str, int]]: ...

    def load(self, jurisdiction: str, year: int) -> Mapping[str, Any]: ...


class InMemorySource:
    def __init__(self, files: Mapping[tuple[str, int], Mapping[str, Any]]):
        self._files = dict(files)

    def list_available(self) -> list[tuple[str, int]]:
        return list(self._files.keys())

    def load(self, jurisdiction: str, year: int) -> Mapping[str, Any]:
        return self._files[(jurisdiction, year)]


class FilesystemSource:
    def __init__(self, root: Path):
        self._root = Path(root)

    def list_available(self) -> list[tuple[str, int]]:
        result: list[tuple[str, int]] = []
        for jurisdiction_dir in self._root.iterdir():
            if not jurisdiction_dir.is_dir():
                continue
            for yaml_file in jurisdiction_dir.glob("*.yaml"):
                try:
                    year = int(yaml_file.stem)
                except ValueError:
                    continue
                result.append((jurisdiction_dir.name, year))
        return result

    def load(self, jurisdiction: str, year: int) -> Mapping[str, Any]:
        path = self._root / jurisdiction / f"{year}.yaml"
        with path.open() as f:
            return yaml.safe_load(f)
