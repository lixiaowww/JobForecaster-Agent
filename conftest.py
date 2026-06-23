"""pytest configuration.

All tests in this suite run offline (no API key, no network).
The `offline` marker is applied automatically to every test.
"""
import sys
from pathlib import Path

# ensure the project root is importable; never insert the parent (/home/sean)
# because /home/sean/agent is a symlink that causes dual-module SQLAlchemy errors
_project_root = str(Path(__file__).resolve().parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import pytest

def pytest_collection_modifyitems(items):
    for item in items:
        item.add_marker(pytest.mark.offline)
