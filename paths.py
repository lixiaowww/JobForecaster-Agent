"""Project root resolution — single source of truth for import bootstrap."""
from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
