"""Read-only service layer — shared by CLI, dashboard, MCP, and future REST."""
from services.read_model import get_ood_assessment, get_scoreboard, list_open_predictions, search_jobs

__all__ = ["get_scoreboard", "get_ood_assessment", "search_jobs", "list_open_predictions"]
