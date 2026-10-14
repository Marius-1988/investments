"""Bitácora de auditoría (JSONL) de decisiones, órdenes y trades."""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import ROOT
from .models import to_dict


class Journal:
    def __init__(self, directory: Path | None = None):
        self.dir = directory or ROOT / "journal"
        self.dir.mkdir(parents=True, exist_ok=True)

    def _file(self) -> Path:
        return self.dir / f"{datetime.now():%Y-%m-%d}.jsonl"

    def write(self, kind: str, payload: Any) -> None:
        rec = {"ts": time.time(), "kind": kind, "data": to_dict(payload)}
        try:
            with open(self._file(), "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        except OSError:
            pass
