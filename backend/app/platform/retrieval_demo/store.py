"""Append-only local demo-run store, deliberately separate from production ORM."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


class DemoRunStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def save(self, payload: dict) -> str:
        self.root.mkdir(parents=True, exist_ok=True)
        run_id = f"demo_run_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid4().hex[:12]}"
        record = {"run_id": run_id, "saved_at": datetime.now(timezone.utc).isoformat(), **payload}
        target = self.root / f"{run_id}.json"
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{run_id}.", suffix=".tmp", dir=self.root)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(record, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
                handle.write("\n")
            Path(temporary_name).replace(target)
        finally:
            temporary = Path(temporary_name)
            if temporary.exists():
                temporary.unlink()
        return run_id
