"""
app/discord_bot.py - Discord Bot (担当者への DM 通知とボタン操作)

FastAPI と同じプロセス・イベントループで動く。Bot は DM を送るだけなので特権インテントは不要。
担当者に DM を送るには、Bot と担当者が同じサーバーに参加している必要がある。
"""
from __future__ import annotations

import asyncio
import logging

import discord

from app import extension_calls as svc
from app.notify import CallCard, NotificationRef

logger = logging.getLogger(__name__)

_STYLES = {
    "success": discord.ButtonStyle.success,
    "danger": discord.ButtonStyle.danger,
}


def _embed(card: CallCard) -> discord.Embed:
    return discord.Embed(title=card.title, description=card.description, color=card.color)


def _view(card: CallCard) -> discord.ui.View | None:
    if not card.buttons:
        return None
    view = discord.ui.View(timeout=None)
    for b in card.buttons:
        if b.style == "link":
            view.add_item(discord.ui.Button(label=b.label, style=discord.ButtonStyle.link, url=b.url))
        else:
            view.add_item(discord.ui.Button(label=b.label, style=_STYLES[b.style], custom_id=b.custom_id))
    return view


class DiscordNotifier:
    def __init__(self, token: str):
        self.token = token
        self.client = discord.Client(intents=discord.Intents.default())
        self._task: asyncio.Task | None = None
        self.client.event(self.on_ready)
        self.client.event(self.on_interaction)

    # --- ライフサイクル ---
    async def start(self) -> None:
        self._task = asyncio.create_task(self.client.start(self.token), name="discord-bot")

    async def stop(self) -> None:
        await self.client.close()
        if self._task:
            self._task.cancel()

    async def on_ready(self) -> None:
        logger.info(f"Discord Bot ログイン: {self.client.user}")

    # --- ボタン ---
    async def on_interaction(self, interaction: discord.Interaction) -> None:
        if interaction.type != discord.InteractionType.component:
            return
        custom_id = (interaction.data or {}).get("custom_id", "")
        if not custom_id.startswith("extcall:"):
            return
        try:
            _, call_id, action = custom_id.split(":")
        except ValueError:
            return
        try:
            await interaction.response.defer()
        except Exception as e:
            logger.warning(f"interaction defer 失敗: {e}")
        user = interaction.user
        name = user.display_name or user.name
        async with svc.session_factory() as db:
            if action == "accept":
                await svc.accept(db, int(call_id), str(user.id), name)
            elif action == "reject":
                await svc.reject(db, int(call_id), str(user.id))

    # --- Notifier ---
    async def send(self, user_id: str, card: CallCard) -> NotificationRef | None:
        await asyncio.wait_for(self.client.wait_until_ready(), timeout=10)
        user = self.client.get_user(int(user_id)) or await self.client.fetch_user(int(user_id))
        msg = await user.send(embed=_embed(card), view=_view(card))
        return NotificationRef(user_id=str(user_id), channel_id=msg.channel.id, message_id=msg.id)

    async def edit(self, ref: NotificationRef, card: CallCard) -> None:
        channel = self.client.get_channel(ref.channel_id) or await self.client.fetch_channel(ref.channel_id)
        msg = await channel.fetch_message(ref.message_id)
        await msg.edit(embed=_embed(card), view=_view(card))
