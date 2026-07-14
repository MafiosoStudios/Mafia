from __future__ import annotations

import asyncio
import logging
from typing import Any

import discord

logger = logging.getLogger(__name__)


class DiscordMessageQueue:
    """Queues all non-urgent outgoing Discord messages to prevent rate limits."""

    def __init__(self, bot: discord.Client) -> None:
        self.bot = bot
        self._queue: asyncio.Queue[tuple[str, Any, tuple[Any, ...], dict[str, Any], asyncio.Future[Any]]] = asyncio.Queue()
        self._worker_task: asyncio.Task[None] | None = None
        self._delay: float = 0.08  # 80ms delay between sending messages is extremely safe and fast

    def start(self) -> None:
        if not self._worker_task:
            self._worker_task = asyncio.create_task(self._loop())
            logger.info("Discord Message Queue worker started.")

    async def stop(self) -> None:
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
            logger.info("Discord Message Queue worker stopped.")

    def send(self, destination: discord.abc.Messageable, *args: Any, **kwargs: Any) -> asyncio.Future[discord.Message]:
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._queue.put_nowait(("send", destination, args, kwargs, fut))
        return fut

    def edit(self, message: discord.Message, *args: Any, **kwargs: Any) -> asyncio.Future[discord.Message]:
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._queue.put_nowait(("edit", message, args, kwargs, fut))
        return fut

    async def _loop(self) -> None:
        while True:
            try:
                action, target, args, kwargs, fut = await self._queue.get()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error reading from message queue.")
                continue

            try:
                # Add a small spacing delay before every API call
                await asyncio.sleep(self._delay)

                if action == "send":
                    res = await target.send(*args, **kwargs)
                elif action == "edit":
                    res = await target.edit(*args, **kwargs)
                else:
                    res = None

                if not fut.done():
                    fut.set_result(res)
            except asyncio.CancelledError:
                if not fut.done():
                    fut.cancel()
                break
            except Exception as e:
                logger.error("Failed to run queued message action %s: %s", action, e)
                if not fut.done():
                    fut.set_exception(e)
            finally:
                self._queue.task_done()
