from __future__ import annotations

import os
from pathlib import Path

from decision_client import DecisionClient, MockDecisionClient


def load_env(path: str | Path | None = None) -> None:
    env_path = Path(path) if path else Path(__file__).with_name(".env")
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def is_mock() -> bool:
    return os.environ.get("DECISION_MOCK", "").strip().lower() in {"1", "true", "yes", "on"}


def build_client(mock: bool = False):
    load_env()
    if mock or is_mock():
        return MockDecisionClient()
    return DecisionClient.from_env()
