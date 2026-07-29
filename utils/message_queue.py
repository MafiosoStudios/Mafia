from __future__ import annotations

import asyncio
import logging
from typing import Any

import discord

logger = logging.getLogger(__name__)


def _sanitize_v2_kwargs(args: tuple[Any, ...], kwargs: dict[str, Any]) -> tuple[tuple[Any, ...], dict[str, Any]]:
    kwargs = dict(kwargs)
    view = kwargs.get("view") or kwargs.get("embed")
    if view is not None and isinstance(view, discord.ui.LayoutView):
        content_str: str | None = None
        new_args = list(args)
        if new_args and isinstance(new_args[0], str):
            content_str = new_args.pop(0)
        elif "content" in kwargs and isinstance(kwargs["content"], str):
            content_str = kwargs.pop("content")

        if content_str:
            from ui.components import build_v2_layout
            view = build_v2_layout(description=content_str, view=view, footer_text="")
            kwargs["view"] = view
            kwargs.pop("embed", None)
        return tuple(new_args), kwargs
    return args, kwargs


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

            attempts = 0
            while attempts < 3:
                try:
                    # Add a small spacing delay before every API call
                    await asyncio.sleep(self._delay)
                    clean_args, clean_kwargs = _sanitize_v2_kwargs(args, kwargs)

                    if action == "send":
                        res = await target.send(*clean_args, **clean_kwargs)
                    elif action == "edit":
                        res = await target.edit(*clean_args, **clean_kwargs)
                    else:
                        res = None

                    if not fut.done():
                        fut.set_result(res)
                    break
                except asyncio.CancelledError:
                    if not fut.done():
                        fut.cancel()
                    return
                except discord.Forbidden as exc:
                    if getattr(exc, "code", None) == 50278:
                        logger.debug("Cannot send message to user (code 50278 / no mutual guild or DMs blocked): %s", exc)
                        if not fut.done():
                            fut.set_exception(exc)
                        break
                    logger.error("Failed to run queued message action %s: %s", action, exc)
                    if not fut.done():
                        fut.set_exception(exc)
                    break
                except discord.HTTPException as http_exc:
                    if http_exc.status == 429:
                        retry_after = getattr(http_exc, "retry_after", 1.5) or 1.5
                        logger.warning("Discord Rate Limit hit (429). Retrying action %s in %.2fs (attempt %d/3)", action, retry_after, attempts + 1)
                        attempts += 1
                        await asyncio.sleep(retry_after)
                        if attempts >= 3:
                            if not fut.done():
                                fut.set_exception(http_exc)
                    else:
                        logger.error("Failed to run queued message action %s: %s", action, http_exc)
                        if not fut.done():
                            fut.set_exception(http_exc)
                        break
                except Exception as e:
                    logger.error("Failed to run queued message action %s: %s", action, e)
                    if not fut.done():
                        fut.set_exception(e)
                    break
            self._queue.task_done()

