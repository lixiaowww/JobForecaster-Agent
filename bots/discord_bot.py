"""Discord bot for crowd contributions (requires discord.py)."""
from __future__ import annotations

import os

from bots.base import dispatch_command
from services.config_loader import load_config


def run_discord_bot() -> None:
    try:
        import discord
        from discord.ext import commands
    except ImportError as e:
        raise RuntimeError("pip install -r requirements-bots.txt") from e

    token = os.environ.get(
        load_config().get("bots", {}).get("discord", {}).get("token_env", "DISCORD_BOT_TOKEN"),
        "",
    ).strip()
    if not token:
        raise RuntimeError("Set DISCORD_BOT_TOKEN to run the Discord bot")

    intents = discord.Intents.default()
    intents.message_content = True
    bot = commands.Bot(command_prefix="!", intents=intents)

    @bot.event
    async def on_ready():
        print(f"[discord] logged in as {bot.user}")

    @bot.command(name="crowdhelp")
    async def crowdhelp(ctx):
        await ctx.send(dispatch_command(str(ctx.author.id), "/help", ""))

    @bot.command(name="contribute")
    async def contribute(ctx, target_id: str):
        try:
            await ctx.send(dispatch_command(f"discord:{ctx.author.id}", "/contribute", target_id))
        except Exception as e:
            await ctx.send(f"❌ {e}")

    @bot.command(name="fcsubmit")
    async def fcsubmit(ctx, *, payload: str):
        try:
            await ctx.send(dispatch_command(f"discord:{ctx.author.id}", "/submit", payload))
        except Exception as e:
            await ctx.send(f"❌ {e}")

    @bot.command(name="crowd")
    async def crowd(ctx, target_id: str):
        try:
            await ctx.send(dispatch_command(f"discord:{ctx.author.id}", "/crowd", target_id))
        except Exception as e:
            await ctx.send(f"❌ {e}")

    bot.run(token)


if __name__ == "__main__":
    run_discord_bot()
