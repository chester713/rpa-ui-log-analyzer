"""Per-analysis artifact store for the progressive pipeline."""

import json
import os
from typing import Any, Optional

_STORE_DIR = os.path.join("data", "progressive")


class StepStore:
    """Persists each pipeline step's output as a JSON file under data/progressive/<aid>/."""

    STEPS = {1: "step1", 2: "step2", 3: "step3", 4: "step4", 5: "step5", 6: "step6"}

    def __init__(self, analysis_id: str):
        self.aid = analysis_id
        self.dir = os.path.join(_STORE_DIR, analysis_id)
        os.makedirs(self.dir, exist_ok=True)

    # ── Low-level ────────────────────────────────────────────────────────────

    def _path(self, key: str) -> str:
        return os.path.join(self.dir, f"{key}.json")

    def has(self, key: str) -> bool:
        return os.path.exists(self._path(key))

    def load(self, key: str) -> Optional[dict]:
        p = self._path(key)
        if not os.path.exists(p):
            return None
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)

    def save(self, key: str, data: Any) -> None:
        with open(self._path(key), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    # ── Step helpers ─────────────────────────────────────────────────────────

    def has_step(self, step_num: int) -> bool:
        return self.has(self.STEPS[step_num])

    def load_step(self, step_num: int) -> Optional[dict]:
        return self.load(self.STEPS[step_num])

    def save_step(self, step_num: int, data: Any) -> None:
        self.save(self.STEPS[step_num], data)

    # ── Class-level ──────────────────────────────────────────────────────────

    @classmethod
    def exists(cls, analysis_id: str) -> bool:
        return os.path.exists(os.path.join(_STORE_DIR, analysis_id, "meta.json"))
