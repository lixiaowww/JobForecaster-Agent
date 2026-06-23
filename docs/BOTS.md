# Chat bots — crowd contributions (Phase 2b)

## Telegram

```bash
export TELEGRAM_BOT_TOKEN=...
python -m bots.run_bots telegram
```

Commands:

- `/contribute <prediction_id>` — blind target (no agent prior)
- `/submit <id> <prob> | <argument> | <url1,url2>`
- `/crowd <prediction_id>` — aggregate after you have submitted

## Discord

```bash
pip install -r requirements-bots.txt
export DISCORD_BOT_TOKEN=...
python -m bots.run_bots discord
```

Commands: `!crowdhelp`, `!contribute <id>`, `!fcsubmit <id> <prob> | <argument> | <urls>`, `!crowd <id>`

All bots call `services/crowd_service.py` — same anti-anchoring rules as REST API.
