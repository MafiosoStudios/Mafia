from __future__ import annotations

import asyncio
import logging
from typing import Callable, Awaitable, Any
import discord

logger = logging.getLogger(__name__)


class DebouncedUpdater:
    """Debounces repetitive message/embed update calls to prevent Discord HTTP 429 rate limits.
    
    Ensures that rapid bursts of updates (e.g. votes cast, night actions submitted, lobby joins)
    coalesce into a single API edit per `delay` window.
    """

    def __init__(self, update_func: Callable[[], Awaitable[Any]], delay: float = 1.2) -> None:
        self.update_func = update_func
        self.delay = delay
        self._task: asyncio.Task[None] | None = None
        self._pending = False

    def request_update(self) -> None:
        self._pending = True
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        await asyncio.sleep(self.delay)
        while self._pending:
            self._pending = False
            try:
                await self.update_func()
            except discord.HTTPException as http_err:
                if http_err.status == 429:
                    retry_after = getattr(http_err, "retry_after", 1.5) or 1.5
                    logger.warning("Rate limit hit during debounced update. Retrying in %.2fs", retry_after)
                    self._pending = True
                    await asyncio.sleep(retry_after)
                else:
                    logger.error("HTTP error during debounced update: %s", http_err)
            except Exception as exc:
                logger.exception("Unexpected error in debounced update: %s", exc)

    async def flush(self) -> None:
        """Forces an immediate update if there is a pending request."""
        if self._pending:
            self._pending = False
            if self._task and not self._task.done():
                self._task.cancel()
            try:
                await self.update_func()
            except Exception as exc:
                logger.exception("Error flushing debounced update: %s", exc)
