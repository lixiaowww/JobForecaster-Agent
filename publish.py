"""Publishing layer. Renders a report (Markdown + HTML + RSS) and ships it.

Backends are pluggable:
  - FilePublisher   : writes a static site (host on GitHub Pages / Netlify / S3)
  - WebhookPublisher: posts a summary to Slack / Discord / any webhook
  - GitPublisher    : commits + pushes the static site to a git remote

A review gate (config: require_review) writes to ./pending/ instead of going live,
so a human can approve before anything is published to the world.
"""
from __future__ import annotations

import json
import subprocess
from datetime import date, datetime
from pathlib import Path

import requests

try:
    from schemas import Prediction
except ImportError:
    from .schemas import Prediction

DISCLAIMER = (
    "These are automatically generated, speculative forecasts produced by an AI agent. "
    "They are not financial, investment, or economic advice. Confidence values are the "
    "model's own estimates and the track record is self-scored."
)


def render_markdown(new_preds: list[Prediction], scoreboard: dict) -> str:
    today = date.today().isoformat()
    lines = [f"# AI x Economy Forecast — {today}", ""]
    sb = scoreboard
    lines += [
        "## Calibration scoreboard",
        f"- Total predictions: **{sb['total']}**  |  open: {sb['open']}  |  "
        f"resolved: {sb['resolved']}  |  ambiguous: {sb['ambiguous']}",
        f"- Mean Brier score: **{sb['mean_brier']}** "
        f"_(0 = perfect, 0.25 = a 50/50 guess, lower is better)_",
        "",
    ]
    if sb["calibration"]:
        lines += ["| confidence band | n | avg confidence | actual hit rate |",
                  "|---|---|---|---|"]
        for c in sb["calibration"]:
            lines.append(
                f"| {c['bucket']} | {c['n']} | {c['avg_confidence']} | {c['actual_hit_rate']} |")
        lines.append("")

    lines += [f"## New predictions ({len(new_preds)})", ""]
    for p in sorted(new_preds, key=lambda x: x.confidence, reverse=True):
        lines += [
            f"### {p.statement}",
            f"- **Confidence:** {p.confidence:.0%}  |  **Category:** {p.category}  "
            f"|  **Resolves:** {p.resolution_date} ({p.horizon})",
            f"- **Why:** {p.rationale}",
            f"- **Resolution test:** {p.resolution_criteria}",
        ]
        if p.sources:
            lines.append("- **Sources:** " + ", ".join(p.sources))
        lines.append("")
    lines += ["---", f"_{DISCLAIMER}_"]
    return "\n".join(lines)


def render_html(markdown_text: str) -> str:
    # minimal, dependency-light: render markdown if available, else <pre>
    try:
        import markdown  # type: ignore
        body = markdown.markdown(markdown_text, extensions=["tables"])
    except Exception:
        body = f"<pre>{markdown_text}</pre>"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI x Economy Forecast</title>
<style>
 body{{max-width:760px;margin:2rem auto;padding:0 1rem;
      font:16px/1.6 system-ui,sans-serif;color:#1a1a1a}}
 table{{border-collapse:collapse;width:100%}} td,th{{border:1px solid #ddd;padding:.4rem .6rem}}
 h1{{border-bottom:2px solid #eee;padding-bottom:.3rem}} code,pre{{background:#f6f6f6}}
</style></head><body>{body}</body></html>"""


class FilePublisher:
    name = "file"

    def __init__(self, out_dir: str = "site"):
        self.out = Path(out_dir)
        self.out.mkdir(parents=True, exist_ok=True)

    def publish(self, md: str, html: str, new_preds: list[Prediction]) -> str:
        stamp = date.today().isoformat()
        (self.out / f"{stamp}.md").write_text(md)
        (self.out / "index.html").write_text(html)
        # append to a JSON feed for programmatic consumers
        feed_path = self.out / "feed.json"
        feed = json.loads(feed_path.read_text()) if feed_path.exists() else []
        feed.insert(0, {"date": stamp,
                        "predictions": [p.model_dump(mode="json") for p in new_preds]})
        feed_path.write_text(json.dumps(feed[:200], indent=2, default=str))
        return str(self.out / "index.html")


class WebhookPublisher:
    name = "webhook"

    def __init__(self, url: str):
        self.url = url

    def publish(self, md: str, html: str, new_preds: list[Prediction]) -> str:
        top = sorted(new_preds, key=lambda x: x.confidence, reverse=True)[:3]
        text = f"*AI x Economy Forecast — {date.today()}*\n" + "\n".join(
            f"• ({p.confidence:.0%}) {p.statement}" for p in top)
        try:
            requests.post(self.url, json={"text": text}, timeout=20)
        except Exception as e:
            print(f"  ! webhook failed: {e}")
        return self.url


class GitPublisher:
    """Writes the static site then commits + pushes it (e.g. to a GitHub Pages repo)."""
    name = "git"

    def __init__(self, repo_dir: str, branch: str = "main"):
        self.repo = Path(repo_dir)
        self.branch = branch
        self.file = FilePublisher(out_dir=str(self.repo))

    def publish(self, md: str, html: str, new_preds: list[Prediction]) -> str:
        path = self.file.publish(md, html, new_preds)
        try:
            subprocess.run(["git", "-C", str(self.repo), "add", "-A"], check=True)
            subprocess.run(["git", "-C", str(self.repo), "commit",
                            "-m", f"forecast {date.today()}"], check=True)
            subprocess.run(["git", "-C", str(self.repo), "push", "origin", self.branch],
                           check=True)
        except subprocess.CalledProcessError as e:
            print(f"  ! git publish failed: {e}")
        return path


def publish_or_queue(publishers, md, html, new_preds, *, require_review: bool):
    if require_review:
        pending = Path("pending")
        pending.mkdir(exist_ok=True)
        stamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
        (pending / f"{stamp}.md").write_text(md)
        (pending / f"{stamp}.json").write_text(
            json.dumps([p.model_dump(mode="json") for p in new_preds], default=str, indent=2))
        print(f"  → queued for review: pending/{stamp}.md "
              f"(approve with: python run.py approve)")
        return []
    targets = []
    for pub in publishers:
        targets.append(pub.publish(md, html, new_preds))
        print(f"  → published via {pub.name}: {targets[-1]}")
    return targets
