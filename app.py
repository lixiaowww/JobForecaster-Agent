"""Hugging Face Spaces entrypoint.

HF runs: streamlit run app.py
This imports dashboard.py (all Streamlit widgets register at import time).
"""
from __future__ import annotations

import dashboard  # noqa: F401
