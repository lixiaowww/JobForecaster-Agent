"""Shared crowd bot command parsing (Telegram + Discord)."""
from __future__ import annotations

from services.crowd_service import get_blind_contribution_target, get_crowd_result, submit_contribution
from services.config_loader import load_config


def format_blind_target(target_id: str) -> str:
    data = get_blind_contribution_target(target_id)
    return (
        f"📋 Prediction `{data['id']}`\n"
        f"Statement: {data['statement']}\n"
        f"Resolves: {data['resolution_date']}\n"
        f"Criteria: {data['resolution_criteria']}\n\n"
        "Submit with:\n"
        f"`/submit {target_id} <probability> | <argument> | <url1,url2>`"
    )


def parse_submit_line(text: str) -> tuple[str, float, str, list[str]]:
    """Parse: `<id> <prob> | <argument> | <url1,url2>`"""
    parts = [p.strip() for p in text.split("|")]
    if len(parts) < 3:
        raise ValueError("format: <prediction_id> <probability> | <argument> | <url1,url2>")
    head = parts[0].split(None, 1)
    if len(head) < 2:
        raise ValueError("first segment needs prediction_id and probability")
    target_id = head[0]
    probability = float(head[1])
    argument = parts[1]
    urls = [u.strip() for u in parts[2].split(",") if u.strip()]
    if not urls:
        raise ValueError("at least one evidence URL required")
    return target_id, probability, argument, urls


def handle_submit(contributor_id: str, text: str) -> str:
    target_id, prob, argument, urls = parse_submit_line(text)
    result = submit_contribution(
        target_id,
        contributor_id,
        prob,
        argument,
        urls,
        cfg=load_config(),
    )
    d = result["your_decision"]
    return (
        f"✅ Contribution `{result['contribution_id']}` recorded.\n"
        f"Gate: admitted={d['admitted']} reason={d['reason']}\n"
        f"View aggregate: `/crowd {target_id}` (after you submitted)"
    )


def handle_crowd(contributor_id: str, target_id: str) -> str:
    data = get_crowd_result(target_id, contributor_id)
    return (
        f"📊 Crowd aggregate for `{target_id}`: "
        f"{data['aggregate_probability']:.1%} "
        f"({data['selected_contribution_count']} admitted)"
    )


def dispatch_command(contributor_id: str, command: str, args: str) -> str:
    cmd = command.lower().lstrip("/")
    if cmd in ("start", "help"):
        return (
            "forecaster-agent crowd bot\n"
            "/contribute <prediction_id> — blind target (no agent prior)\n"
            "/submit <id> <prob> | <argument> | <url1,url2>\n"
            "/crowd <prediction_id> — aggregate (after you submitted)"
        )
    if cmd == "contribute":
        if not args.strip():
            raise ValueError("usage: /contribute <prediction_id>")
        return format_blind_target(args.strip().split()[0])
    if cmd == "submit":
        if not args.strip():
            raise ValueError("usage: /submit <id> <prob> | <argument> | <urls>")
        return handle_submit(contributor_id, args.strip())
    if cmd == "crowd":
        if not args.strip():
            raise ValueError("usage: /crowd <prediction_id>")
        return handle_crowd(contributor_id, args.strip().split()[0])
    raise ValueError(f"unknown command: {command}")
