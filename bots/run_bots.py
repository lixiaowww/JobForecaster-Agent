#!/usr/bin/env python3
"""Launch crowd contribution chat bots.

  python -m bots.run_bots telegram
  python -m bots.run_bots discord
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "telegram"
    if which == "telegram":
        from bots.telegram_bot import run_telegram_bot
        run_telegram_bot()
    elif which == "discord":
        from bots.discord_bot import run_discord_bot
        run_discord_bot()
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
