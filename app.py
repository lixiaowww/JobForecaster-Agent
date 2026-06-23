"""Hugging Face Spaces entrypoint (legacy).

HF Docker image runs `streamlit run dashboard.py` directly.
This file remains for local `streamlit run app.py` compatibility.
"""
from __future__ import annotations

import dashboard  # noqa: F401
