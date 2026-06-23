#!/usr/bin/env python3
"""P1.2 — Follow-up Digest CLI.

Lists JobFeedback records where the 6-month follow-up window has passed
but no response has been recorded. Outputs a CSV for manual outreach.

Usage:
    python followup_digest.py             # list due follow-ups (default)
    python followup_digest.py --due       # explicit flag for due follow-ups
    python followup_digest.py --all       # all follow-up records regardless of status
    python followup_digest.py --stats     # summary statistics

Design (harness conventions):
- No SMTP or external dependencies (offline-safe)
- Pure read: no DB mutations
- Output to stdout in CSV or human-readable format
"""
from __future__ import annotations

import csv
import sys
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

# Ensure project root is importable
_here = Path(__file__).resolve().parent
if str(_here) not in sys.path:
    sys.path.insert(0, str(_here))
sys.path = [p for p in sys.path if p != '/home/sean']

from sqlmodel import Session, select
from schemas import engine, JobFeedback


def get_due_followups() -> list[JobFeedback]:
    """Return feedback records whose follow-up is due and not yet received."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with Session(engine) as session:
        results = session.exec(
            select(JobFeedback).where(
                JobFeedback.email != None,           # opted in  # noqa: E711
                JobFeedback.follow_up_due_at != None,  # noqa: E711
                JobFeedback.follow_up_received == False,
            )
        ).all()
    return [r for r in results if r.follow_up_due_at and r.follow_up_due_at <= now]


def get_all_followups() -> list[JobFeedback]:
    """Return all feedback records that opted into follow-up."""
    with Session(engine) as session:
        return list(session.exec(
            select(JobFeedback).where(JobFeedback.email != None)  # noqa: E711
        ).all())


def to_csv(records: list[JobFeedback]) -> str:
    """Serialize records to CSV string."""
    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "id", "email", "job_title", "industry", "status",
        "transition_target", "confidence", "created_at",
        "follow_up_due_at", "follow_up_received", "outcome_verified",
    ])
    for r in records:
        writer.writerow([
            r.id, r.email, r.job_title, r.industry, r.status,
            r.transition_target or "", round(r.confidence, 2),
            r.created_at.isoformat() if r.created_at else "",
            r.follow_up_due_at.isoformat() if r.follow_up_due_at else "",
            r.follow_up_received, r.outcome_verified,
        ])
    return buf.getvalue()


def print_stats() -> None:
    """Print summary statistics about the follow-up cohort."""
    all_fb = get_all_followups()
    due = get_due_followups()
    received = [r for r in all_fb if r.follow_up_received]
    verified_ok = [r for r in received if r.outcome_verified is True]
    verified_fail = [r for r in received if r.outcome_verified is False]

    print(f"Follow-up cohort (opted-in):  {len(all_fb)}")
    print(f"  Due now (not yet responded): {len(due)}")
    print(f"  Responses received:          {len(received)}")
    print(f"  Transition verified SUCCESS: {len(verified_ok)}")
    print(f"  Transition verified FAILED:  {len(verified_fail)}")
    if received:
        success_rate = len(verified_ok) / len(received) * 100
        print(f"  Verified success rate:       {success_rate:.1f}%")


def main() -> None:
    args = sys.argv[1:]

    if "--stats" in args:
        print_stats()
        return

    if "--all" in args:
        records = get_all_followups()
        label = "all opted-in"
    else:
        # Default: --due
        records = get_due_followups()
        label = "due"

    if not records:
        print(f"No {label} follow-up records found.", file=sys.stderr)
        return

    print(f"# {len(records)} {label} follow-up record(s) — {datetime.utcnow().date().isoformat()}")
    print(to_csv(records), end="")


if __name__ == "__main__":
    main()
